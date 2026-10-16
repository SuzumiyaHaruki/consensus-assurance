package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"sync/atomic"
	"testing"
	"time"
)

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
func caStaleSuffixScenario(t *testing.T, trailing uint64, orphanWrites int) (*cluster, int, *Raft, *Raft, *assuranceRestoreCounter, *SnapshotMeta, bool) {
	conf := inmemConfig(t)
	conf.TrailingLogs = trailing
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = time.Hour

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:       3,
		Bootstrap:   true,
		Conf:        conf,
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

func caRunProbe(t *testing.T, tag string, window time.Duration, trailing uint64, orphanWrites int) {
	c, victimIdx, victim, leader, victimFSM, snap, ready := caStaleSuffixScenario(t, trailing, orphanWrites)
	defer c.Close()
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
	for time.Since(start) < window {
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
	}, "ca_probe")
}

// TestAssurance_StaleSuffixAfterInstallSnapshot drives the trimmed-leader case:
// the leader can only repair the stale follower by shipping a snapshot, and the
// snapshot lands at an index the follower's own (stale) log already covers.
func TestAssurance_StaleSuffixAfterInstallSnapshot(t *testing.T) {
	caRunProbe(t, "trimmed", 3*time.Second, 10, 60)
}

// TestAssurance_Control_UntrimmedLeaderRepairsStaleSuffix is the control for
// the same cluster history without log trimming: entries alone repair the
// stale suffix, so the trigger is excluded.
func TestAssurance_Control_UntrimmedLeaderRepairsStaleSuffix(t *testing.T) {
	caRunProbe(t, "untrimmed", 3*time.Second, 1000000, 60)
}
