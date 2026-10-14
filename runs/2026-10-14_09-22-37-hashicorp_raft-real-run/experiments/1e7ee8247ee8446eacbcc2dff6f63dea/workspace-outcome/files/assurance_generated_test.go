package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

// caEvent prints one observation as a single JSON line for controller parsing.
func caEvent(t *testing.T, kind string, fields map[string]interface{}) {
	fields["event"] = kind
	b, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func waitLeaderState(r *Raft, d time.Duration) bool {
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		if r.State() == Leader {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	return r.State() == Leader
}

// TestAssurance_RestartConfigFromCommittedLogs restarts a single-voter node
// whose configuration entry lives in the log (never snapshotted) and observes
// whether the node still knows the bootstrapped configuration, with
// RestoreCommittedLogs on and off, and with a covering snapshot as a control.
func TestAssurance_RestartConfigFromCommittedLogs(t *testing.T) {
	cases := []struct {
		mode         string
		restore      bool
		takeSnapshot bool
	}{
		{mode: "restore_on_no_snapshot", restore: true, takeSnapshot: false},
		{mode: "restore_off_no_snapshot", restore: false, takeSnapshot: false},
		{mode: "restore_on_with_snapshot", restore: true, takeSnapshot: true},
	}

	for _, tc := range cases {
		runRestartCase(t, tc.mode, tc.restore, tc.takeSnapshot)
	}
}

func runRestartCase(t *testing.T, mode string, restore, takeSnapshot bool) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = restore
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 10

	addr, trans := NewInmemTransport(ServerAddress("A"))
	conf.LocalID = ServerID(addr)
	logs := NewInmemCommitTrackingStore()
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()

	configuration := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: ServerID(addr), Address: addr},
	}}
	if err := BootstrapCluster(conf, logs, stable, snaps, trans, configuration); err != nil {
		t.Fatalf("[%s] bootstrap: %v", mode, err)
	}

	r, err := NewRaft(conf, new(MockFSM), logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("[%s] first NewRaft: %v", mode, err)
	}
	firstLeader := waitLeaderState(r, 5*time.Second)

	for i := 0; i < 5; i++ {
		if err := r.Apply([]byte(fmt.Sprintf("cmd%d", i)), 2*time.Second).Error(); err != nil {
			t.Fatalf("[%s] apply %d: %v", mode, i, err)
		}
	}

	if takeSnapshot {
		if err := r.Snapshot().Error(); err != nil {
			t.Fatalf("[%s] snapshot: %v", mode, err)
		}
	}

	before := r.GetConfiguration()
	if err := before.Error(); err != nil {
		t.Fatalf("[%s] GetConfiguration before restart: %v", mode, err)
	}
	snapList, err := snaps.List()
	if err != nil {
		t.Fatalf("[%s] list snapshots: %v", mode, err)
	}
	stagedCommit, err := logs.GetCommitIndex()
	if err != nil {
		t.Fatalf("[%s] GetCommitIndex: %v", mode, err)
	}
	lastIdx, err := logs.LastIndex()
	if err != nil {
		t.Fatalf("[%s] LastIndex: %v", mode, err)
	}

	caEvent(t, "pre_restart", map[string]interface{}{
		"mode":              mode,
		"restore_committed": restore,
		"took_snapshot":     takeSnapshot,
		"became_leader":     firstLeader,
		"servers_before":    len(before.Configuration().Servers),
		"snapshot_count":    len(snapList),
		"staged_commit_idx": stagedCommit,
		"log_last_index":    lastIdx,
		"last_applied":      r.AppliedIndex(),
		"commit_index":      r.CommitIndex(),
	})

	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("[%s] shutdown: %v", mode, err)
	}

	// Restart on the same durable stores with a fresh transport.
	_, trans2 := NewInmemTransport(addr)
	r2, err := NewRaft(conf, new(MockFSM), logs, stable, snaps, trans2)
	if err != nil {
		t.Fatalf("[%s] second NewRaft: %v", mode, err)
	}
	after := r2.GetConfiguration()
	if err := after.Error(); err != nil {
		t.Fatalf("[%s] GetConfiguration after restart: %v", mode, err)
	}
	// Give the node a fair opportunity to campaign again.
	leaderAgain := waitLeaderState(r2, 3*time.Second)

	caEvent(t, "post_restart", map[string]interface{}{
		"mode":           mode,
		"servers_after":  len(after.Configuration().Servers),
		"config_preserved": len(after.Configuration().Servers) == len(before.Configuration().Servers),
		"became_leader":  leaderAgain,
		"last_applied":   r2.AppliedIndex(),
		"commit_index":   r2.CommitIndex(),
		"snapshot_count": len(snapList),
		"log_last_index": lastIdx,
		"staged_commit":  stagedCommit,
	})

	_ = r2.Shutdown().Error()
}
