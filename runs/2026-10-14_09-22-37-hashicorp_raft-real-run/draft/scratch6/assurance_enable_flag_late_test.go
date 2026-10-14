package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

// Self-contained harness: only this file is copied into the captured package.

func lateEvent(t *testing.T, kind string, fields map[string]interface{}) {
	fields["event"] = kind
	b, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func lateServers(r *Raft) int {
	f := r.GetConfiguration()
	if err := f.Error(); err != nil {
		return -1
	}
	return len(f.Configuration().Servers)
}

func lateLeader(r *Raft, d time.Duration) bool {
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		if r.State() == Leader {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	return r.State() == Leader
}

// TestAssurance_EnablingFlagLateIsALatentTrap asks whether RestoreCommittedLogs
// is the trigger by itself, or whether the trigger is the commit index the store
// has staged. A cluster that ran with the flag disabled never stages one, so the
// first restart with the flag enabled should be harmless while the next one,
// after the flag has been on for a while, should lose the configuration.
func TestAssurance_EnablingFlagLateIsALatentTrap(t *testing.T) {
	base := inmemConfig(t)
	base.RestoreCommittedLogs = false
	base.SnapshotThreshold = 1 << 40
	base.SnapshotInterval = 10 * time.Minute
	base.TrailingLogs = 10

	addr, trans := NewInmemTransport(ServerAddress("A"))
	base.LocalID = ServerID(addr)
	logs := NewInmemCommitTrackingStore()
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	cfg := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: ServerID(addr), Address: addr},
	}}
	if err := BootstrapCluster(base, logs, stable, snaps, trans, cfg); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	r, err := NewRaft(base, new(MockFSM), logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("NewRaft (flag off): %v", err)
	}
	if !lateLeader(r, 5*time.Second) {
		t.Fatalf("node did not become leader")
	}
	for i := 0; i < 5; i++ {
		if err := r.Apply([]byte(fmt.Sprintf("cmd%d", i)), 2*time.Second).Error(); err != nil {
			t.Fatalf("apply %d: %v", i, err)
		}
	}
	stagedWhileOff, err := logs.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex while flag off: %v", err)
	}
	lateEvent(t, "run_with_flag_off", map[string]interface{}{
		"probe":                "enable_flag_late",
		"staged_commit":        stagedWhileOff,
		"staged_below_config":  stagedWhileOff < 1,
		"servers":              lateServers(r),
	})
	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}

	// First restart, now with the flag enabled and nothing staged yet.
	onConf := *base
	onConf.RestoreCommittedLogs = true
	_, trans2 := NewInmemTransport(addr)
	r2, err := NewRaft(&onConf, new(MockFSM), logs, stable, snaps, trans2)
	if err != nil {
		t.Fatalf("first restart with flag on: %v", err)
	}
	lateEvent(t, "first_restart_flag_on", map[string]interface{}{
		"probe":            "enable_flag_late",
		"staged_commit":    stagedWhileOff,
		"servers":          lateServers(r2),
		"leader_within_2s": lateLeader(r2, 2*time.Second),
	})

	// Let the flag-on node write, which is what stages a commit index.
	for i := 0; i < 2; i++ {
		if err := r2.Apply([]byte(fmt.Sprintf("later%d", i)), 2*time.Second).Error(); err != nil {
			t.Fatalf("apply later %d: %v", i, err)
		}
	}
	stagedWhileOn, err := logs.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex while flag on: %v", err)
	}
	lateEvent(t, "after_commands_flag_on", map[string]interface{}{
		"probe":                 "enable_flag_late",
		"staged_commit":         stagedWhileOn,
		"staged_at_or_above_one": stagedWhileOn >= 1,
		"servers":               lateServers(r2),
	})
	if err := r2.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown after commands: %v", err)
	}

	// Second restart with the flag still enabled: this is where the trap fires.
	_, trans3 := NewInmemTransport(addr)
	r3, err := NewRaft(&onConf, new(MockFSM), logs, stable, snaps, trans3)
	if err != nil {
		t.Fatalf("second restart with flag on: %v", err)
	}
	lateEvent(t, "second_restart_flag_on", map[string]interface{}{
		"probe":            "enable_flag_late",
		"staged_commit":    stagedWhileOn,
		"servers":          lateServers(r3),
		"leader_within_2s": lateLeader(r3, 2*time.Second),
	})
	_ = r3.Shutdown().Error()
}
