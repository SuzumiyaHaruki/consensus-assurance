package raft

import (
	"fmt"
	"testing"
	"time"
)

// TestAssurance_AddVoterSuffrage asks whether the member added by the public
// AddVoter API is a voter from the moment it is added, as the implementation
// and its unit expectations say, or a staging/non-voting member promoted later
// once caught up, as the AddVoter documentation says.
//
// Initialization: MakeCluster(2) bootstraps a real two-voter cluster; a second
// single-node cluster with no bootstrap is merged in and fully connected, which
// is the in-tree way of joining a fresh, empty node (raft_test.go:258-279); the
// join itself is the public AddVoter call, made by the elected leader.
func TestAssurance_AddVoterSuffrage(t *testing.T) {
	c := MakeCluster(2, t, nil)
	defer c.Close()

	originals := append([]*Raft(nil), c.rafts...)

	c1 := MakeClusterNoBootstrap(1, t, nil)
	c.Merge(c1)
	c.FullyConnect()

	leader := c.Leader()
	newNode := c1.rafts[0]
	var peer *Raft
	for _, r := range originals {
		if r != leader {
			peer = r
		}
	}
	if peer == nil {
		t.Fatalf("could not identify the other original voter")
	}

	// Join the fresh, empty node through the documented public API.
	addErr := ""
	addIndex := uint64(0)
	addDone := make(chan error, 1)
	future := leader.AddVoter(newNode.localID, newNode.localAddr, 0, 5*time.Second)
	go func() { addDone <- future.Error() }()
	select {
	case err := <-addDone:
		if err != nil {
			addErr = err.Error()
		} else {
			addIndex = future.Index()
		}
	case <-time.After(10 * time.Second):
		addErr = "addvoter future did not return"
	}

	// Suffrage the leader wrote for the member it just added.
	leaderSuffrage := "absent"
	for _, s := range leader.getLatestConfiguration().Servers {
		if s.ID == newNode.localID {
			leaderSuffrage = s.Suffrage.String()
		}
	}
	targetSuffrage := "absent"
	for _, s := range newNode.getLatestConfiguration().Servers {
		if s.ID == newNode.localID {
			targetSuffrage = s.Suffrage.String()
		}
	}
	voters := 0
	for _, s := range leader.getLatestConfiguration().Servers {
		if s.Suffrage == Voter {
			voters++
		}
	}

	// Take one original voter away. If the added member votes, a majority of
	// the voters is still reachable (leader plus the new member); if the added
	// member is a non-voting member as the documentation describes, no
	// majority remains and a new command cannot commit.
	c.Disconnect(peer.localAddr)

	applyDone := make(chan error, 1)
	applied := leader.Apply([]byte("assurance-addvoter"), 5*time.Second)
	go func() { applyDone <- applied.Error() }()
	applyResult := "no_completion"
	applyWait := 8 * time.Second
	waitStart := time.Now()
	select {
	case err := <-applyDone:
		if err != nil {
			applyResult = "error:" + err.Error()
		} else {
			applyResult = "committed"
		}
	case <-time.After(applyWait):
	}
	waitedMs := time.Since(waitStart).Milliseconds()

	newLast := newNode.getLastIndex()
	leaderState := leader.State().String()

	fmt.Printf("CA_EVENT {\"event\":\"addvoter_suffrage\",\"leader_addr\":%q,\"new_node_addr\":%q,"+
		"\"disconnected_addr\":%q,\"add_err\":%q,\"add_index\":%d,"+
		"\"leader_view_suffrage\":%q,\"new_node_view_suffrage\":%q,\"voters_in_config\":%d,"+
		"\"apply_with_one_original_voter_gone\":%q,\"apply_waited_ms\":%d,"+
		"\"new_node_last_index\":%d,\"leader_state\":%q}\n",
		string(leader.localAddr), string(newNode.localAddr), string(peer.localAddr),
		addErr, addIndex, leaderSuffrage, targetSuffrage, voters,
		applyResult, waitedMs, newLast, leaderState)
}
