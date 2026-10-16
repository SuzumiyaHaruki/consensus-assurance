package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sync/atomic"
	"testing"
	"time"
)

// caClose shuts the cluster down with a bounded wait. The stock cluster helper
// panics if a replication goroutine is still inside a long snapshot RPC, which
// is a teardown artifact rather than an observation, so keep the exit path
// finite and still clean the temporary directories.
func caClose(c *cluster) {
	var futures []Future
	for _, r := range c.rafts {
		futures = append(futures, r.Shutdown())
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		for _, f := range futures {
			_ = f.Error()
		}
	}()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
	}
	for _, d := range c.dirs {
		_ = os.RemoveAll(d)
	}
}

// assuranceRestoreCounter counts FSM Restore invocations, which is how a
// follower observes each accepted InstallSnapshot.
type assuranceRestoreCounter struct {
	*MockFSM
	restores int64
}

func (f *assuranceRestoreCounter) Restore(inp io.ReadCloser) error {
	if err := f.MockFSM.Restore(inp); err != nil {
		return err
	}
	atomic.AddInt64(&f.restores, 1)
	return nil
}

func (f *assuranceRestoreCounter) restoreCount() int64 { return atomic.LoadInt64(&f.restores) }

func caEmit(fields map[string]interface{}, event string) {
	fields["event"] = event
	b, err := json.Marshal(fields)
	if err != nil {
		fmt.Printf("CA_EVENT {\"event\":\"ca_emit_error\",\"err\":%q}\n", err.Error())
		return
	}
	fmt.Println("CA_EVENT " + string(b))
}

// caWaitLeader returns a node from rs that is the only leader for a few
// consecutive polls, or nil.
func caWaitLeader(rs []*Raft, d time.Duration) *Raft {
	deadline := time.Now().Add(d)
	var last *Raft
	streak := 0
	for time.Now().Before(deadline) {
		var cur *Raft
		n := 0
		for _, r := range rs {
			if r.getState() == Leader {
				cur = r
				n++
			}
		}
		if n == 1 && cur == last {
			streak++
			if streak >= 3 {
				return cur
			}
		} else {
			last = cur
			streak = 0
		}
		time.Sleep(20 * time.Millisecond)
	}
	return nil
}

func caMaxApplied(rs []*Raft) uint64 {
	var out uint64
	for _, r := range rs {
		if a := r.getLastApplied(); a > out {
			out = a
		}
	}
	return out
}

func caLeaders(rs []*Raft) string {
	out := ""
	for _, r := range rs {
		if r.getState() == Leader {
			out += fmt.Sprintf("%s@t%d ", r.localID, r.getCurrentTerm())
		}
	}
	if out == "" {
		return "none"
	}
	return out
}

// caStaleSuffixScenario drives a real three-voter cluster into the state where
// one voter holds a log suffix that extends beyond the snapshot index of the
// current leader, with a lower term, and the leader's log has been trimmed by
// that snapshot. It returns the handles needed to observe the repair path.
func caStaleSuffixScenario(t *testing.T, tag string, trailing uint64, orphanWrites int, monotonic bool) (*cluster, int, *Raft, *Raft, *assuranceRestoreCounter, *SnapshotMeta, bool) {
	conf := inmemConfig(t)
	conf.TrailingLogs = trailing
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = time.Hour

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:       3,
		Bootstrap:   true,
		Conf:        conf,
		MonotonicLogs: monotonic,
		MakeFSMFunc: func() FSM { return &assuranceRestoreCounter{MockFSM: &MockFSM{}} },
	})

	initLeader := c.Leader()
	_ = c.Followers()

	var f Future
	for i := 0; i < 60; i++ {
		f = initLeader.Apply([]byte(fmt.Sprintf("pre-%03d", i)), 0)
	}
	if err := f.Error(); err != nil {
		t.Fatalf("pre apply: %v", err)
	}

	victimIdx := c.IndexOf(initLeader)
	victim := initLeader
	victimFSM := c.fsms[victimIdx].(*assuranceRestoreCounter)
	oldTrans := c.trans[victimIdx]

	// Isolate the leader and let it append entries that never reach a quorum.
	c.Partition([]ServerAddress{victim.localAddr})
	base := victim.LastIndex()
	for i := 0; i < orphanWrites; i++ {
		_ = victim.Apply([]byte(fmt.Sprintf("orphan-%03d", i)), 0)
		if victim.LastIndex()-base >= uint64(orphanWrites) {
			break
		}
		time.Sleep(time.Millisecond)
	}
	deadline := time.Now().Add(3 * time.Second)
	for victim.getState() == Leader && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	orphanLast := victim.LastIndex()

	// Shut the victim down so its term does not escalate while it is away: the
	// restart replays its real on-disk log, keeping the orphan suffix.
	if err := victim.Shutdown().Error(); err != nil {
		t.Fatalf("victim shutdown: %v", err)
	}

	var near []*Raft
	for _, r := range c.rafts {
		if r != victim {
			near = append(near, r)
		}
	}
	leader := caWaitLeader(near, 5*time.Second)
	if leader == nil {
		return c, victimIdx, victim, nil, victimFSM, nil, false
	}
	for i := 0; i < 20; i++ {
		f = leader.Apply([]byte(fmt.Sprintf("post-%03d", i)), 0)
	}
	if err := f.Error(); err != nil {
		return c, victimIdx, victim, leader, victimFSM, nil, false
	}
	if err := leader.Snapshot().Error(); err != nil {
		return c, victimIdx, victim, leader, victimFSM, nil, false
	}
	snaps, err := leader.snapshots.List()
	if err != nil || len(snaps) == 0 {
		return c, victimIdx, victim, leader, victimFSM, nil, false
	}
	snap := snaps[0]
	leaderLast, _ := leader.logs.LastIndex()

	addr, newTrans := NewInmemTransport(oldTrans.LocalAddr())
	cfg := victim.config()
	cfg.LocalID = victim.localID

	restarted, err := NewRaft(&cfg, victim.fsm, victim.logs, victim.stable, victim.snapshots, newTrans)
	if err != nil {
		t.Fatalf("victim restart: %v", err)
	}
	c.rafts[victimIdx] = restarted
	c.trans[victimIdx] = newTrans

	lastLogIdx, lastLogTerm := restarted.getLastLog()
	snapLogIdx, _ := restarted.getLastSnapshot()
	storeFirst, _ := restarted.logs.FirstIndex()
	storeLast, _ := restarted.logs.LastIndex()

	premise := lastLogIdx >= snap.Index && lastLogTerm < snap.Term && orphanLast >= snap.Index
	caEmit(map[string]interface{}{
		"tag":                      tag,
		"victim_id":                string(restarted.localID),
		"victim_peer_index":        victimIdx,
		"victim_restart_addr":      string(addr),
		"victim_last_log_index":    lastLogIdx,
		"victim_last_log_term":     lastLogTerm,
		"victim_last_snapshot_idx": snapLogIdx,
		"victim_store_first":       storeFirst,
		"victim_store_last":        storeLast,
		"victim_orphan_last_index": orphanLast,
		"victim_restores_at_setup": victimFSM.restoreCount(),
		"leader_id":                string(leader.localID),
		"leader_last_index":        leaderLast,
		"leader_snapshot_index":    snap.Index,
		"leader_snapshot_term":     snap.Term,
		"leader_trailing_logs":     trailing,
		"premise_stale_suffix":     premise,
	}, "ca_setup")
	if !premise {
		return c, victimIdx, restarted, leader, victimFSM, snap, false
	}

	// Reconnect the restarted victim to the other two voters.
	for j, ot := range c.trans {
		if j == victimIdx {
			continue
		}
		newTrans.Connect(ot.LocalAddr(), ot)
		ot.Connect(addr, newTrans)
	}
	return c, victimIdx, restarted, leader, victimFSM, snap, true
}

func caRunProbe(t *testing.T, tag string, window time.Duration, trailing uint64, orphanWrites int, monotonic bool, repairAfter time.Duration) {
	c, victimIdx, victim, leader, victimFSM, snap, ready := caStaleSuffixScenario(t, tag, trailing, orphanWrites, monotonic)
	defer caClose(c)
	if !ready {
		caEmit(map[string]interface{}{
			"tag":    tag,
			"reason": "scenario premise not established",
		}, "ca_probe_skipped")
		return
	}

	// Wait for the first InstallSnapshot to land on the victim.
	installDeadline := time.Now().Add(3 * time.Second)
	for victim.getLastApplied() < snap.Index && time.Now().Before(installDeadline) {
		time.Sleep(5 * time.Millisecond)
	}
	time.Sleep(50 * time.Millisecond)

	startApplied := victim.getLastApplied()
	startRestores := victimFSM.restoreCount()
	startLastLogIdx, startLastLogTerm := victim.getLastLog()
	startSnapIdx, _ := victim.getLastSnapshot()

	step := 250 * time.Millisecond
	start := time.Now()
	lastLeaderSet := ""
	leaderSetChanges := 0
	samples := 0
	var (
		repairDone            bool
		appliedBeforeRepair   uint64
		restoresBeforeRepair  int64
		clusterBeforeRepair   uint64
		claimAtRepair         uint64
		newSnapshotIndex      uint64
	)
	for time.Since(start) < window {
		if repairAfter > 0 && !repairDone && time.Since(start) >= repairAfter {
			// Boundary probe: keep writing until the leader's applied index passes
			// the follower's stale claim, then publish a snapshot at that higher
			// index and let the leader offer it. If the account is right, the
			// follower's prev-log checks start matching again once the installed
			// snapshot index exceeds its cached claim.
			appliedBeforeRepair = victim.getLastApplied()
			restoresBeforeRepair = victimFSM.restoreCount()
			clusterBeforeRepair = caMaxApplied(c.rafts)
			claimAtRepair, _ = victim.getLastLog()
			for i := 0; i < 80 && leader.getState() == Leader && leader.getLastApplied() <= claimAtRepair; i++ {
				if err := leader.Apply([]byte(fmt.Sprintf("repair-%03d", i)), time.Second).Error(); err != nil {
					break
				}
			}
			if sf := leader.Snapshot(); sf != nil {
				if err := sf.Error(); err == nil {
					if snaps, err := leader.snapshots.List(); err == nil && len(snaps) > 0 {
						newSnapshotIndex = snaps[0].Index
					}
				}
			}
			repairDone = true
		}
		terms := map[uint64]bool{}
		for _, r := range c.rafts {
			terms[r.getCurrentTerm()] = true
		}
		ls := caLeaders(c.rafts)
		if ls != lastLeaderSet {
			leaderSetChanges++
			lastLeaderSet = ls
			caEmit(map[string]interface{}{
				"tag":                       tag,
				"t_ms":                      time.Since(start).Milliseconds(),
				"victim_id":                 string(victim.localID),
				"leaders":                   ls,
				"victim_term":               victim.getCurrentTerm(),
				"victim_state":              victim.getState().String(),
				"distinct_terms_in_cluster": len(terms),
			}, "ca_leader_set")
		}
		stFirst, _ := victim.logs.FirstIndex()
		stLast, _ := victim.logs.LastIndex()
		llIdx, llTerm := victim.getLastLog()
		lsIdx, _ := victim.getLastSnapshot()
		caEmit(map[string]interface{}{
			"tag":                   tag,
			"t_ms":                  time.Since(start).Milliseconds(),
			"victim_id":             string(victim.localID),
			"victim_applied":        victim.getLastApplied(),
			"victim_commit":         victim.getCommitIndex(),
			"victim_last_log_index": llIdx,
			"victim_last_log_term":  llTerm,
			"victim_snapshot_index": lsIdx,
			"victim_store_first":    stFirst,
			"victim_store_last":     stLast,
			"victim_restores":       victimFSM.restoreCount(),
			"victim_term":           victim.getCurrentTerm(),
			"victim_state":          victim.getState().String(),
			"cluster_max_applied":   caMaxApplied(c.rafts),
		}, "ca_sample")
		// Keep committing new entries so that the cluster frontier moves while
		// the victim's own progress is measured against it.
		for _, l := range c.rafts {
			if l.getState() == Leader {
				_ = l.Apply([]byte(fmt.Sprintf("during-%03d", samples)), 200*time.Millisecond)
				break
			}
		}
		samples++
		time.Sleep(step)
	}

	endApplied := victim.getLastApplied()
	endRestores := victimFSM.restoreCount()
	endLastLogIdx, endLastLogTerm := victim.getLastLog()
	endSnapIdx, _ := victim.getLastSnapshot()
	endStoreFirst, _ := victim.logs.FirstIndex()
	endStoreLast, _ := victim.logs.LastIndex()
	clusterMax := caMaxApplied(c.rafts)
	leaderLast, _ := leader.logs.LastIndex()
	leaderFirst, _ := leader.logs.FirstIndex()

	caEmit(map[string]interface{}{
		"tag":                          tag,
		"victim_id":                    string(victim.localID),
		"victim_peer_index":            victimIdx,
		"window_ms":                    window.Milliseconds(),
		"samples":                      samples,
		"victim_applied_start":         startApplied,
		"victim_applied_end":           endApplied,
		"victim_restores_start":        startRestores,
		"victim_restores_end":          endRestores,
		"victim_last_log_index_start":  startLastLogIdx,
		"victim_last_log_term_start":   startLastLogTerm,
		"victim_last_log_index_end":    endLastLogIdx,
		"victim_last_log_term_end":     endLastLogTerm,
		"victim_snapshot_index_start":  startSnapIdx,
		"victim_snapshot_index_end":    endSnapIdx,
		"victim_store_first_end":       endStoreFirst,
		"victim_store_last_end":        endStoreLast,
		"victim_commit_index_end":      victim.getCommitIndex(),
		"victim_term_end":              victim.getCurrentTerm(),
		"leader_last_index_end":        leaderLast,
		"leader_store_first_end":       leaderFirst,
		"leader_snapshot_index_end":    snap.Index,
		"leader_snapshot_term_end":     snap.Term,
		"cluster_max_applied_end":      clusterMax,
		"distinct_leader_sets_seen":    leaderSetChanges,
		"leader_snapshot_is_unchanged": endSnapIdx == snap.Index,
		"repeated_snapshot_installs":   endRestores > startRestores,
		"stale_claim_persists":         endLastLogIdx >= endSnapIdx && endLastLogTerm < snap.Term,
		"victim_not_caught_up":         endApplied < clusterMax,
		"victim_store_suffix_kept":     endStoreLast > endSnapIdx,
		"victim_applied_active":        endApplied > startApplied,
		"leader_log_trimmed":           leaderFirst > 1,
		"monotonic_log_store":          monotonic,
		"repair_attempted":             repairDone,
		"victim_claim_at_repair":       claimAtRepair,
		"victim_applied_before_repair": appliedBeforeRepair,
		"victim_restores_before_repair": restoresBeforeRepair,
		"cluster_max_applied_before_repair": clusterBeforeRepair,
		"stall_observed_before_repair": repairDone && appliedBeforeRepair < clusterBeforeRepair && restoresBeforeRepair > startRestores,
		"new_snapshot_index_after_repair": newSnapshotIndex,
		"victim_caught_up_within_window": endApplied+3 >= clusterMax,
	}, "ca_probe")

	// Stop the induced snapshot pressure before teardown so the shutdown path
	// stays bounded; this runs after every measured sample.
	c.Disconnect(victim.localAddr)
}

// TestAssurance_StaleSuffixAfterInstallSnapshot drives the trimmed-leader case:
// the leader can only repair the stale follower by shipping a snapshot, and the
// snapshot lands at an index the follower's own (stale) log already covers.
func TestAssurance_StaleSuffixAfterInstallSnapshot(t *testing.T) {
	caRunProbe(t, "trimmed", 3*time.Second, 10, 60, false, 0)
}

// TestAssurance_Control_UntrimmedLeaderRepairsStaleSuffix is the control for
// the same cluster history without log trimming: entries alone repair the
// stale suffix, so the trigger is excluded.
func TestAssurance_Control_UntrimmedLeaderRepairsStaleSuffix(t *testing.T) {
	caRunProbe(t, "untrimmed", 3*time.Second, 1000000, 60, false, 0)
}

// TestAssurance_StaleSuffixAfterInstallSnapshot_MonotonicStore repeats the
// trimmed case with a MonotonicLogStore, where the install path deletes the
// whole log store instead of keeping a suffix above the snapshot index.
func TestAssurance_StaleSuffixAfterInstallSnapshot_MonotonicStore(t *testing.T) {
	caRunProbe(t, "trimmed-monotonic", 3*time.Second, 10, 60, true, 0)
}

// TestAssurance_StaleSuffixAfterInstallSnapshot_HigherSnapshotRepairs probes the
// boundary of the stall: once the leader commits past the follower's stale
// claim and publishes a snapshot above it, the follower is expected to accept
// entries again.
func TestAssurance_StaleSuffixAfterInstallSnapshot_HigherSnapshotRepairs(t *testing.T) {
	caRunProbe(t, "trimmed-repair", 4*time.Second, 10, 60, false, 1200*time.Millisecond)
}

// caPhantomVoteProbe builds a five-voter cluster in which the deposed leader and
// one follower keep an uncommitted suffix while the other three voters commit a
// newer term and publish a snapshot below that suffix, then delivers one
// RequestVote (the stale follower's real log claim, carrying the
// leadership-transfer flag so the known-leader rejection cannot mask the
// log-completeness test) to a phantom holder and to a voter whose cached state
// matches its snapshot.
func caPhantomVoteProbe(t *testing.T, tag string, orphanWrites, postEntries int, configChange string) {
	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = time.Hour
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:       5,
		Bootstrap:   true,
		Conf:        conf,
		MakeFSMFunc: func() FSM { return &assuranceRestoreCounter{MockFSM: &MockFSM{}} },
	})
	defer caClose(c)

	lead := c.Leader()
	_ = c.WaitForFollowers(4)
	for i := 0; i < 40; i++ {
		if err := lead.Apply([]byte(fmt.Sprintf("pre-%03d", i)), 0).Error(); err != nil {
			t.Fatalf("pre apply: %v", err)
		}
	}

	var others []*Raft
	for _, r := range c.rafts {
		if r != lead {
			others = append(others, r)
		}
	}
	staleFollower := others[0]
	majority := others[1:]
	sharedLast := lead.LastIndex()

	// Isolate the deposed leader together with one follower; the pair is still a
	// minority of five, so the suffix they exchange is never committed.
	c.Partition([]ServerAddress{lead.localAddr, staleFollower.localAddr})
	base := lead.LastIndex()
	for i := 0; i < orphanWrites; i++ {
		_ = lead.Apply([]byte(fmt.Sprintf("orphan-%03d", i)), 0)
		if lead.LastIndex()-base >= uint64(orphanWrites) {
			break
		}
		time.Sleep(time.Millisecond)
	}
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) &&
		(staleFollower.LastIndex() < lead.LastIndex() || lead.getState() == Leader) {
		time.Sleep(10 * time.Millisecond)
	}
	suffixLast := lead.LastIndex()
	_, suffixTerm := lead.getLastLog()

	newLeader := caWaitLeader(majority, 5*time.Second)
	if newLeader == nil {
		caEmit(map[string]interface{}{"tag": tag, "reason": "no majority leader"}, "ca_vote_skipped")
		return
	}
	for i := 0; i < postEntries; i++ {
		if err := newLeader.Apply([]byte(fmt.Sprintf("post-%03d", i)), 0).Error(); err != nil {
			caEmit(map[string]interface{}{"tag": tag, "reason": "post apply failed"}, "ca_vote_skipped")
			return
		}
	}
	if err := newLeader.Snapshot().Error(); err != nil {
		caEmit(map[string]interface{}{"tag": tag, "reason": "snapshot failed"}, "ca_vote_skipped")
		return
	}
	snaps, err := newLeader.snapshots.List()
	if err != nil || len(snaps) == 0 {
		caEmit(map[string]interface{}{"tag": tag, "reason": "no snapshot"}, "ca_vote_skipped")
		return
	}
	leaderSnap := snaps[0]

	// Heal the partition and let the minority members install the snapshot, which
	// sits below the suffix they still claim.
	c.FullyConnect()
	installed := func(r *Raft) bool {
		idx, _ := r.getLastSnapshot()
		return idx > 0
	}
	installDeadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(installDeadline) && !(installed(lead) && installed(staleFollower)) {
		time.Sleep(10 * time.Millisecond)
	}

	phantomClaimIdx, phantomClaimTerm := lead.getLastLog()
	phantomSnapIdx, phantomSnapTerm := lead.getLastSnapshot()
	phantomApplied := lead.getLastApplied()
	secondClaimIdx, secondClaimTerm := staleFollower.getLastLog()
	secondSnapIdx, _ := staleFollower.getLastSnapshot()
	consistent := newLeader
	for _, r := range majority {
		if r != newLeader {
			consistent = r
			break
		}
	}
	consClaimIdx, consClaimTerm := consistent.getLastLog()
	consSnapIdx, consSnapTerm := consistent.getLastSnapshot()
	consApplied := consistent.getLastApplied()
	candIdx, candTerm := staleFollower.getLastLog()

	premise := phantomSnapIdx > 0 && phantomClaimIdx >= phantomSnapIdx &&
		secondSnapIdx > 0 && secondClaimIdx >= secondSnapIdx
	caEmit(map[string]interface{}{
		"tag":                            tag,
		"phantom_id":                     string(lead.localID),
		"second_phantom_id":              string(staleFollower.localID),
		"candidate_id":                   string(staleFollower.localID),
		"consistent_id":                  string(consistent.localID),
		"leader_snapshot_index":          leaderSnap.Index,
		"leader_snapshot_term":           leaderSnap.Term,
		"shared_prefix_last_index":       sharedLast,
		"uncommitted_suffix_last_index":  suffixLast,
		"uncommitted_suffix_term":        suffixTerm,
		"phantom_claim_index":            phantomClaimIdx,
		"phantom_claim_term":             phantomClaimTerm,
		"phantom_snapshot_index":         phantomSnapIdx,
		"phantom_snapshot_term":          phantomSnapTerm,
		"phantom_applied_index":          phantomApplied,
		"second_phantom_claim_index":     secondClaimIdx,
		"second_phantom_claim_term":      secondClaimTerm,
		"second_phantom_snapshot_index":  secondSnapIdx,
		"consistent_claim_index":         consClaimIdx,
		"consistent_claim_term":          consClaimTerm,
		"consistent_snapshot_index":      consSnapIdx,
		"consistent_snapshot_term":       consSnapTerm,
		"consistent_applied_index":       consApplied,
		"candidate_last_log_index":       candIdx,
		"candidate_last_log_term":        candTerm,
		"premise_phantom_claims":         premise,
	}, "ca_vote_setup")
	if !premise {
		return
	}

	if configChange != "" {
		// Configuration-change probe: removing a phantom voter still leaves a
		// quorum of consistent voters, while removing a consistent voter leaves a
		// quorum that includes a phantom, whose cached claim blocks every
		// AppendEntries from this leader.
		var target *Raft
		if configChange == "phantom" {
			target = staleFollower
		} else {
			for _, r := range majority {
				if r != newLeader {
					target = r
					break
				}
			}
		}
		if target == nil {
			caEmit(map[string]interface{}{"tag": tag, "reason": "no config target"}, "ca_vote_skipped")
			return
		}
		sizeBefore := 0
		if f := newLeader.GetConfiguration(); f.Error() == nil {
			sizeBefore = len(f.Configuration().Servers)
		}
		start := time.Now()
		fut := newLeader.RemoveServer(target.localID, 0, time.Second)
		done := make(chan error, 1)
		go func() { done <- fut.Error() }()
		committed := false
		errText := ""
		select {
		case err := <-done:
			committed = err == nil
			if err != nil {
				errText = err.Error()
			}
		case <-time.After(5 * time.Second):
			errText = "not committed within window"
		}
		elapsed := time.Since(start).Milliseconds()
		sizeAfter := 0
		if f := newLeader.GetConfiguration(); f.Error() == nil {
			sizeAfter = len(f.Configuration().Servers)
		}
		_, targetIsPhantom := func() (uint64, bool) {
			idx, _ := target.getLastSnapshot()
			claim, _ := target.getLastLog()
			return idx, idx > 0 && claim >= idx
		}()
		caEmit(map[string]interface{}{
			"tag":                    tag,
			"phantom_id":             string(lead.localID),
			"second_phantom_id":      string(staleFollower.localID),
			"leader_id":              string(newLeader.localID),
			"target_id":              string(target.localID),
			"target_is_phantom":      targetIsPhantom,
			"phantom_claim_exceeds_snapshot": phantomClaimIdx > phantomSnapIdx && phantomClaimTerm < phantomSnapTerm,
			"config_size_before":     sizeBefore,
			"config_size_after":      sizeAfter,
			"config_change_committed": committed,
			"config_change_error":    errText,
			"config_change_ms":       elapsed,
			"window_ms":              int64(5000),
		}, "ca_config_probe")

		if !committed {
			// Second change after a blocked one: the leader's latest
			// configuration never committed, so the change gate that requires
			// latestIndex == committedIndex should refuse further requests. The
			// phantom holder is the voter an operator would want to remove.
			start2 := time.Now()
			fut2 := newLeader.RemoveServer(staleFollower.localID, 0, time.Second)
			done2 := make(chan error, 1)
			go func() { done2 <- fut2.Error() }()
			committed2 := false
			errText2 := ""
			select {
			case err := <-done2:
				committed2 = err == nil
				if err != nil {
					errText2 = err.Error()
				}
			case <-time.After(2 * time.Second):
				errText2 = "not committed within window"
			}
			caEmit(map[string]interface{}{
				"tag":                    tag,
				"phantom_id":             string(lead.localID),
				"second_target_id":       string(staleFollower.localID),
				"second_change_error":    errText2,
				"second_change_rejected": errText2 == ErrEnqueueTimeout.Error(),
				"second_change_committed": committed2,
				"second_change_ms":       time.Since(start2).Milliseconds(),
				"window_ms":              int64(2000),
			}, "ca_config_probe2")
		}
		c.Disconnect(lead.localAddr)
		return
	}

	encoded := staleFollower.trans.EncodePeer(staleFollower.localID, staleFollower.localAddr)
	req := &RequestVoteRequest{
		RPCHeader: RPCHeader{
			ProtocolVersion: conf.ProtocolVersion,
			ID:              []byte(staleFollower.localID),
			Addr:            encoded,
		},
		Term:               consistent.getCurrentTerm() + 1,
		Candidate:          encoded,
		LastLogIndex:       candIdx,
		LastLogTerm:        candTerm,
		LeadershipTransfer: true,
	}
	// Both targets are under snapshot pressure from the leader's retry loop, so
	// deliver with bounded retries and record how many attempts each needed.
	deliver := func(target ServerAddress) (RequestVoteResponse, int, bool, string) {
		var resp RequestVoteResponse
		lastErr := ""
		for attempt := 1; attempt <= 6; attempt++ {
			if err := staleFollower.trans.RequestVote(staleFollower.localID, target, req, &resp); err == nil {
				return resp, attempt, true, ""
			}
			lastErr = fmt.Sprintf("%v", staleFollower.trans.RequestVote(staleFollower.localID, target, req, &resp))
			time.Sleep(100 * time.Millisecond)
		}
		return resp, 6, false, lastErr
	}
	phantomResp, phantomAttempts, phantomOK, phantomErr := deliver(lead.localAddr)
	consistentResp, consistentAttempts, consistentOK, consistentErr := deliver(consistent.localAddr)

	caEmit(map[string]interface{}{
		"tag":                            tag,
		"phantom_id":                     string(lead.localID),
		"consistent_id":                  string(consistent.localID),
		"candidate_id":                   string(staleFollower.localID),
		"request_term":                   req.Term,
		"candidate_last_log_index":       req.LastLogIndex,
		"candidate_last_log_term":        req.LastLogTerm,
		"phantom_delivered":              phantomOK,
		"phantom_attempts":               phantomAttempts,
		"consistent_delivered":           consistentOK,
		"consistent_attempts":            consistentAttempts,
		"phantom_delivery_error":         phantomErr,
		"consistent_delivery_error":      consistentErr,
		"consistent_state":               consistent.getState().String(),
		"leader_id_after_probe":          string(newLeader.localID),
		"phantom_granted":                phantomResp.Granted,
		"phantom_response_term":          phantomResp.Term,
		"consistent_granted":             consistentResp.Granted,
		"consistent_response_term":       consistentResp.Term,
		"phantom_claim_exceeds_snapshot": phantomClaimIdx > phantomSnapIdx && phantomClaimTerm < phantomSnapTerm,
		"candidate_lacks_snapshot_term":  req.LastLogTerm < phantomSnapTerm,
		"vote_decision_differs":          phantomResp.Granted != consistentResp.Granted,
	}, "ca_vote_probe")

	c.Disconnect(lead.localAddr)
}

// TestAssurance_PhantomClaimVoteDecision delivers one RequestVote to a phantom
// holder and to a consistent voter in the same five-voter history.
func TestAssurance_PhantomClaimVoteDecision(t *testing.T) {
	caPhantomVoteProbe(t, "phantom-vote", 40, 20, "")
}

// caAuthorityProbe exercises the leadership-transfer control message in a
// healthy three-voter cluster: either the same TimeoutNow payload is delivered
// twice (first to a follower, then again to whoever became leader), or a plain
// RequestVote with the leader's log claim is delivered to a follower instead.
func caAuthorityProbe(t *testing.T, tag string, mode string) {
	conf := inmemConfig(t)
	c := MakeCluster(3, t, conf)
	defer caClose(c)

	lead := c.Leader()
	followers := c.Followers()
	if len(followers) < 2 {
		caEmit(map[string]interface{}{"tag": tag, "reason": "no two followers"}, "ca_auth_skipped")
		return
	}
	target := followers[0]
	sender := followers[1]
	for i := 0; i < 10; i++ {
		if err := lead.Apply([]byte(fmt.Sprintf("auth-%03d", i)), 0).Error(); err != nil {
			t.Fatalf("apply: %v", err)
		}
	}
	leaderBefore := lead
	termBefore := lead.getCurrentTerm()
	header := RPCHeader{
		ProtocolVersion: conf.ProtocolVersion,
		ID:              []byte(lead.localID),
		Addr:            lead.trans.EncodePeer(lead.localID, lead.localAddr),
	}
	payloadIdx, payloadTerm := lead.getLastLog()
	targetIdx, targetTerm := target.getLastLog()
	caEmit(map[string]interface{}{
		"tag":                        tag,
		"mode":                       mode,
		"leader_before":              string(leaderBefore.localID),
		"term_before":                termBefore,
		"target_id":                  string(target.localID),
		"target_last_log_index":      targetIdx,
		"target_last_log_term":       targetTerm,
		"payload_last_log_index":     payloadIdx,
		"payload_last_log_term":      payloadTerm,
		"timeout_now_message_fields": 1,
	}, "ca_auth_setup")

	switch mode {
	case "timeout-now-duplicate":
		var first TimeoutNowResponse
		errFirst := sender.trans.TimeoutNow(lead.localID, target.localAddr,
			&TimeoutNowRequest{RPCHeader: header}, &first)
		newLeader := caWaitLeader(c.rafts, 5*time.Second)
		movedOnce := newLeader != nil && newLeader != leaderBefore
		termAfterFirst := uint64(0)
		leaderAfterFirst := ""
		if newLeader != nil {
			termAfterFirst = newLeader.getCurrentTerm()
			leaderAfterFirst = string(newLeader.localID)
		}
		// Deliver the identical payload again, now to whoever became leader.
		dup := newLeader
		dupDelivered := false
		dupState := ""
		termAfterDup := termAfterFirst
		gapSamples, noLeaderSamples := 0, 0
		writeAttempts, writeRejections := 0, 0
		writeErr := ""
		firstRejMs, lastRejMs := int64(-1), int64(-1)
		if dup != nil {
			var second TimeoutNowResponse
			dupDelivered = sender.trans.TimeoutNow(lead.localID, dup.localAddr,
				&TimeoutNowRequest{RPCHeader: header}, &second) == nil
			// Observe the aftermath: sample the leadership set and attempt a
			// client write on every step, so the cost of the extra election -
			// including any interval in which the node rejects client work - is
			// measured rather than inferred.
			startGap := time.Now()
			for time.Since(startGap) < 1500*time.Millisecond {
				ls := caLeaders(c.rafts)
				gapSamples++
				if ls == "none" {
					noLeaderSamples++
				}
				elapsedMs := time.Since(startGap).Milliseconds()
				writeAttempts++
				if err := dup.Apply([]byte("during-gap"), 200*time.Millisecond).Error(); err != nil {
					writeRejections++
					writeErr = err.Error()
					if firstRejMs < 0 {
						firstRejMs = elapsedMs
					}
					lastRejMs = elapsedMs
				}
				time.Sleep(10 * time.Millisecond)
			}
			termAfterDup = dup.getCurrentTerm()
			dupState = dup.getState().String()
		}
		caEmit(map[string]interface{}{
			"tag":                       tag,
			"mode":                      mode,
			"target_after_duplicate":    string(target.localID),
			"target_id":                 string(target.localID),
			"first_delivered":           errFirst == nil,
			"leadership_moved_on_first": movedOnce,
			"leader_after_first":        leaderAfterFirst,
			"term_after_first":          termAfterFirst,
			"duplicate_delivered":       dupDelivered,
			"duplicate_target_state":    dupState,
			"term_after_duplicate":      termAfterDup,
			"duplicate_caused_election": termAfterDup > termAfterFirst,
			"leaders_after_duplicate":   caLeaders(c.rafts),
			"gap_samples":               gapSamples,
			"no_leader_samples":         noLeaderSamples,
			"leadership_gap_observed":   noLeaderSamples > 0,
			"write_attempts":            writeAttempts,
			"write_rejections":          writeRejections,
			"client_write_error":        writeErr,
			"first_rejection_ms":        firstRejMs,
			"last_rejection_ms":         lastRejMs,
			"any_write_rejected":        writeRejections > 0,
			"rejection_window_ms":       lastRejMs - firstRejMs,
		}, "ca_auth_probe")
	case "plain-vote-control":
		ctrlHeader := RPCHeader{
			ProtocolVersion: conf.ProtocolVersion,
			ID:              []byte(target.localID),
			Addr:            target.trans.EncodePeer(target.localID, target.localAddr),
		}
		ctrlIdx, ctrlTerm := target.getLastLog()
		req := &RequestVoteRequest{
			RPCHeader:    ctrlHeader,
			Term:         target.getCurrentTerm() + 1,
			Candidate:    ctrlHeader.Addr,
			LastLogIndex: ctrlIdx,
			LastLogTerm:  ctrlTerm,
		}
		var resp RequestVoteResponse
		err := sender.trans.RequestVote(lead.localID, target.localAddr, req, &resp)
		time.Sleep(500 * time.Millisecond)
		caEmit(map[string]interface{}{
			"tag":                tag,
			"mode":               mode,
			"target_id":          string(target.localID),
			"delivered":          err == nil,
			"vote_granted":       resp.Granted,
			"response_term":      resp.Term,
			"target_state":       target.getState().String(),
			"target_term":        target.getCurrentTerm(),
			"leader_after":       string(leaderBefore.localID),
			"leadership_changed": leaderBefore.getState() != Leader,
		}, "ca_auth_probe")
	}
}

// TestAssurance_StaleTimeoutNowDuplicate delivers one TimeoutNow payload twice:
// the first copy performs the requested transfer, the second identical copy is
// honoured again by whoever became leader.
func TestAssurance_StaleTimeoutNowDuplicate(t *testing.T) {
	caAuthorityProbe(t, "duplicate-timeout-now", "timeout-now-duplicate")
}

// TestAssurance_Control_PlainVoteRejected is the control for the same history:
// a plain RequestVote carrying the leader's own log claim is rejected because a
// leader is known, so no election follows.
func TestAssurance_Control_PlainVoteRejected(t *testing.T) {
	caAuthorityProbe(t, "plain-vote-control", "plain-vote-control")
}

// TestAssurance_ConfigChangeRemovePhantom removes a phantom voter: the remaining
// four voters still contain three consistent voters, so the change should commit.
func TestAssurance_ConfigChangeRemovePhantom(t *testing.T) {
	caPhantomVoteProbe(t, "config-remove-phantom", 40, 20, "phantom")
}

// TestAssurance_ConfigChangeRemoveConsistent removes a consistent voter: the new
// configuration's quorum then includes a phantom holder, whose cached claim
// blocks every AppendEntries from the leader.
func TestAssurance_ConfigChangeRemoveConsistent(t *testing.T) {
	caPhantomVoteProbe(t, "config-remove-consistent", 40, 20, "consistent")
}
