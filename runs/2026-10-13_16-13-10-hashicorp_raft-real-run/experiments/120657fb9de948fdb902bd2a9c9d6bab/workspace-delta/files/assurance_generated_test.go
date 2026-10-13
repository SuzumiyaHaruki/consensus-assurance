package raft

import (
	"fmt"
	"testing"
	"time"
)

// TestAssurance_ConfigIndexBasis observes, on one running bootstrapped leader,
// the configuration index that the public API hands to a caller
// (GetConfiguration().Index(), and Stats()["latest_configuration_index"])
// next to the index the main thread holds for the latest configuration entry
// (r.configurations.latestIndex, served over configurationsCh).
//
// Initialization: MakeCluster(3) bootstraps a real three-node cluster, which
// writes a real configuration entry (index 1) and elects a leader; one client
// command is then committed so that commit/applied indexes are past the
// configuration entry. No supplied state is injected.
func TestAssurance_ConfigIndexBasis(t *testing.T) {
	c := MakeCluster(3, t, nil)
	defer c.Close()

	leader := c.Leader() // fatals unless exactly one node is in Leader state
	leaderAddr := string(leader.localAddr)

	applied := leader.Apply([]byte("assurance-index-probe"), 5*time.Second)
	if err := applied.Error(); err != nil {
		t.Fatalf("apply failed: %v", err)
	}

	// The main thread's authoritative view of the configurations. This is the
	// path snapshot.go uses to obtain the committed configuration and its index.
	mainReq := &configurationsFuture{}
	mainReq.ShutdownCh = leader.shutdownCh
	mainReq.init()
	select {
	case leader.configurationsCh <- mainReq:
	case <-leader.shutdownCh:
		t.Fatalf("raft shut down before the configurations request was served")
	}
	if err := mainReq.Error(); err != nil {
		t.Fatalf("configurations future: %v", err)
	}

	public := leader.GetConfiguration()
	if err := public.Error(); err != nil {
		t.Fatalf("GetConfiguration: %v", err)
	}

	stats := leader.Stats()

	fmt.Printf("CA_EVENT {\"event\":\"config_index_observation\","+
		"\"leader_addr\":%q,"+
		"\"main_latest_index\":%d,"+
		"\"main_committed_index\":%d,"+
		"\"main_latest_servers\":%d,"+
		"\"public_index\":%d,"+
		"\"public_servers\":%d,"+
		"\"stats_latest_configuration_index\":%q,"+
		"\"stats_latest_configuration\":%q,"+
		"\"applied_index\":%q,"+
		"\"commit_index\":%q,\"term\":%q}\n",
		leaderAddr,
		mainReq.configurations.latestIndex,
		mainReq.configurations.committedIndex,
		len(mainReq.configurations.latest.Servers),
		public.Index(),
		len(public.Configuration().Servers),
		stats["latest_configuration_index"],
		stats["latest_configuration"],
		stats["applied_index"],
		stats["commit_index"],
		stats["term"],
	)
}
