package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func partialEvent(t *testing.T, kind string, fields map[string]interface{}) {
	fields["event"] = kind
	b, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssurance_PartialRestartLosesLiveQuorum restarts two of three voters
// (with RestoreCommittedLogs enabled, and disabled as a control), lets the one
// uninterrupted voter lead the cluster, then stops that voter while the two
// restarted voters - a live quorum with every committed entry on disk - remain
// running, and observes whether a leader can be elected.
func TestAssurance_PartialRestartLosesLiveQuorum(t *testing.T) {
	for _, mode := range []string{"restore_on", "restore_off"} {
		runPartialRestartCase(t, mode, mode == "restore_on")
	}
}

func runPartialRestartCase(t *testing.T, mode string, restore bool) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = restore
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 10

	addrs := []ServerAddress{"A", "B", "C"}
	trans := make([]*InmemTransport, 3)
	confs := make([]*Config, 3)
	logs := make([]*InmemCommitTrackingStore, 3)
	stables := make([]*InmemStore, 3)
	snaps := make([]*InmemSnapshotStore, 3)
	for i, a := range addrs {
		_, trans[i] = NewInmemTransport(a)
		c := *conf
		c.LocalID = ServerID(a)
		confs[i] = &c
		logs[i] = NewInmemCommitTrackingStore()
		stables[i] = NewInmemStore()
		snaps[i] = NewInmemSnapshotStore()
	}
	for i := 0; i < 3; i++ {
		for j := 0; j < 3; j++ {
			if i != j {
				trans[i].Connect(addrs[j], trans[j])
			}
		}
	}

	cfg := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "A", Address: "A"},
		{Suffrage: Voter, ID: "B", Address: "B"},
		{Suffrage: Voter, ID: "C", Address: "C"},
	}}
	if err := BootstrapCluster(confs[0], logs[0], stables[0], snaps[0], trans[0], cfg); err != nil {
		t.Fatalf("[%s] bootstrap: %v", mode, err)
	}

	rafts := make([]*Raft, 3)
	for i := 0; i < 3; i++ {
		r, err := NewRaft(confs[i], new(MockFSM), logs[i], stables[i], snaps[i], trans[i])
		if err != nil {
			t.Fatalf("[%s] NewRaft %d: %v", mode, i, err)
		}
		rafts[i] = r
	}
	firstLeader := waitLeaderAmong(rafts, 10*time.Second)
	if firstLeader < 0 {
		t.Fatalf("[%s] no initial leader", mode)
	}
	if !waitAllConfigured(rafts, 3, 5*time.Second) {
		t.Fatalf("[%s] nodes did not converge: %v", mode, configSizes(rafts))
	}
	for i := 0; i < 10; i++ {
		if err := rafts[firstLeader].Apply([]byte(fmt.Sprintf("cmd%d", i)), 2*time.Second).Error(); err != nil {
			t.Fatalf("[%s] apply %d: %v", mode, i, err)
		}
	}

	// Restart two voters; C keeps running.
	for i := 0; i < 2; i++ {
		if err := rafts[i].Shutdown().Error(); err != nil {
			t.Fatalf("[%s] shutdown %d: %v", mode, i, err)
		}
	}
	// Fresh transports for the two restarted voters, wired to each other and to
	// the still-running voter's live transport (both directions).
	trans2 := make([]*InmemTransport, 2)
	for i := 0; i < 2; i++ {
		_, trans2[i] = NewInmemTransport(addrs[i])
	}
	trans2[0].Connect(addrs[1], trans2[1])
	trans2[1].Connect(addrs[0], trans2[0])
	for i := 0; i < 2; i++ {
		trans2[i].Connect(addrs[2], trans[2])
		trans[2].Connect(addrs[i], trans2[i])
	}
	for i := 0; i < 2; i++ {
		r, err := NewRaft(confs[i], new(MockFSM), logs[i], stables[i], snaps[i], trans2[i])
		if err != nil {
			t.Fatalf("[%s] restart %d: %v", mode, i, err)
		}
		rafts[i] = r
	}

	// C still holds the configuration, so it should be able to lead with votes
	// from the two restarted (configuration-less) voters.
	leaderAfterPartial := waitLeaderAmong(rafts, 8*time.Second)
	partialEvent(t, "partial_restart_"+mode, map[string]interface{}{
		"mode":               mode,
		"leader_index":       leaderAfterPartial,
		"any_leader":         leaderAfterPartial >= 0,
		"servers_after":      configSizes(rafts),
		"nodes_with_full":    fullConfigCount(rafts, 3),
		"restarted":          []int{0, 1},
	})

	// Now stop the only configured voter. A and B are live, have every committed
	// entry, and are two of three voters.
	if err := rafts[2].Shutdown().Error(); err != nil {
		t.Fatalf("[%s] shutdown C: %v", mode, err)
	}
	live := []*Raft{rafts[0], rafts[1]}
	leaderAfterLoss := waitLeaderAmong(live, 6*time.Second)
	partialEvent(t, "after_losing_configured_voter_"+mode, map[string]interface{}{
		"mode":              mode,
		"any_leader":        leaderAfterLoss >= 0,
		"leader_index":      leaderAfterLoss,
		"servers_after":     configSizes(live),
		"live_voters":       2,
		"nodes_with_full":   fullConfigCount(live, 3),
		"log_last_index":    func() string { a, _ := logs[0].LastIndex(); b, _ := logs[1].LastIndex(); return fmt.Sprintf("%d,%d", a, b) }(),
	})

	for i := 0; i < 2; i++ {
		_ = rafts[i].Shutdown().Error()
	}
}
