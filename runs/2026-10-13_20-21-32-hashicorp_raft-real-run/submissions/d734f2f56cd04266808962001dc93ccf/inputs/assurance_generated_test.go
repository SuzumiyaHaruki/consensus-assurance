package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

// restartAfterRecovery boots a single-node cluster, commits entries that
// include the bootstrap configuration entry, then restarts the node from the
// same on-disk state and reports the configuration the node holds in memory
// after NewRaft returns.
//
// No snapshot is ever taken, so restoreSnapshot cannot supply a configuration;
// the log is the only source of the configuration (LogStore is also the
// CommitTrackingLogStore whose persisted commit index drives
// restoreFromCommittedLogs).
func restartAfterRecovery(t *testing.T, restoreCommittedLogs bool) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = restoreCommittedLogs
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 1 << 40

	opts := &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)
	leader := c.Leader()

	for i := 0; i < 10; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("test%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}

	beforeLatestIndex := leader.configurations.latestIndex
	beforeCommittedIndex := leader.configurations.committedIndex
	beforeServers := len(leader.configurations.latest.Servers)
	snaps, err := leader.snapshots.List()
	if err != nil {
		t.Fatalf("list snapshots: %v", err)
	}

	mode := map[bool]string{true: "on", false: "off"}[restoreCommittedLogs]
	setup := map[string]interface{}{
		"event":                  "startup_before_restart",
		"mode":                   mode,
		"phase":                  "before_restart",
		"restore_committed_logs": restoreCommittedLogs,
		"snapshots":              len(snaps),
		"before_latest_index":    beforeLatestIndex,
		"before_committed_index": beforeCommittedIndex,
		"before_servers":         beforeServers,
		"peers":                  opts.Peers,
		"applied_entries":        10,
	}
	setupBytes, err := json.Marshal(setup)
	if err != nil {
		t.Fatalf("marshal setup: %v", err)
	}
	fmt.Println("CA_EVENT " + string(setupBytes))

	// Restart from the same logs/stable/snapshots stores.
	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown err: %v", err)
	}
	_, trans2 := NewInmemTransport(leader.trans.LocalAddr())
	cfg := leader.config()
	restarted, err := NewRaft(&cfg, leader.fsm, leader.logs, leader.stable, leader.snapshots, trans2)
	if err != nil {
		t.Fatalf("NewRaft err: %v", err)
	}
	c.rafts[0] = restarted
	defer c.Close()

	after := restarted.getLatestConfiguration()

	event := map[string]interface{}{
		"event":                  "restart_after_recovery",
		"phase":                  "after_restart",
		"mode":                   mode,
		"restore_committed_logs": restoreCommittedLogs,
		"snapshots":              len(snaps),
		"before_latest_index":    beforeLatestIndex,
		"before_committed_index": beforeCommittedIndex,
		"before_servers":         beforeServers,
		"after_latest_index":     restarted.configurations.latestIndex,
		"after_committed_index":  restarted.configurations.committedIndex,
		"after_servers":          len(after.Servers),
		"after_has_vote":         hasVote(after, restarted.localID),
		"after_quorum_size":      restarted.quorumSize(),
		"after_commit_index":     restarted.getCommitIndex(),
		"after_last_applied":     restarted.getLastApplied(),
		"after_last_log_index":   restarted.getLastIndex(),
	}
	b, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func TestAssuranceRestartConfigurationRecovery(t *testing.T) {
	restartAfterRecovery(t, true)
	restartAfterRecovery(t, false)
}

// restartAfterConfigChangeCommittedAfterSnapshot covers the registered gap: a
// committed LogConfiguration entry that is newer than the on-disk snapshot.
// A nonvoter is added so the change commits with a one-voter quorum, then the
// node is restarted from the same stores and the configuration it holds after
// NewRaft returns is compared with the configuration the log says is latest.
func restartAfterConfigChangeCommittedAfterSnapshot(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.SnapshotThreshold = 5
	conf.SnapshotInterval = 50 * time.Millisecond
	conf.TrailingLogs = 1 << 40

	opts := &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)
	leader := c.Leader()

	// Drive enough traffic for a snapshot to exist before the config change.
	deadline := time.Now().Add(20 * time.Second)
	var snaps []*SnapshotMeta
	for i := 0; time.Now().Before(deadline); i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("pre%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
		var err error
		snaps, err = leader.snapshots.List()
		if err != nil {
			t.Fatalf("list snapshots: %v", err)
		}
		if len(snaps) > 0 {
			break
		}
	}
	if len(snaps) == 0 {
		t.Fatal("no snapshot was taken before the configuration change")
	}

	// Commit a configuration change that is newer than the snapshot.
	cfgFuture := leader.AddNonvoter(ServerID("nonvoter-b"), ServerAddress("nonvoter-b"), 0, 5*time.Second)
	if err := cfgFuture.Error(); err != nil {
		t.Fatalf("AddNonvoter err: %v", err)
	}

	// Commit further entries so the persisted (staged) commit index advances
	// past the configuration entry's index; otherwise the entry would still sit
	// above the restored commit index and be re-scanned.
	for i := 0; i < 10; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("post%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}
	// Give the replication/commit path a moment to stage the newer index.
	time.Sleep(50 * time.Millisecond)

	expectedIndex := cfgFuture.Index()
	expectedServers := len(leader.configurations.latest.Servers)
	beforeLatestIndex := leader.configurations.latestIndex
	snapshotIndex := snaps[0].Index
	snapshotConfigIndex := snaps[0].ConfigurationIndex

	mode := "snapshot"
	setup := map[string]interface{}{
		"event":                  "startup_before_restart",
		"mode":                   mode,
		"phase":                  "before_restart",
		"restore_committed_logs": true,
		"snapshots":              len(snaps),
		"snapshot_index":         snapshotIndex,
		"snapshot_config_index":  snapshotConfigIndex,
		"expected_latest_index":  expectedIndex,
		"expected_servers":       expectedServers,
		"before_latest_index":    beforeLatestIndex,
	}
	setupBytes, err := json.Marshal(setup)
	if err != nil {
		t.Fatalf("marshal setup: %v", err)
	}
	fmt.Println("CA_EVENT " + string(setupBytes))

	// Restart from the same stores.
	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown err: %v", err)
	}
	_, trans2 := NewInmemTransport(leader.trans.LocalAddr())
	cfg := leader.config()
	restarted, err := NewRaft(&cfg, leader.fsm, leader.logs, leader.stable, leader.snapshots, trans2)
	if err != nil {
		t.Fatalf("NewRaft err: %v", err)
	}
	c.rafts[0] = restarted
	defer c.Close()

	after := restarted.getLatestConfiguration()
	matches := restarted.configurations.latestIndex == expectedIndex &&
		len(after.Servers) == expectedServers

	event := map[string]interface{}{
		"event":                  "restart_after_config_change",
		"mode":                   mode,
		"phase":                  "after_restart",
		"restore_committed_logs": true,
		"snapshots":              len(snaps),
		"snapshot_index":         snapshotIndex,
		"snapshot_config_index":  snapshotConfigIndex,
		"expected_latest_index":  expectedIndex,
		"expected_servers":       expectedServers,
		"before_latest_index":    beforeLatestIndex,
		"after_latest_index":     restarted.configurations.latestIndex,
		"after_servers":          len(after.Servers),
		"after_has_vote":         hasVote(after, restarted.localID),
		"after_commit_index":     restarted.getCommitIndex(),
		"after_last_applied":     restarted.getLastApplied(),
		"matches_committed_log":  matches,
	}
	eventBytes, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(eventBytes))
}

func TestAssuranceRestartConfigurationAfterSnapshot(t *testing.T) {
	restartAfterConfigChangeCommittedAfterSnapshot(t)
}

// restartWithBacklog boots a single node with RestoreCommittedLogs on, commits
// n entries without ever snapshotting, then restarts it and reports whether
// NewRaft returned within a bounded wait. The two sizes bracket the number of
// batches that processLogs pushes into the FSM queue before the FSM goroutine
// exists.
func restartWithBacklog(t *testing.T, n int, mode string) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 1 << 40

	opts := &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)
	leader := c.Leader()

	for i := 0; i < n; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("e%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}

	beforeCommit := leader.getCommitIndex()
	beforeLastLog, _ := leader.logs.LastIndex()
	snaps, err := leader.snapshots.List()
	if err != nil {
		t.Fatalf("list snapshots: %v", err)
	}

	setup := map[string]interface{}{
		"event":                  "startup_before_restart",
		"mode":                   mode,
		"phase":                  "before_restart",
		"restore_committed_logs": true,
		"snapshots":              len(snaps),
		"applied_entries":        n,
		"before_commit_index":    beforeCommit,
		"before_last_log_index":  beforeLastLog,
	}
	setupBytes, err := json.Marshal(setup)
	if err != nil {
		t.Fatalf("marshal setup: %v", err)
	}
	fmt.Println("CA_EVENT " + string(setupBytes))

	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown err: %v", err)
	}
	_, trans2 := NewInmemTransport(leader.trans.LocalAddr())
	cfg := leader.config()

	returned := false
	restartStart := time.Now()
	done := make(chan struct{})
	go func() {
		_, err := NewRaft(&cfg, leader.fsm, leader.logs, leader.stable, leader.snapshots, trans2)
		if err == nil {
			returned = true
		}
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(15 * time.Second):
	}
	restartMs := time.Since(restartStart).Milliseconds()

	resultEvent := "restart_backlog_below"
	if mode == "above_buffer" {
		resultEvent = "restart_backlog_above"
	}
	event := map[string]interface{}{
		"event":                  resultEvent,
		"mode":                   mode,
		"phase":                  "after_restart",
		"restore_committed_logs": true,
		"snapshots":              len(snaps),
		"applied_entries":        n,
		"before_commit_index":    beforeCommit,
		"before_last_log_index":  beforeLastLog,
		"newraft_returned":       returned,
		"restart_wait_ms":        restartMs,
	}
	eventBytes, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(eventBytes))

	for _, r := range c.rafts {
		_ = r.Shutdown()
	}
}

func TestAssuranceRestartWithBacklog(t *testing.T) {
	restartWithBacklog(t, 8000, "below_buffer")
	restartWithBacklog(t, 8400, "above_buffer")
}
