// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
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
