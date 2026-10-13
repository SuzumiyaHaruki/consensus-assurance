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
