// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
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
