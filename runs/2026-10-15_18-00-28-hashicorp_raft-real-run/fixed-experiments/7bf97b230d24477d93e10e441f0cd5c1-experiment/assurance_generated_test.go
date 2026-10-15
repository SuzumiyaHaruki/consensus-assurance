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
	if l := ldr(); l == nil {
		t.Fatalf("no leader for bootstrap step")
	} else if err := l.RemoveServer(ids[3], 0, 0).Error(); err != nil {
		t.Fatalf("remove 3: %v", err)
	}
	if l := ldr(); l == nil {
		t.Fatalf("no leader after first removal")
	} else if err := l.RemoveServer(ids[4], 0, 0).Error(); err != nil {
		t.Fatalf("remove 4: %v", err)
	}
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
	if l := ldr(); l == nil {
		t.Fatalf("no leader after snapshot")
	} else {
		if err := l.AddVoter(ids[3], roles[3].localAddr, 0, 0).Error(); err != nil {
			t.Fatalf("re-add 3: %v", err)
		}
		if err := l.AddVoter(ids[4], roles[4].localAddr, 0, 0).Error(); err != nil {
			t.Fatalf("re-add 4: %v", err)
		}
	}
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
