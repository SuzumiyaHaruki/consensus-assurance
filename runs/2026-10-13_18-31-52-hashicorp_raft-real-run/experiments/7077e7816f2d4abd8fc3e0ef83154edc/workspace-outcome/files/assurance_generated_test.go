package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func assuranceEmit(t *testing.T, fields map[string]interface{}) {
	b, err := json.Marshal(fields)
	if err != nil {
		return
	}
	fmt.Println("CA_EVENT " + string(b))
}

// boundedApply enqueues cmd on the leader and reports whether the apply future
// completed inside window. It never blocks the test past the window.
func boundedApply(leader *Raft, cmd string, window time.Duration) (committed bool, err error) {
	future := leader.Apply([]byte(cmd), window)
	done := make(chan error, 1)
	go func() { done <- future.Error() }()
	select {
	case e := <-done:
		return true, e
	case <-time.After(window):
		return false, nil
	}
}

// TestAssurance_NonvoterCommitEligibility checks whether a nonvoter's
// acknowledgement can advance the leader's commit index. The cluster is two
// Voters (quorum 2) plus one real Nonvoter that is fully caught up. Withholding
// the nonvoter must not affect commitment; withholding a voter must stall it
// even though the nonvoter keeps storing entries.
func TestAssurance_NonvoterCommitEligibility(t *testing.T) {
	c := MakeCluster(2, t, nil)
	defer c.Close()

	c1 := MakeClusterNoBootstrap(1, t, nil)
	defer c1.Close()

	c.Merge(c1)
	c.FullyConnect()

	leader := c.Leader()
	nonvoter := c1.rafts[0]

	future := leader.AddNonvoter(nonvoter.localID, nonvoter.localAddr, 0, 0)
	err := future.Error()
	assuranceEmit(t, map[string]interface{}{
		"event":             "addnonvoter_result",
		"err":               fmt.Sprintf("%v", err),
		"index":             future.Index(),
		"leader_id":         string(leader.localID),
		"nonvoter_id":       string(nonvoter.localID),
		"nonvoter_addr":     string(nonvoter.localAddr),
		"leader_last_index": leader.getLastIndex(),
		"leader_commit":     leader.getCommitIndex(),
	})

	// Let the new configuration and the nonvoter catch up.
	time.Sleep(300 * time.Millisecond)

	var voterFollower *Raft
	for _, r := range c.rafts {
		if r != leader && r.localID != nonvoter.localID {
			voterFollower = r
		}
	}
	if voterFollower == nil {
		t.Fatalf("no voter follower found")
	}

	assuranceEmit(t, map[string]interface{}{
		"event":              "baseline",
		"leader_commit":      leader.getCommitIndex(),
		"leader_last_index":  leader.getLastIndex(),
		"voter_last_index":   voterFollower.getLastIndex(),
		"nonvoter_last_index": nonvoter.getLastIndex(),
	})

	// Mode A: the Nonvoter is withheld; the two Voters are healthy.
	c.Disconnect(nonvoter.localAddr)
	commitA, errA := boundedApply(leader, "mode-a", 800*time.Millisecond)
	assuranceEmit(t, map[string]interface{}{
		"event":              "mode_a_nv_isolated",
		"committed_in_window": commitA,
		"err":                fmt.Sprintf("%v", errA),
		"leader_last_index":  leader.getLastIndex(),
		"leader_commit":      leader.getCommitIndex(),
		"nonvoter_last_index": nonvoter.getLastIndex(),
	})

	// Reconnect everyone, let the pipeline settle.
	c.FullyConnect()
	time.Sleep(300 * time.Millisecond)

	// Mode B: a Voter is withheld; the Nonvoter is healthy and can store logs.
	c.Disconnect(voterFollower.localAddr)
	beforeLast := leader.getLastIndex()
	commitB, errB := boundedApply(leader, "mode-b", 800*time.Millisecond)
	leaderLast := leader.getLastIndex()
	leaderCommit := leader.getCommitIndex()
	time.Sleep(300 * time.Millisecond)
	assuranceEmit(t, map[string]interface{}{
		"event":               "mode_b_voter_isolated",
		"committed_in_window": commitB,
		"err":                 fmt.Sprintf("%v", errB),
		"leader_last_before":  beforeLast,
		"leader_last_index":   leaderLast,
		"leader_commit":       leaderCommit,
		"nonvoter_last_index": nonvoter.getLastIndex(),
		"nonvoter_has_entry":  nonvoter.getLastIndex() >= leaderLast,
	})
}
