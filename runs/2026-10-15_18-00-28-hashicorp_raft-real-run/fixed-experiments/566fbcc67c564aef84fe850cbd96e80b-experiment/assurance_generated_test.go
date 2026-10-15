// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"bytes"
	"encoding/json"
	"fmt"
	"runtime"
	"strings"
	"testing"
	"time"
)

func caEmit(t *testing.T, ev map[string]interface{}) {
	t.Helper()
	buf, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Printf("CA_EVENT %s\n", buf)
}

func caServers(c Configuration) []string {
	out := make([]string, 0, len(c.Servers))
	for _, s := range c.Servers {
		out = append(out, fmt.Sprintf("%s/%s", s.ID, s.Suffrage))
	}
	return out
}

// caRestartShutdownAndRestart restarts a single-node cluster from its own
// retained stores (log, stable, snapshots) with a fresh in-memory transport,
// exactly like the repository's own restart tests do.
func caRestart(t *testing.T, old *Raft) *Raft {
	t.Helper()
	if err := old.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}
	_, trans := NewInmemTransport(old.localAddr)
	cfg := old.config()
	n, err := NewRaft(&cfg, old.fsm, old.logs, old.stable, old.snapshots, trans)
	if err != nil {
		t.Fatalf("restart NewRaft: %v", err)
	}
	return n
}

func caConf(t *testing.T) *Config {
	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.SnapshotThreshold = 1 << 20 // keep automatic snapshotting out of the way
	conf.SnapshotInterval = time.Hour
	conf.RestoreCommittedLogs = true
	return conf
}

// TestAssurance_RestoreCommittedLogs_NoSnapshot probes the documented
// RestoreCommittedLogs startup path on a node that has committed log entries but
// no snapshot: which configuration does the node hold after NewRaft returns, and
// where does the NewRaft configuration scan start relative to the committed
// index?
func TestAssurance_RestoreCommittedLogs_NoSnapshot(t *testing.T) {
	opts := &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               caConf(t),
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)
	defer c.Close()

	leader := c.Leader()
	for i := 0; i < 10; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("pre-%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply: %v", err)
		}
	}

	store := leader.logs.(CommitTrackingLogStore)
	stagedBefore, err := store.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex before restart: %v", err)
	}
	lastIdx, err := leader.logs.LastIndex()
	if err != nil {
		t.Fatalf("LastIndex before restart: %v", err)
	}
	before := leader.getLatestConfiguration()

	// The first log entry of a bootstrapped cluster is the configuration entry.
	var entry Log
	if err := leader.logs.GetLog(1, &entry); err != nil {
		t.Fatalf("GetLog(1): %v", err)
	}
	var entryConf Configuration
	if entry.Type == LogConfiguration {
		entryConf = DecodeConfiguration(entry.Data)
	}

	n := caRestart(t, leader)
	after := n.getLatestConfiguration()
	storeAfter := n.logs.(CommitTrackingLogStore)
	stagedAfter, err := storeAfter.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex after restart: %v", err)
	}
	lastApplied := n.getLastApplied()
	snapIdx, _ := n.getLastSnapshot()
	scanStart := max(snapIdx, lastApplied) + 1

	caEmit(t, map[string]interface{}{
		"event":                  "restore_committed_logs_no_snapshot",
		"variant":                "no-snapshot",
		"bootstrap_config_index": entry.Index,
		"bootstrap_config_type":  entry.Type.String(),
		"bootstrap_config_servers": caServers(entryConf),
		"staged_commit_index_before_restart": stagedBefore,
		"last_log_index_before_restart":      lastIdx,
		"latest_config_before_restart":       caServers(before),
		"staged_commit_index_after_restart":  stagedAfter,
		"last_applied_after_restart":         lastApplied,
		"last_snapshot_index_after_restart":  snapIdx,
		"config_scan_start_index":            scanStart,
		"config_entry_covered_by_scan":       entry.Index >= scanStart,
		"latest_config_after_restart":        caServers(after),
		"latest_config_after_restart_len":    len(after.Servers),
	})
}

// TestAssurance_RestoreCommittedLogs_SnapshotAndConfigChange probes a restart
// where a configuration entry was committed after the node's last snapshot.
func TestAssurance_RestoreCommittedLogs_SnapshotAndConfigChange(t *testing.T) {
	opts := &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               caConf(t),
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)
	defer c.Close()

	leader := c.Leader()
	for i := 0; i < 20; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("pre-%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply: %v", err)
		}
	}

	if err := leader.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	snaps, err := leader.snapshots.List()
	if err != nil {
		t.Fatalf("list snapshots: %v", err)
	}
	if len(snaps) == 0 {
		t.Fatalf("no snapshot taken")
	}
	snapIdx := snaps[0].Index
	snapConfIdx := snaps[0].ConfigurationIndex
	snapConf := snaps[0].Configuration

	// Commit a configuration change after the snapshot.
	change := leader.AddNonvoter(ServerID("nonvoter-B"), ServerAddress("addr-B"), 0, 0)
	if err := change.Error(); err != nil {
		t.Fatalf("AddNonvoter: %v", err)
	}
	changeIdx := change.Index()

	// Write more entries so the commit-tracking store stages a commit index at
	// or beyond the configuration entry.
	for i := 0; i < 10; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("post-%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply: %v", err)
		}
	}

	store := leader.logs.(CommitTrackingLogStore)
	stagedBefore, err := store.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex before restart: %v", err)
	}
	before := leader.getLatestConfiguration()

	var entry Log
	if err := leader.logs.GetLog(changeIdx, &entry); err != nil {
		t.Fatalf("GetLog(%d): %v", changeIdx, err)
	}

	n := caRestart(t, leader)
	after := n.getLatestConfiguration()
	lastApplied := n.getLastApplied()
	afterSnapIdx, _ := n.getLastSnapshot()
	scanStart := max(afterSnapIdx, lastApplied) + 1

	var loggedConf Configuration
	if entry.Type == LogConfiguration {
		loggedConf = DecodeConfiguration(entry.Data)
	}

	caEmit(t, map[string]interface{}{
		"event":                    "restore_committed_logs_snapshot_and_config_change",
		"variant":                  "snapshot+config-change",
		"snapshot_index":           snapIdx,
		"snapshot_config_index":    snapConfIdx,
		"snapshot_config":          caServers(snapConf),
		"config_entry_index":       changeIdx,
		"config_entry_type":        entry.Type.String(),
		"config_entry_servers":     caServers(loggedConf),
		"staged_commit_index_before_restart": stagedBefore,
		"latest_config_before_restart":       caServers(before),
		"staged_commit_index_after_restart":  mustCommitIndex(t, n),
		"last_applied_after_restart":         lastApplied,
		"config_scan_start_index":            scanStart,
		"config_entry_covered_by_scan":       changeIdx >= scanStart,
		"config_entry_committed_at_restart":  mustCommitIndex(t, n) >= changeIdx,
		"latest_config_after_restart":        caServers(after),
		"latest_config_after_restart_len":    len(after.Servers),
	})
}

func mustCommitIndex(t *testing.T, n *Raft) uint64 {
	t.Helper()
	store := n.logs.(CommitTrackingLogStore)
	idx, err := store.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex: %v", err)
	}
	return idx
}

// caBlockedFrames returns the stack frames of every goroutine that is currently
// blocked, so that a restart that never returns can be attributed to an actual
// call site instead of being attributed by inference.
func caBlockedFrames() []string {
	buf := make([]byte, 1<<20)
	n := runtime.Stack(buf, true)
	var out []string
	for _, line := range strings.Split(string(buf[:n]), "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.Contains(trimmed, "github.com/hashicorp/raft.") ||
			strings.Contains(trimmed, "[chan send]") ||
			strings.Contains(trimmed, "[select]") {
			if len(out) < 40 {
				out = append(out, trimmed)
			}
		}
	}
	return out
}

// caLargeRangeCase commits one kind of history and measures whether the
// RestoreCommittedLogs restart returns within the given bound.
func caLargeRangeCase(t *testing.T, applied int, wait time.Duration) {
	t.Helper()

	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.SnapshotThreshold = 1 << 30 // no automatic snapshot at all
	conf.SnapshotInterval = time.Hour
	conf.RestoreCommittedLogs = true

	opts := &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)
	defer c.Close()

	leader := c.Leader()
	for i := 0; i < applied; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("cmd-%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply %d: %v", i, err)
		}
	}

	staged := mustCommitIndex(t, leader)
	lastIdx, _ := leader.logs.LastIndex()
	firstIdx, _ := leader.logs.FirstIndex()
	snapIdx, _ := leader.getLastSnapshot()
	batches := (staged + uint64(conf.MaxAppendEntries) - 1) / uint64(conf.MaxAppendEntries)
	variant := fmt.Sprintf("committed-range-entries-%d", staged)

	caEmit(t, map[string]interface{}{
		"event":                              "large_committed_range_setup",
		"variant":                            variant,
		"applied_commands":                   applied,
		"first_log_index":                    firstIdx,
		"last_log_index_before_restart":      lastIdx,
		"last_snapshot_index":                snapIdx,
		"staged_commit_index_before_restart": staged,
		"recovery_range_entries":             staged,
		"recovery_range_batches":             batches,
		"fsm_mutate_ch_capacity":             128,
	})

	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}

	_, trans := NewInmemTransport(leader.localAddr)
	cfg := leader.config()
	type restartResult struct {
		raft *Raft
		err  error
	}
	done := make(chan restartResult, 1)
	start := time.Now()
	go func() {
		n, err := NewRaft(&cfg, leader.fsm, leader.logs, leader.stable, leader.snapshots, trans)
		done <- restartResult{raft: n, err: err}
	}()

	select {
	case res := <-done:
		lastApplied, commitIdx := uint64(0), uint64(0)
		cfgLen := 0
		if res.raft != nil {
			lastApplied = res.raft.getLastApplied()
			commitIdx = mustCommitIndex(t, res.raft)
			cfgLen = len(res.raft.getLatestConfiguration().Servers)
			_ = res.raft.Shutdown()
		}
		caEmit(t, map[string]interface{}{
			"event":                             "restart_newraft_completed",
			"variant":                           variant,
			"newraft_returned":                  true,
			"elapsed_ms":                        time.Since(start).Milliseconds(),
			"error":                             fmt.Sprint(res.err),
			"last_applied_after_restart":        lastApplied,
			"staged_commit_index_after_restart": commitIdx,
			"latest_config_after_restart_len":   cfgLen,
			"blocked_frames":                    []string{},
		})
	case <-time.After(wait):
		caEmit(t, map[string]interface{}{
			"event":             "restart_newraft_completed",
			"variant":           variant,
			"newraft_returned":  false,
			"observed_after_ms": wait.Milliseconds(),
			"blocked_frames":    caBlockedFrames(),
		})
	}
}

// TestAssurance_RestoreCommittedLogs_LargeCommittedRange probes whether the
// RestoreCommittedLogs startup path can return at all when the recovered
// committed range needs more FSM batches than the fsmMutateCh buffer, with a
// smaller range as a control.
func TestAssurance_RestoreCommittedLogs_LargeCommittedRange(t *testing.T) {
	caLargeRangeCase(t, 6000, 20*time.Second)
	caLargeRangeCase(t, 9000, 20*time.Second)
}

// TestAssurance_EmptyConfigVoteAdmission drives the restarted node's vote and
// pre-vote handlers over a real in-memory transport with a candidate that is
// absent from the configuration entry recorded in the node's own log.
func TestAssurance_EmptyConfigVoteAdmission(t *testing.T) {
	opts := &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               caConf(t),
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)
	defer c.Close()

	leader := c.Leader()
	for i := 0; i < 10; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("cmd-%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply: %v", err)
		}
	}

	var entry Log
	if err := leader.logs.GetLog(1, &entry); err != nil {
		t.Fatalf("GetLog(1): %v", err)
	}
	var logConf Configuration
	if entry.Type == LogConfiguration {
		logConf = DecodeConfiguration(entry.Data)
	}

	n := caRestart(t, leader)
	live := n.getLatestConfiguration()
	voters := 0
	for _, s := range live.Servers {
		if s.Suffrage == Voter {
			voters++
		}
	}

	// A real transport, wired to the restarted node's transport.
	peerAddr, peerTrans := NewInmemTransport("")
	defer peerTrans.Close()
	own := n.trans.(*InmemTransport)
	own.Connect(peerAddr, peerTrans)
	peerTrans.Connect(n.localAddr, own)

	caEmit(t, map[string]interface{}{
		"event":                    "empty_config_restart_setup",
		"variant":                  "no-snapshot-restart",
		"log_recorded_config":      caServers(logConf),
		"log_recorded_config_len":  len(logConf.Servers),
		"live_config_after_restart": caServers(live),
		"live_config_len":          len(live.Servers),
		"live_voters":              voters,
		"derived_quorum_size":      voters/2 + 1,
	})

	candidateID := ServerID("outsider-not-in-log")
	encoded := peerTrans.EncodePeer(candidateID, peerAddr)
	term := n.getCurrentTerm()

	voteResp := &RequestVoteResponse{}
	verr := peerTrans.RequestVote(candidateID, n.localAddr, &RequestVoteRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: n.config().ProtocolVersion, ID: []byte(candidateID), Addr: encoded},
		Term:         term + 1,
		Candidate:    encoded,
		LastLogIndex: 1 << 40,
		LastLogTerm:  term + 1,
	}, voteResp)

	preResp := &RequestPreVoteResponse{}
	perr := peerTrans.RequestPreVote(candidateID, n.localAddr, &RequestPreVoteRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: n.config().ProtocolVersion, ID: []byte(candidateID), Addr: encoded},
		Term:         n.getCurrentTerm() + 1,
		LastLogIndex: 1 << 40,
		LastLogTerm:  n.getCurrentTerm() + 1,
	}, preResp)

	caEmit(t, map[string]interface{}{
		"event":                        "empty_config_vote_admission",
		"variant":                      "no-snapshot-restart",
		"log_recorded_config":          caServers(logConf),
		"live_config_after_restart":    caServers(live),
		"live_config_len":              len(live.Servers),
		"live_voters":                  voters,
		"derived_quorum_size":          voters/2 + 1,
		"candidate_in_live_config":     inConfiguration(live, candidateID),
		"request_vote_error":           fmt.Sprint(verr),
		"request_vote_granted":         voteResp.Granted,
		"request_vote_term":            voteResp.Term,
		"request_prevote_error":        fmt.Sprint(perr),
		"request_prevote_granted":      preResp.Granted,
		"request_prevote_term":         preResp.Term,
		"node_term_after_requests":     n.getCurrentTerm(),
	})
}

// caConfigChange retries a configuration change on the current leader so that an
// election racing the call does not fail the whole harness.
func caConfigChange(t *testing.T, leader func() *Raft, apply func(l *Raft) error) {
	t.Helper()
	for i := 0; i < 40; i++ {
		l := leader()
		if l != nil {
			err := apply(l)
			if err == nil {
				return
			}
			if err != ErrNotLeader {
				t.Fatalf("configuration change failed: %v", err)
			}
		}
		time.Sleep(25 * time.Millisecond)
	}
	t.Fatalf("configuration change did not succeed")
}

func caPoll(cond func() bool, d time.Duration) bool {
	limit := time.Now().Add(d)
	for time.Now().Before(limit) {
		if cond() {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	return cond()
}

func caFindLeader(rafts ...*Raft) *Raft {
	for _, r := range rafts {
		if r != nil && r.State() == Leader {
			return r
		}
	}
	return nil
}

func caVoters(c Configuration) []string {
	out := []string{}
	for _, s := range c.Servers {
		if s.Suffrage == Voter {
			out = append(out, string(s.ID))
		}
	}
	return out
}

func caHoldsPayload(r *Raft, payload []byte) (bool, uint64) {
	first, err := r.logs.FirstIndex()
	if err != nil {
		return false, 0
	}
	last, err := r.logs.LastIndex()
	if err != nil {
		return false, 0
	}
	for i := first; i > 0 && i <= last; i++ {
		var l Log
		if err := r.logs.GetLog(i, &l); err != nil {
			continue
		}
		if bytes.Equal(l.Data, payload) {
			return true, i
		}
	}
	return false, 0
}

// TestAssurance_StaleConfigCommitQuorum drives the safety consequence of the
// configuration gap: a node restarted with the smaller configuration recorded in
// its snapshot acknowledges a write that is stored by fewer nodes than the true
// configuration's quorum, and a leader elected from the true configuration does
// not have that write.
func TestAssurance_StaleConfigCommitQuorum(t *testing.T) {
	conf := inmemConfig(t)
	conf.HeartbeatTimeout = 200 * time.Millisecond
	conf.ElectionTimeout = 400 * time.Millisecond
	conf.LeaderLeaseTimeout = 200 * time.Millisecond
	conf.CommitTimeout = 20 * time.Millisecond
	conf.TrailingLogs = 10
	conf.SnapshotThreshold = 1 << 30
	conf.SnapshotInterval = time.Hour
	conf.RestoreCommittedLogs = true
	conf.ShutdownOnRemove = false

	c := MakeClusterCustom(t, &MakeClusterOpts{Peers: 5, Bootstrap: true, Conf: conf, CommitTrackingLogs: true})
	// Teardown of this deliberately half-shutdown cluster must not decide the test:
	// every observation is emitted before the deferred cleanup runs.
	defer func() {
		defer func() { _ = recover() }()
		c.Close()
	}()

	roles := []*Raft{c.rafts[0], c.rafts[1], c.rafts[2], c.rafts[3], c.rafts[4]}
	ids := make([]ServerID, len(roles))
	for i, r := range roles {
		ids[i] = r.localID
	}

	// Step 1: shrink the configuration in force to the three-voter set {0,1,2},
	// then snapshot node 2 so that its snapshot records that smaller set.
	ldr := func() *Raft {
		var l *Raft
		caPoll(func() bool {
			l = caFindLeader(roles...)
			return l != nil
		}, 20*time.Second)
		return l
	}
	caConfigChange(t, ldr, func(l *Raft) error { return l.RemoveServer(ids[3], 0, 0).Error() })
	caConfigChange(t, ldr, func(l *Raft) error { return l.RemoveServer(ids[4], 0, 0).Error() })
	// The FSM needs applied commands before it can snapshot at all.
	if l := ldr(); l == nil {
		t.Fatalf("no leader before pre-snapshot traffic")
	} else {
		for i := 0; i < 5; i++ {
			if err := l.Apply([]byte(fmt.Sprintf("pre-snapshot-%d", i)), 5*time.Second).Error(); err != nil {
				t.Fatalf("pre-snapshot apply: %v", err)
			}
		}
	}
	if ok := caPoll(func() bool {
		e := roles[2].Snapshot()
		return e.Error() == nil
	}, 20*time.Second); !ok {
		t.Fatalf("snapshot on node 2 failed")
	}
	snaps, err := roles[2].snapshots.List()
	if err != nil || len(snaps) == 0 {
		t.Fatalf("no snapshot on node 2: %v", err)
	}
	snap := snaps[0]

	// Step 2: restore the five-voter configuration and add traffic so node 2's
	// commit-tracking store stages a commit index past that configuration entry.
	caConfigChange(t, ldr, func(l *Raft) error { return l.AddVoter(ids[3], roles[3].localAddr, 0, 0).Error() })
	caConfigChange(t, ldr, func(l *Raft) error { return l.AddVoter(ids[4], roles[4].localAddr, 0, 0).Error() })
	if l := ldr(); l == nil {
		t.Fatalf("no leader after re-add")
	} else {
		for i := 0; i < 20; i++ {
			if err := l.Apply([]byte(fmt.Sprintf("traffic-%d", i)), 5*time.Second).Error(); err != nil {
				t.Fatalf("traffic apply: %v", err)
			}
		}
	}
	trueConfFuture := roles[2].GetConfiguration()
	_ = trueConfFuture.Error()
	trueConf := trueConfFuture.Configuration()

	caEmit(t, map[string]interface{}{
		"event":                    "stale_config_setup",
		"variant":                  "stale-smaller-config",
		"snapshot_index":           snap.Index,
		"snapshot_config":          caVoters(snap.Configuration),
		"snapshot_config_servers":  caServers(snap.Configuration),
		"snapshot_config_index":    snap.ConfigurationIndex,
		"config_in_force":          caVoters(trueConf),
		"config_in_force_len":      len(trueConf.Servers),
	})

	// Step 3: restart node 2 from its own stores.
	old := roles[2]
	if err := old.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown node 2: %v", err)
	}
	_, trans2 := NewInmemTransport(old.localAddr)
	cfg2 := old.config()
	restarted, err := NewRaft(&cfg2, old.fsm, old.logs, old.stable, old.snapshots, trans2)
	if err != nil {
		t.Fatalf("restart node 2: %v", err)
	}
	roles[2] = restarted
	c.rafts[2] = restarted
	c.trans[2] = trans2
	c.FullyConnect()

	live := restarted.getLatestConfiguration()
	stagedAfter := mustCommitIndex(t, restarted)
	lastIdxRestart, _ := restarted.logs.LastIndex()
	confEntryBeyondSnap := false
	for i := snap.Index + 1; i <= lastIdxRestart; i++ {
		var l Log
		if err := restarted.logs.GetLog(i, &l); err != nil {
			continue
		}
		if l.Type == LogConfiguration {
			confEntryBeyondSnap = true
		}
	}

	caEmit(t, map[string]interface{}{
		"event":                       "stale_config_restart",
		"variant":                     "stale-smaller-config",
		"live_config_after_restart":   caVoters(live),
		"live_config_servers_after_restart": caServers(live),
		"live_voters_after_restart":   len(caVoters(live)),
		"derived_stale_quorum":        len(caVoters(live))/2 + 1,
		"config_in_force":             caVoters(trueConf),
		"config_in_force_voters":      len(caVoters(trueConf)),
		"true_quorum":                 len(caVoters(trueConf))/2 + 1,
		"last_applied_after_restart":  restarted.getLastApplied(),
		"staged_commit_index":         stagedAfter,
		"last_log_index":              lastIdxRestart,
		"log_has_config_entry_beyond_snapshot": confEntryBeyondSnap,
	})

	// Step 4: transfer leadership to node 2, whose voter set is the smaller stale
	// set, while the cluster is still fully connected.
	if l := ldr(); l == nil {
		t.Fatalf("no leader before transfer")
	} else if l == restarted {
		// The restarted node may already have won an election with its stale
		// voter set; that is the same configuration to be measured next.
	} else {
		tf := l.LeadershipTransferToServer(restarted.localID, restarted.localAddr)
		if err := tf.Error(); err != nil {
			t.Fatalf("leadership transfer: %v", err)
		}
	}

	if ok := caPoll(func() bool { return restarted.State() == Leader }, 20*time.Second); !ok {
		caEmit(t, map[string]interface{}{
			"event":   "stale_config_leadership",
			"variant": "stale-smaller-config",
			"transfer_became_leader": false,
			"node2_state":            restarted.State().String(),
		})
		return
	}

	afterTransfer := restarted.getLatestConfiguration()
	caEmit(t, map[string]interface{}{
		"event":                     "stale_config_leadership",
		"variant":                   "stale-smaller-config",
		"transfer_became_leader":    true,
		"leader_id":                 string(restarted.localID),
		"leader_term":               restarted.getCurrentTerm(),
		"live_config_as_leader":     caVoters(afterTransfer),
		"derived_stale_quorum":      len(caVoters(afterTransfer))/2 + 1,
		"config_in_force_voters":    len(caVoters(trueConf)),
		"true_quorum":               len(caVoters(trueConf))/2 + 1,
		"peers_leader_replicates_to": len(restarted.leaderState.replState),
	})

	// Step 4b: isolate node 1 so it cannot hold the write that the stale leader
	// is about to acknowledge.
	c.trans[2].Disconnect(roles[1].localAddr)
	c.trans[1].Disconnect(roles[2].localAddr)

	// Step 5: the write that the stale leader acknowledges.
	payload := []byte("acknowledged-under-stale-quorum")
	writeFuture := restarted.Apply(payload, 5*time.Second)
	writeErr := writeFuture.Error()
	writeIndex := writeFuture.Index()

	holders := map[string]bool{}
	for i, r := range roles {
		if has, idx := caHoldsPayload(r, payload); has {
			holders[string(r.localID)] = true
			_ = i
			_ = idx
		}
	}
	holderCount := 0
	for _, v := range holders {
		if v {
			holderCount++
		}
	}

	caEmit(t, map[string]interface{}{
		"event":                 "stale_config_write",
		"variant":               "stale-smaller-config",
		"apply_error":           fmt.Sprint(writeErr),
		"write_acknowledged":    writeErr == nil,
		"write_index":           writeIndex,
		"write_holders":         holders,
		"write_holders_count":   holderCount,
		"write_backed_by_true_quorum": holderCount >= len(caVoters(trueConf))/2+1,
		"derived_stale_quorum":  len(caVoters(afterTransfer))/2 + 1,
		"config_in_force_voters": len(caVoters(trueConf)),
		"true_quorum":           len(caVoters(trueConf))/2 + 1,
	})

	// Step 6: remove both holders of the write and let the remaining voters of
	// the configuration in force elect a leader.
	if err := restarted.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown node 2: %v", err)
	}
	for i, r := range roles {
		if i == 2 {
			continue
		}
		if has, _ := caHoldsPayload(r, payload); has {
			if err := r.Shutdown().Error(); err != nil {
				t.Fatalf("shutdown holder %d: %v", i, err)
			}
			roles[i] = nil
		}
	}

	survivors := []*Raft{}
	for _, r := range roles {
		if r != nil {
			survivors = append(survivors, r)
		}
	}
	var newLeader *Raft
	caPoll(func() bool {
		newLeader = caFindLeader(survivors...)
		return newLeader != nil
	}, 30*time.Second)

	result := map[string]interface{}{
		"event":               "stale_config_loss",
		"variant":             "stale-smaller-config",
		"write_acknowledged":  writeErr == nil,
		"write_index":         writeIndex,
		"write_holders_count": holderCount,
		"true_quorum":         len(caVoters(trueConf))/2 + 1,
		"config_in_force":     caVoters(trueConf),
		"new_leader_elected":  newLeader != nil,
	}
	if newLeader != nil {
		hasWrite, _ := caHoldsPayload(newLeader, payload)
		result["new_leader_id"] = string(newLeader.localID)
		result["new_leader_term"] = newLeader.getCurrentTerm()
		result["new_leader_has_write"] = hasWrite
		result["acknowledged_write_absent_from_new_leader"] = writeErr == nil && !hasWrite
		result["new_leader_last_applied"] = newLeader.getLastApplied()
	}
	caEmit(t, result)
}

// TestAssurance_ConfigurationFutureIndex probes the index reported by the
// public configuration future and by the documented stats key
// "latest_configuration_index" after a configuration entry is committed.
func TestAssurance_ConfigurationFutureIndex(t *testing.T) {
	c := MakeClusterCustom(t, &MakeClusterOpts{Peers: 2, Bootstrap: true, Conf: inmemConfig(t)})
	defer c.Close()

	var leader *Raft
	if !caPoll(func() bool {
		leader = caFindLeader(c.rafts...)
		return leader != nil
	}, 20*time.Second) {
		t.Fatalf("no leader")
	}

	for i := 0; i < 3; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("cmd-%d", i)), 5*time.Second).Error(); err != nil {
			t.Fatalf("apply: %v", err)
		}
	}

	change := leader.AddNonvoter(ServerID("nonvoter-x"), ServerAddress("addr-x"), 0, 0)
	if err := change.Error(); err != nil {
		t.Fatalf("AddNonvoter: %v", err)
	}
	entryIndex := change.Index()
	var entry Log
	if err := leader.logs.GetLog(entryIndex, &entry); err != nil {
		t.Fatalf("GetLog(%d): %v", entryIndex, err)
	}

	caEmit(t, map[string]interface{}{
		"event":                     "configuration_future_setup",
		"variant":                   "two-voter-cluster-plus-nonvoter",
		"configuration_entry_index": entryIndex,
		"log_entry_type":            entry.Type.String(),
		"cluster_peers":             len(c.rafts),
	})

	cf := leader.GetConfiguration()
	if err := cf.Error(); err != nil {
		t.Fatalf("GetConfiguration: %v", err)
	}
	futureIndex := cf.Index()
	live := cf.Configuration()
	statsIndex := leader.Stats()["latest_configuration_index"]

	caEmit(t, map[string]interface{}{
		"event":                            "configuration_future_index",
		"variant":                          "two-voter-cluster-plus-nonvoter",
		"configuration_entry_index":        entryIndex,
		"future_index":                     futureIndex,
		"future_index_matches_entry":       futureIndex == entryIndex,
		"stats_latest_configuration_index": statsIndex,
		"stats_index_matches_entry":        statsIndex == fmt.Sprint(entryIndex),
		"live_config_len":                  len(live.Servers),
		"live_config":                      caServers(live),
	})
}

// TestAssurance_EmptyConfigRepair probes whether a configuration entry committed
// after a RestoreCommittedLogs restart repairs the node's configuration, which
// bounds how long the empty/stale configuration can persist.
func TestAssurance_EmptyConfigRepair(t *testing.T) {
	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.SnapshotThreshold = 1 << 30
	conf.SnapshotInterval = time.Hour
	conf.RestoreCommittedLogs = true

	c := MakeClusterCustom(t, &MakeClusterOpts{Peers: 2, Bootstrap: true, Conf: conf, CommitTrackingLogs: true})
	defer func() {
		defer func() { _ = recover() }()
		c.Close()
	}()

	var leader *Raft
	if !caPoll(func() bool {
		leader = caFindLeader(c.rafts...)
		return leader != nil
	}, 20*time.Second) {
		t.Fatalf("no leader")
	}
	for i := 0; i < 5; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("cmd-%d", i)), 5*time.Second).Error(); err != nil {
			t.Fatalf("apply: %v", err)
		}
	}

	// Pick the follower to restart.
	idx := -1
	for i, r := range c.rafts {
		if r != leader {
			idx = i
		}
	}
	if idx < 0 {
		t.Fatalf("no follower")
	}
	old := c.rafts[idx]
	logConf := Configuration{}
	var entry Log
	if err := old.logs.GetLog(1, &entry); err == nil && entry.Type == LogConfiguration {
		logConf = DecodeConfiguration(entry.Data)
	}
	before := old.getLatestConfiguration()

	if err := old.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown follower: %v", err)
	}
	_, trans2 := NewInmemTransport(old.localAddr)
	cfg2 := old.config()
	restarted, err := NewRaft(&cfg2, old.fsm, old.logs, old.stable, old.snapshots, trans2)
	if err != nil {
		t.Fatalf("restart follower: %v", err)
	}
	c.rafts[idx] = restarted
	c.trans[idx] = trans2
	c.FullyConnect()

	afterRestart := restarted.getLatestConfiguration()
	caEmit(t, map[string]interface{}{
		"event":                     "empty_config_repair_setup",
		"variant":                   "two-voter-restart-no-snapshot",
		"config_before_restart":     caServers(before),
		"log_recorded_config":       caServers(logConf),
		"live_config_len_after_restart": len(afterRestart.Servers),
		"live_config_after_restart": caServers(afterRestart),
	})

	// The serving leader now commits a new configuration entry.
	change := leader.AddNonvoter(ServerID("repair-C"), ServerAddress("repair-C-addr"), 0, 0)
	if err := change.Error(); err != nil {
		t.Fatalf("AddNonvoter: %v", err)
	}
	changeIndex := change.Index()
	var newEntry Log
	if err := leader.logs.GetLog(changeIndex, &newEntry); err != nil {
		t.Fatalf("GetLog(%d): %v", changeIndex, err)
	}

	repaired := caPoll(func() bool {
		return len(restarted.getLatestConfiguration().Servers) > 0
	}, 15*time.Second)
	finalConf := restarted.getLatestConfiguration()

	caEmit(t, map[string]interface{}{
		"event":                        "empty_config_repair_result",
		"variant":                      "two-voter-restart-no-snapshot",
		"change_entry_index":           changeIndex,
		"change_entry_type":            newEntry.Type.String(),
		"config_repaired_by_later_entry": repaired,
		"live_config_len_after_change": len(finalConf.Servers),
		"live_config_after_change":     caServers(finalConf),
		"config_before_restart_len":    len(before.Servers),
	})
}

// TestAssurance_TimeoutNowFromRemovedNode probes whether a server that is no
// longer in the configuration can still force a leadership change through the
// TimeoutNow RPC.
func TestAssurance_TimeoutNowFromRemovedNode(t *testing.T) {
	c := MakeCluster(3, t, inmemConfig(t))
	defer func() {
		defer func() { _ = recover() }()
		c.Close()
	}()

	var leader *Raft
	if !caPoll(func() bool {
		leader = caFindLeader(c.rafts...)
		return leader != nil
	}, 20*time.Second) {
		t.Fatalf("no leader")
	}
	if err := leader.Apply([]byte("warm"), 5*time.Second).Error(); err != nil {
		t.Fatalf("apply: %v", err)
	}

	// Choose a node to remove and a follower to target.
	removedIdx := -1
	for i, r := range c.rafts {
		if r != leader {
			removedIdx = i
			break
		}
	}
	if removedIdx < 0 {
		t.Fatalf("no follower to remove")
	}
	removed := c.rafts[removedIdx]
	targetIdx := -1
	for i, r := range c.rafts {
		if r != leader && r != removed {
			targetIdx = i
		}
	}
	if targetIdx < 0 {
		t.Fatalf("no target follower")
	}
	target := c.rafts[targetIdx]

	if err := leader.RemoveServer(removed.localID, 0, 0).Error(); err != nil {
		t.Fatalf("RemoveServer: %v", err)
	}
	// Let the removed node receive the entry that drops it from the configuration.
	caPoll(func() bool { return !inConfiguration(removed.getLatestConfiguration(), removed.localID) }, 10*time.Second)

	setupConf := leader.GetConfiguration()
	_ = setupConf.Error()
	caEmit(t, map[string]interface{}{
		"event":                       "timeoutnow_removed_setup",
		"variant":                     "three-voter-one-removed",
		"config_in_force":             caServers(setupConf.Configuration()),
		"removed_node_id":             string(removed.localID),
		"removed_node_in_config":      inConfiguration(setupConf.Configuration(), removed.localID),
		"target_id":                   string(target.localID),
		"leader_id":                   string(leader.localID),
		"target_state_before":         target.State().String(),
		"target_term_before":          target.getCurrentTerm(),
	})

	_, removedTrans := c.trans[removedIdx].(interface {
		LocalAddr() ServerAddress
	}) != nil, c.trans[removedIdx]
	tnowResp := &TimeoutNowResponse{}
	tnowErr := removedTrans.TimeoutNow(target.localID, target.localAddr,
		&TimeoutNowRequest{RPCHeader: RPCHeader{
			ProtocolVersion: removed.protocolVersion,
			ID:              []byte(removed.localID),
			Addr:            removedTrans.EncodePeer(removed.localID, removed.localAddr),
		}}, tnowResp)

	caPoll(func() bool {
		return target.State() == Leader || caFindLeader(c.rafts...) != leader
	}, 10*time.Second)

	oldLeaderSteppedDown := leader.State() != Leader
	caPoll(func() bool { return caFindLeader(c.rafts...) != nil }, 8*time.Second)
	newLeader := caFindLeader(c.rafts...)
	result := map[string]interface{}{
		"event":                    "timeoutnow_removed_result",
		"variant":                  "three-voter-one-removed",
		"timeoutnow_error":         fmt.Sprint(tnowErr),
		"target_state_after":       target.State().String(),
		"target_term_after":        target.getCurrentTerm(),
		"old_leader_state_after":   leader.State().String(),
		"old_leader_stepped_down":  oldLeaderSteppedDown,
		"leader_after_disruption_present": newLeader != nil,
		"leadership_changed":       newLeader != nil && newLeader != leader,
		"target_became_leader":     newLeader == target,
	}
	if newLeader != nil {
		result["new_leader_id"] = string(newLeader.localID)
		result["new_leader_term"] = newLeader.getCurrentTerm()
	}
	caEmit(t, result)
}

// TestAssurance_EmptyConfigLeaderAdmission probes what else the empty
// configuration admits: whether the node campaigns on its own, and whether it
// accepts an outsider's AppendEntries and takes it as its leader.
func TestAssurance_EmptyConfigLeaderAdmission(t *testing.T) {
	opts := &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               caConf(t),
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)
	defer c.Close()

	leader := c.Leader()
	for i := 0; i < 5; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("cmd-%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply: %v", err)
		}
	}
	n := caRestart(t, leader)
	live := n.getLatestConfiguration()

	caEmit(t, map[string]interface{}{
		"event":                       "empty_config_leader_setup",
		"variant":                     "no-snapshot-restart",
		"live_config_len":             len(live.Servers),
		"node_in_own_config":          inConfiguration(live, n.localID),
		"derived_quorum_size":         0,
	})

	// Watch the node for a few heartbeat timeouts: with an empty configuration
	// its own follower loop is expected to refuse to campaign.
	time.Sleep(6 * n.config().HeartbeatTimeout)
	selfState := n.State()
	_, selfLeader := n.LeaderWithID()

	// Now let an outsider speak AppendEntries with a higher term.
	peerAddr, peerTrans := NewInmemTransport("")
	defer peerTrans.Close()
	own := n.trans.(*InmemTransport)
	own.Connect(peerAddr, peerTrans)
	peerTrans.Connect(n.localAddr, own)

	outsider := ServerID("outsider-leader")
	encoded := peerTrans.EncodePeer(outsider, peerAddr)
	aResp := &AppendEntriesResponse{}
	aErr := peerTrans.AppendEntries(outsider, n.localAddr, &AppendEntriesRequest{
		RPCHeader:         RPCHeader{ProtocolVersion: n.config().ProtocolVersion, ID: []byte(outsider), Addr: encoded},
		Term:              n.getCurrentTerm() + 1,
		Leader:            encoded,
		PrevLogEntry:      0,
		PrevLogTerm:       0,
		LeaderCommitIndex: 0,
	}, aResp)

	leaderAddr, leaderID := n.LeaderWithID()

	// Now let that outsider replicate an entry and see whether the node stores
	// and applies it while its own configuration is empty.
	beforeLast, _ := n.logs.LastIndex()
	beforeApplied := n.getLastApplied()
	entryData := []byte("outsider-entry")
	aResp2 := &AppendEntriesResponse{}
	aErr2 := peerTrans.AppendEntries(outsider, n.localAddr, &AppendEntriesRequest{
		RPCHeader:         RPCHeader{ProtocolVersion: n.config().ProtocolVersion, ID: []byte(outsider), Addr: encoded},
		Term:              n.getCurrentTerm(),
		Leader:            encoded,
		PrevLogEntry:      0,
		PrevLogTerm:       0,
		Entries:           []*Log{{Index: beforeLast + 1, Term: n.getCurrentTerm(), Type: LogCommand, Data: entryData}},
		LeaderCommitIndex: beforeLast + 1,
	}, aResp2)
	afterLast, _ := n.logs.LastIndex()
	caPoll(func() bool { return n.getLastApplied() > beforeApplied }, 5*time.Second)
	afterApplied := n.getLastApplied()
	stored := false
	for i := beforeLast + 1; i <= afterLast; i++ {
		var l Log
		if err := n.logs.GetLog(i, &l); err == nil && bytes.Equal(l.Data, entryData) {
			stored = true
		}
	}

	caEmit(t, map[string]interface{}{
		"event":                     "empty_config_outsider_entries",
		"variant":                   "no-snapshot-restart",
		"append_entries_error":      fmt.Sprint(aErr2),
		"append_entries_success":    aResp2.Success,
		"entry_stored":              stored,
		"last_log_index_before":     beforeLast,
		"last_log_index_after":      afterLast,
		"last_applied_before":       beforeApplied,
		"last_applied_after":        afterApplied,
		"entry_applied_from_outsider": stored && afterApplied >= beforeLast+1,
	})

	caEmit(t, map[string]interface{}{
		"event":                        "empty_config_leader_admission",
		"variant":                      "no-snapshot-restart",
		"live_config_len":              len(live.Servers),
		"node_state_after_wait":        selfState.String(),
		"node_campaigned_on_its_own":   selfState != Follower,
		"leader_before_append":         string(selfLeader),
		"append_entries_error":         fmt.Sprint(aErr),
		"append_entries_success":       aResp.Success,
		"append_entries_resp_term":     aResp.Term,
		"leader_after_append_id":       string(leaderID),
		"leader_after_append_addr":     string(leaderAddr),
		"outsider_became_leader":       leaderID == outsider,
		"node_in_own_config":           inConfiguration(live, n.localID),
	})
}

// TestAssurance_VerifyLeaderNonvoterAck probes whether the leader-verification
// quorum can be satisfied by a non-voter acknowledgement while the voter quorum
// is unreachable.
func TestAssurance_VerifyLeaderNonvoterAck(t *testing.T) {
	slowed := inmemConfig(t)
	slowed.HeartbeatTimeout = 1 * time.Second
	slowed.ElectionTimeout = 2 * time.Second
	slowed.LeaderLeaseTimeout = 1 * time.Second
	slowed.CommitTimeout = 50 * time.Millisecond
	caVerifyNonvoterCase(t, slowed, "slowed-timers")
	caVerifyNonvoterCase(t, inmemConfig(t), "default-timers")
}

func caVerifyNonvoterCase(t *testing.T, conf *Config, variant string) {
	t.Helper()
	c := MakeCluster(4, t, conf)
	defer c.Close()

	var leader *Raft
	if !caPoll(func() bool {
		leader = caFindLeader(c.rafts...)
		return leader != nil
	}, 20*time.Second) {
		t.Fatalf("no leader")
	}
	if err := leader.Apply([]byte("warm"), 5*time.Second).Error(); err != nil {
		t.Fatalf("apply: %v", err)
	}

	// Demote one follower so the configuration is three voters plus one nonvoter.
	li := c.IndexOf(leader)
	var nonvoterIdx int = -1
	for i := range c.rafts {
		if i != li {
			nonvoterIdx = i
			break
		}
	}
	if nonvoterIdx < 0 {
		t.Fatalf("no follower to demote")
	}
	nonvoter := c.rafts[nonvoterIdx]
	if err := leader.DemoteVoter(nonvoter.localID, 0, 0).Error(); err != nil {
		t.Fatalf("demote: %v", err)
	}
	confNow := leader.GetConfiguration()
	_ = confNow.Error()
	voters := caVoters(confNow.Configuration())
	quorum := len(voters)/2 + 1

	// Isolate the leader from the other two voters, keeping the nonvoter wired.
	for i, r := range c.rafts {
		if i == li || i == nonvoterIdx {
			continue
		}
		c.trans[li].Disconnect(r.localAddr)
		c.trans[i].Disconnect(leader.localAddr)
	}

	nonvoterReach := fmt.Sprint(c.trans[li].AppendEntries(nonvoter.localID, nonvoter.localAddr,
		&AppendEntriesRequest{RPCHeader: leader.getRPCHeader(), Term: leader.getCurrentTerm(),
			Leader: c.trans[li].EncodePeer(leader.localID, leader.localAddr)}, &AppendEntriesResponse{}))
	var voterReach string
	for i, r := range c.rafts {
		if i == li || i == nonvoterIdx {
			continue
		}
		voterReach = fmt.Sprint(c.trans[li].AppendEntries(r.localID, r.localAddr,
			&AppendEntriesRequest{RPCHeader: leader.getRPCHeader(), Term: leader.getCurrentTerm(),
				Leader: c.trans[li].EncodePeer(leader.localID, leader.localAddr)}, &AppendEntriesResponse{}))
		_ = r
		break
	}

	caEmit(t, map[string]interface{}{
		"event":             "verify_leader_nonvoter_setup",
		"variant":           variant,
		"voters":            voters,
		"voters_len":        len(voters),
		"voter_quorum":      quorum,
		"leader_id":         string(leader.localID),
		"nonvoter_id":       string(nonvoter.localID),
		"nonvoter_reachable": nonvoterReach,
		"voter_reachable":   voterReach,
	})

	type res struct{ err error }
	done := make(chan res, 1)
	start := time.Now()
	go func() { done <- res{err: leader.VerifyLeader().Error()} }()

	result := map[string]interface{}{
		"event":          "verify_leader_nonvoter_result",
		"variant":        variant,
		"voter_quorum":   quorum,
		"voters_len":     len(voters),
	}
	select {
	case r := <-done:
		result["verify_returned"] = true
		result["verify_error"] = fmt.Sprint(r.err)
		result["verify_succeeded"] = r.err == nil
		result["elapsed_ms"] = time.Since(start).Milliseconds()
	case <-time.After(5 * time.Second):
		result["verify_returned"] = false
		result["observed_after_ms"] = 5000
	}
	result["leader_state_after"] = leader.State().String()
	caEmit(t, result)

	// Bound the exposure: the leader lease counts voters only, so a leader that
	// cannot reach a voter quorum should step down shortly.
	waitStart := time.Now()
	caPoll(func() bool { return leader.State() != Leader }, 5*conf.LeaderLeaseTimeout+2*time.Second)
	caEmit(t, map[string]interface{}{
		"event":                "verify_leader_nonvoter_lease_bound",
		"variant":              variant,
		"lease_timeout_ms":     conf.LeaderLeaseTimeout.Milliseconds(),
		"leader_stepped_down":  leader.State() != Leader,
		"leader_state_after_wait": leader.State().String(),
		"waited_ms":            time.Since(waitStart).Milliseconds(),
	})
}

// TestAssurance_StaleConfigRejectsNewVoter probes whether a node restarted with
// the smaller configuration recorded in its snapshot rejects a vote request from
// a server that the configuration in force contains but that set does not.
func TestAssurance_StaleConfigRejectsNewVoter(t *testing.T) {
	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.SnapshotThreshold = 1 << 30
	conf.SnapshotInterval = time.Hour
	conf.RestoreCommittedLogs = true
	conf.ShutdownOnRemove = false

	c := MakeClusterCustom(t, &MakeClusterOpts{Peers: 5, Bootstrap: true, Conf: conf, CommitTrackingLogs: true})
	defer func() {
		defer func() { _ = recover() }()
		c.Close()
	}()

	roles := []*Raft{c.rafts[0], c.rafts[1], c.rafts[2], c.rafts[3], c.rafts[4]}
	ids := make([]ServerID, len(roles))
	for i, r := range roles {
		ids[i] = r.localID
	}
	ldr := func() *Raft {
		var l *Raft
		caPoll(func() bool {
			l = caFindLeader(roles...)
			return l != nil
		}, 20*time.Second)
		return l
	}

	// Shrink the configuration in force to {0,1,2}, snapshot node 2, then widen it
	// again and drive traffic so node 2's commit-tracking store stages a commit
	// index past the widening entries.
	caConfigChange(t, ldr, func(l *Raft) error { return l.RemoveServer(ids[3], 0, 0).Error() })
	caConfigChange(t, ldr, func(l *Raft) error { return l.RemoveServer(ids[4], 0, 0).Error() })
	// The FSM needs applied commands before it can snapshot at all.
	if l := ldr(); l != nil {
		for i := 0; i < 5; i++ {
			if err := l.Apply([]byte(fmt.Sprintf("pre-snapshot-%d", i)), 5*time.Second).Error(); err != nil {
				t.Fatalf("pre-snapshot apply: %v", err)
			}
		}
	}
	if ok := caPoll(func() bool { return roles[2].Snapshot().Error() == nil }, 20*time.Second); !ok {
		t.Fatalf("snapshot on node 2 failed")
	}
	caConfigChange(t, ldr, func(l *Raft) error { return l.AddVoter(ids[3], roles[3].localAddr, 0, 0).Error() })
	caConfigChange(t, ldr, func(l *Raft) error { return l.AddVoter(ids[4], roles[4].localAddr, 0, 0).Error() })
	if l := ldr(); l != nil {
		for i := 0; i < 20; i++ {
			if err := l.Apply([]byte(fmt.Sprintf("traffic-%d", i)), 5*time.Second).Error(); err != nil {
				t.Fatalf("traffic apply: %v", err)
			}
		}
	}

	old := roles[2]
	if err := old.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown node 2: %v", err)
	}
	_, trans2 := NewInmemTransport(old.localAddr)
	cfg2 := old.config()
	restarted, err := NewRaft(&cfg2, old.fsm, old.logs, old.stable, old.snapshots, trans2)
	if err != nil {
		t.Fatalf("restart node 2: %v", err)
	}
	roles[2] = restarted
	c.rafts[2] = restarted
	c.trans[2] = trans2
	c.FullyConnect()

	live := restarted.getLatestConfiguration()
	trueConf := ldr().GetConfiguration()
	_ = trueConf.Error()

	// A candidate that the configuration in force contains but the recovered set
	// does not: node 3, which was re-added after node 2's snapshot.
	send := func(fromIdx int, fromID ServerID) *RequestVoteResponse {
		peerAddr, peerTrans := NewInmemTransport("")
		defer peerTrans.Close()
		own := restarted.trans.(*InmemTransport)
		own.Connect(peerAddr, peerTrans)
		peerTrans.Connect(restarted.localAddr, own)
		encoded := peerTrans.EncodePeer(fromID, peerAddr)
		resp := &RequestVoteResponse{}
		_ = peerTrans.RequestVote(fromID, restarted.localAddr, &RequestVoteRequest{
			RPCHeader:          RPCHeader{ProtocolVersion: restarted.config().ProtocolVersion, ID: []byte(fromID), Addr: encoded},
			Term:               restarted.getCurrentTerm() + 1,
			Candidate:          encoded,
			LastLogIndex:       1 << 40,
			LastLogTerm:        restarted.getCurrentTerm() + 1,
			LeadershipTransfer: true,
		}, resp)
		return resp
	}

	caEmit(t, map[string]interface{}{
		"event":                      "stale_config_vote_setup",
		"variant":                    "stale-smaller-config",
		"live_config":                caVoters(live),
		"live_voters":                len(caVoters(live)),
		"config_in_force":            caVoters(trueConf.Configuration()),
		"config_in_force_voters":     len(caVoters(trueConf.Configuration())),
		"candidate_outside_stale":    string(ids[3]),
		"candidate_outside_in_force": inConfiguration(trueConf.Configuration(), ids[3]),
		"candidate_inside_stale":     string(ids[1]),
		"candidate_inside_in_force":  inConfiguration(trueConf.Configuration(), ids[1]),
	})

	outsideResp := send(3, ids[3])
	insideResp := send(1, ids[1])

	caEmit(t, map[string]interface{}{
		"event":                     "stale_config_vote_admission",
		"variant":                   "stale-smaller-config",
		"live_voters":               len(caVoters(live)),
		"config_in_force_voters":    len(caVoters(trueConf.Configuration())),
		"candidate_outside_stale":   string(ids[3]),
		"candidate_outside_in_force": inConfiguration(trueConf.Configuration(), ids[3]),
		"vote_granted_outside":      outsideResp.Granted,
		"candidate_inside_stale":    string(ids[1]),
		"candidate_inside_in_force": inConfiguration(trueConf.Configuration(), ids[1]),
		"vote_granted_inside":       insideResp.Granted,
		"stale_set_rejects_member":  outsideResp.Granted == false && insideResp.Granted == true,
	})
}

// TestAssurance_StaleConfigRepairBySnapshot probes the other repair path named in
// the parent configuration question: whether an installed snapshot restores the
// recovered configuration when the node is behind the leader's retained log.
func TestAssurance_StaleConfigRepairBySnapshot(t *testing.T) {
	conf := inmemConfig(t)
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 200 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond
	conf.CommitTimeout = 20 * time.Millisecond
	conf.TrailingLogs = 5
	conf.SnapshotThreshold = 20
	conf.SnapshotInterval = 50 * time.Millisecond
	conf.SnapshotThreshold = 20
	conf.RestoreCommittedLogs = true

	c := MakeClusterCustom(t, &MakeClusterOpts{Peers: 3, Bootstrap: true, Conf: conf, CommitTrackingLogs: true})
	defer func() {
		defer func() { _ = recover() }()
		c.Close()
	}()

	ldr := func() *Raft {
		var l *Raft
		caPoll(func() bool {
			l = caFindLeader(c.rafts...)
			return l != nil
		}, 20*time.Second)
		return l
	}
	if l := ldr(); l == nil {
		t.Fatalf("no leader")
	}

	// Give node 2 something to snapshot and a snapshot that predates the
	// configuration change that follows.
	if l := ldr(); l != nil {
		for i := 0; i < 10; i++ {
			if err := l.Apply([]byte(fmt.Sprintf("pre-%d", i)), 5*time.Second).Error(); err != nil {
				t.Fatalf("pre apply: %v", err)
			}
		}
	}
	node2 := c.rafts[2]
	if ok := caPoll(func() bool { return node2.Snapshot().Error() == nil }, 20*time.Second); !ok {
		t.Fatalf("snapshot on node 2 failed")
	}
	caConfigChange(t, ldr, func(l *Raft) error {
		return l.AddNonvoter(ServerID("late-joiner"), ServerAddress("late-joiner-addr"), 0, 0).Error()
	})
	if l := ldr(); l != nil {
		for i := 0; i < 5; i++ {
			if err := l.Apply([]byte(fmt.Sprintf("post-config-%d", i)), 5*time.Second).Error(); err != nil {
				t.Fatalf("post apply: %v", err)
			}
		}
	}

	beforeLogIdx, _ := node2.logs.LastIndex()
	if err := node2.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown node 2: %v", err)
	}

	// The cluster keeps going without node 2: more entries, repeated snapshots
	// and log compaction on the leader.
	if l := ldr(); l != nil {
		for i := 0; i < 80; i++ {
			if err := l.Apply([]byte(fmt.Sprintf("while-down-%d", i)), 5*time.Second).Error(); err != nil {
				t.Fatalf("while-down apply: %v", err)
			}
		}
	}

	_, trans2 := NewInmemTransport(node2.localAddr)
	cfg2 := node2.config()
	restarted, err := NewRaft(&cfg2, node2.fsm, node2.logs, node2.stable, node2.snapshots, trans2)
	if err != nil {
		t.Fatalf("restart node 2: %v", err)
	}
	c.rafts[2] = restarted
	c.trans[2] = trans2
	c.FullyConnect()

	staleConf := restarted.getLatestConfiguration()
	staleSnapIdx, _ := restarted.getLastSnapshot()
	leader := ldr()
	forceConf := leader.GetConfiguration()
	_ = forceConf.Error()
	leaderSnaps, _ := leader.snapshots.List()
	leaderSnapIdx := uint64(0)
	if len(leaderSnaps) > 0 {
		leaderSnapIdx = leaderSnaps[0].Index
	}

	caEmit(t, map[string]interface{}{
		"event":                     "stale_config_snapshot_repair_setup",
		"variant":                   "stale-config-behind-leader-log",
		"config_in_force":           caServers(forceConf.Configuration()),
		"config_in_force_has_late":  inConfiguration(forceConf.Configuration(), ServerID("late-joiner")),
		"recovered_config_has_late": inConfiguration(staleConf, ServerID("late-joiner")),
		"recovered_config_len":      len(staleConf.Servers),
		"node2_last_log_index_before_shutdown": beforeLogIdx,
		"node2_snapshot_index_after_restart":   staleSnapIdx,
		"leader_latest_snapshot_index":         leaderSnapIdx,
	})

	// Wait for the node's configuration to reach the configuration in force.
	repaired := caPoll(func() bool {
		return inConfiguration(restarted.getLatestConfiguration(), ServerID("late-joiner"))
	}, 20*time.Second)
	afterConf := restarted.getLatestConfiguration()
	afterSnapIdx, _ := restarted.getLastSnapshot()
	afterLogIdx, _ := restarted.logs.LastIndex()

	caEmit(t, map[string]interface{}{
		"event":                        "stale_config_snapshot_repair_result",
		"variant":                      "stale-config-behind-leader-log",
		"config_repaired":              repaired,
		"config_after":                 caServers(afterConf),
		"config_after_has_late":        inConfiguration(afterConf, ServerID("late-joiner")),
		"snapshot_index_after_repair":  afterSnapIdx,
		"snapshot_index_changed":       afterSnapIdx != staleSnapIdx,
		"last_log_index_after_repair":  afterLogIdx,
	})
}
