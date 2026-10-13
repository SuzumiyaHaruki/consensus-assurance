package raft

import (
	"fmt"
	"testing"
	"time"
)

// TestAssurance_AddNonvoterControl is the control for the AddVoter suffrage
// witness: the same cluster shape, the same merge-and-connect join, the same
// disconnect of one original voter and the same bounded apply, with only the
// public join call changed from AddVoter to AddNonvoter. It shows whether the
// disconnect discriminator really distinguishes a voting member from a
// non-voting one: with the added member holding no vote, a majority of the
// voters is unreachable once one original voter is gone, so the command must
// not commit.
func TestAssurance_AddNonvoterControl(t *testing.T) {
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

	addErr := ""
	addIndex := uint64(0)
	addDone := make(chan error, 1)
	future := leader.AddNonvoter(newNode.localID, newNode.localAddr, 0, 5*time.Second)
	go func() { addDone <- future.Error() }()
	select {
	case err := <-addDone:
		if err != nil {
			addErr = err.Error()
		} else {
			addIndex = future.Index()
		}
	case <-time.After(10 * time.Second):
		addErr = "addnonvoter future did not return"
	}

	leaderSuffrage := "absent"
	for _, s := range leader.getLatestConfiguration().Servers {
		if s.ID == newNode.localID {
			leaderSuffrage = s.Suffrage.String()
		}
	}
	voters := 0
	for _, s := range leader.getLatestConfiguration().Servers {
		if s.Suffrage == Voter {
			voters++
		}
	}

	c.Disconnect(peer.localAddr)

	applyDone := make(chan error, 1)
	applied := leader.Apply([]byte("assurance-addnonvoter"), 5*time.Second)
	go func() { applyDone <- applied.Error() }()
	applyResult := "no_completion"
	waitStart := time.Now()
	select {
	case err := <-applyDone:
		if err != nil {
			applyResult = "error:" + err.Error()
		} else {
			applyResult = "committed"
		}
	case <-time.After(8 * time.Second):
	}
	waitedMs := time.Since(waitStart).Milliseconds()

	newLast := newNode.getLastIndex()
	leaderState := leader.State().String()

	fmt.Printf("CA_EVENT {\"event\":\"addnonvoter_suffrage\",\"leader_addr\":%q,\"new_node_addr\":%q,"+
		"\"disconnected_addr\":%q,\"add_err\":%q,\"add_index\":%d,"+
		"\"leader_view_suffrage\":%q,\"voters_in_config\":%d,"+
		"\"apply_with_one_original_voter_gone\":%q,\"apply_waited_ms\":%d,"+
		"\"new_node_last_index\":%d,\"leader_state\":%q}\n",
		string(leader.localAddr), string(newNode.localAddr), string(peer.localAddr),
		addErr, addIndex, leaderSuffrage, voters,
		applyResult, waitedMs, newLast, leaderState)
}
