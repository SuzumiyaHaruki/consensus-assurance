package raft

import (
	"fmt"
	"testing"
	"time"
)

// TestAssurance_TransferToVoter is the control case for the same explicit
// leadership-transfer path: everything is identical to the vote-less-target
// case except that the named target keeps its vote. It exists to separate "the
// transfer mechanism does not work in this harness" from "the transfer works
// and a target that holds no vote cannot take the leadership".
//
// Initialization: MakeCluster(4) bootstraps a real four-voter cluster and
// elects a leader; a real follower is picked as the target and is left as a
// voter, so the configuration, the catch-up wait and the TimeoutNow delivery
// are the same as in the vote-less case.
func TestAssurance_TransferToVoter(t *testing.T) {
	c := MakeCluster(4, t, nil)
	defer c.Close()

	leader := c.Leader()
	leaderAddr := string(leader.localAddr)

	var followers []*Raft
	limit := time.Now().Add(c.longstopTimeout)
	for time.Now().Before(limit) && len(followers) == 0 {
		c.WaitEvent(nil, c.conf.CommitTimeout)
		followers = c.GetInState(Follower)
	}
	if len(followers) == 0 {
		t.Fatalf("no follower available as a transfer target")
	}
	target := followers[0]
	targetAddr := string(target.localAddr)

	suffrage := "unknown"
	for _, s := range leader.getLatestConfiguration().Servers {
		if s.ID == target.localID {
			suffrage = s.Suffrage.String()
		}
	}

	termBefore := uint64(0)
	for _, r := range c.rafts {
		if term := r.getCurrentTerm(); term > termBefore {
			termBefore = term
		}
	}

	transferErr := ""
	if err := leader.LeadershipTransferToServer(target.localID, target.localAddr).Error(); err != nil {
		transferErr = err.Error()
	}

	deadline := time.Now().Add(3 * time.Second)
	targetEverLeader := false
	originalLeaderLedAgain := false
	seenLeaders := map[string]bool{}
	for time.Now().Before(deadline) {
		for _, r := range c.rafts {
			if r.getState() != Leader {
				continue
			}
			a := string(r.localAddr)
			seenLeaders[a] = true
			if a == targetAddr {
				targetEverLeader = true
			}
			if a == leaderAddr {
				originalLeaderLedAgain = true
			}
		}
		time.Sleep(20 * time.Millisecond)
	}

	termAfter := uint64(0)
	for _, r := range c.rafts {
		if term := r.getCurrentTerm(); term > termAfter {
			termAfter = term
		}
	}

	leaders := ""
	for a := range seenLeaders {
		if leaders != "" {
			leaders += ","
		}
		leaders += a
	}
	leaderState := leader.State().String()
	targetState := target.State().String()

	fmt.Printf("CA_EVENT {\"event\":\"transfer_to_voter\",\"leader_addr\":%q,\"target_addr\":%q,"+
		"\"target_suffrage\":%q,\"transfer_err\":%q,"+
		"\"target_ever_leader\":%t,\"original_leader_led_again\":%t,\"leaders_seen\":%q,"+
		"\"leader_state_at_end\":%q,\"target_state_at_end\":%q,"+
		"\"term_before\":%d,\"term_after\":%d}\n",
		leaderAddr, targetAddr, suffrage, transferErr,
		targetEverLeader, originalLeaderLedAgain, leaders,
		leaderState, targetState, termBefore, termAfter)
}
