package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func controlEvent(t *testing.T, kind string, fields map[string]interface{}) {
	fields["event"] = kind
	b, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func controlWaitLeader(r *Raft, d time.Duration) bool {
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		if r.State() == Leader {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	return r.State() == Leader
}

// TestAssurance_ControlRestartWithoutCommittedReplay is the isolated control for
// the committed-log-replay finding: the same bootstrap, commits, restart and
// missing snapshot, but with RestoreCommittedLogs left at its default false, so
// the configuration scan is not bounded by a replayed commit index.
func TestAssurance_ControlRestartWithoutCommittedReplay(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = false
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 10

	addr, trans := NewInmemTransport(ServerAddress("A"))
	conf.LocalID = ServerID(addr)
	logs := NewInmemCommitTrackingStore()
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()

	if err := BootstrapCluster(conf, logs, stable, snaps, trans, Configuration{Servers: []Server{
		{Suffrage: Voter, ID: ServerID(addr), Address: addr},
	}}); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}

	r, err := NewRaft(conf, new(MockFSM), logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("first NewRaft: %v", err)
	}
	if !controlWaitLeader(r, 5*time.Second) {
		t.Fatalf("node did not become leader")
	}
	for i := 0; i < 5; i++ {
		if err := r.Apply([]byte(fmt.Sprintf("cmd%d", i)), 2*time.Second).Error(); err != nil {
			t.Fatalf("apply %d: %v", i, err)
		}
	}

	f := r.GetConfiguration()
	if err := f.Error(); err != nil {
		t.Fatalf("GetConfiguration before restart: %v", err)
	}
	before := len(f.Configuration().Servers)
	snapList, err := snaps.List()
	if err != nil {
		t.Fatalf("list snapshots: %v", err)
	}
	staged, err := logs.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex: %v", err)
	}

	controlEvent(t, "control_start", map[string]interface{}{
		"restore_committed": false,
		"servers_before":    before,
		"snapshot_count":    len(snapList),
		"staged_commit_idx": staged,
	})

	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}

	_, trans2 := NewInmemTransport(addr)
	r2, err := NewRaft(conf, new(MockFSM), logs, stable, snaps, trans2)
	if err != nil {
		t.Fatalf("second NewRaft: %v", err)
	}
	f2 := r2.GetConfiguration()
	if err := f2.Error(); err != nil {
		t.Fatalf("GetConfiguration after restart: %v", err)
	}
	controlEvent(t, "control_restart", map[string]interface{}{
		"restore_committed": false,
		"servers_after":     len(f2.Configuration().Servers),
		"became_leader":     controlWaitLeader(r2, 3*time.Second),
		"snapshot_count":    len(snapList),
		"staged_commit":     staged,
	})
	_ = r2.Shutdown().Error()
}
