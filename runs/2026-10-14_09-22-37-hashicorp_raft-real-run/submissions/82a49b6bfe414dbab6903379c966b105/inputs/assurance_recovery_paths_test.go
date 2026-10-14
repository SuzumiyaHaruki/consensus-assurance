package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

// Self-contained harness: only this file is copied into the captured package.

func recEvent(t *testing.T, kind string, fields map[string]interface{}) {
	fields["event"] = kind
	b, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func recServers(r *Raft) int {
	f := r.GetConfiguration()
	if err := f.Error(); err != nil {
		return -1
	}
	return len(f.Configuration().Servers)
}

func recLeader(r *Raft, d time.Duration) bool {
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		if r.State() == Leader {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	return r.State() == Leader
}

// TestAssurance_OperatorRecoveryAfterLostConfiguration asks what an operator can
// do in the state this investigation identified: a node whose configuration is
// empty after a restart with RestoreCommittedLogs. It tries the two documented
// operator entry points - live bootstrap on the running node and RecoverCluster
// on the stopped one - and records what each achieves.
func TestAssurance_OperatorRecoveryAfterLostConfiguration(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 10

	addr, trans := NewInmemTransport(ServerAddress("A"))
	conf.LocalID = ServerID(addr)
	logs := NewInmemCommitTrackingStore()
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	cfg := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: ServerID(addr), Address: addr},
	}}
	if err := BootstrapCluster(conf, logs, stable, snaps, trans, cfg); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	r, err := NewRaft(conf, new(MockFSM), logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("first NewRaft: %v", err)
	}
	if !recLeader(r, 5*time.Second) {
		t.Fatalf("node did not become leader")
	}
	for i := 0; i < 5; i++ {
		if err := r.Apply([]byte(fmt.Sprintf("cmd%d", i)), 2*time.Second).Error(); err != nil {
			t.Fatalf("apply %d: %v", i, err)
		}
	}
	staged, err := logs.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex: %v", err)
	}
	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}

	// Restart with the flag: this is the state under investigation.
	_, trans2 := NewInmemTransport(addr)
	r2, err := NewRaft(conf, new(MockFSM), logs, stable, snaps, trans2)
	if err != nil {
		t.Fatalf("restart NewRaft: %v", err)
	}
	recEvent(t, "lost_configuration", map[string]interface{}{
		"probe":            "operator_recovery_after_lost_configuration",
		"servers":          recServers(r2),
		"staged_commit":    staged,
		"log_last_index":   r2.LastIndex(),
		"leader_within_2s": recLeader(r2, 2*time.Second),
	})

	// Entry point 1: live bootstrap on the running node.
	bootErr := r2.BootstrapCluster(cfg).Error()
	recEvent(t, "live_bootstrap_attempt", map[string]interface{}{
		"probe":   "operator_recovery_after_lost_configuration",
		"err":     fmt.Sprintf("%v", bootErr),
		"servers": recServers(r2),
	})

	if err := r2.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown after bootstrap attempt: %v", err)
	}

	// Entry point 2: RecoverCluster on the stopped node with the same stores.
	recoverErr := RecoverCluster(conf, new(MockFSM), logs, stable, snaps, trans2, cfg)
	_, trans3 := NewInmemTransport(addr)
	r3, err := NewRaft(conf, new(MockFSM), logs, stable, snaps, trans3)
	recovered := 0
	leaderAfterRecover := false
	if err == nil {
		recovered = recServers(r3)
		leaderAfterRecover = recLeader(r3, 3*time.Second)
	}
	recEvent(t, "recover_cluster_attempt", map[string]interface{}{
		"probe":            "operator_recovery_after_lost_configuration",
		"err":              fmt.Sprintf("%v", recoverErr),
		"newraft_err":      fmt.Sprintf("%v", err),
		"servers":          recovered,
		"leader_within_3s": leaderAfterRecover,
	})
	if r3 != nil {
		_ = r3.Shutdown().Error()
	}
}
