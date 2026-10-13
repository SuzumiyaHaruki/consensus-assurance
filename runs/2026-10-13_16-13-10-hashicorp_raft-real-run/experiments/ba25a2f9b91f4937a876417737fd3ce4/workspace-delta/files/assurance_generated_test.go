package raft

import (
	"fmt"
	"testing"
	"time"
)

// TestAssurance_TransferToNonVoter asks what a caller actually receives when it
// names a server that holds no vote as the target of an explicit leadership
// transfer.
//
// Initialization: MakeCluster(4) bootstraps a real four-voter cluster and
// elects a leader. One follower is then demoted to a non-voter through the
// public DemoteVoter API (a committed configuration change), so the named
// target is a real, connected, log-receiving member of the configuration that
// the leader itself replicates to, but holds no vote.
func TestAssurance_TransferToNonVoter(t *testing.T) {
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

	// Demote the target through the public API and wait for that configuration
	// entry to be applied.
	demoteErr := ""
	if err := leader.DemoteVoter(target.localID, 0, 5*time.Second).Error(); err != nil {
		demoteErr = err.Error()
	}

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

	// Ask for the transfer to the named, vote-less target.
	transferErr := ""
	if err := leader.LeadershipTransferToServer(target.localID, target.localAddr).Error(); err != nil {
		transferErr = err.Error()
	}

	// Watch who actually leads for a bounded interval, and whether the named
	// target ever reaches Leader.
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

	fmt.Printf("CA_EVENT {\"event\":\"transfer_to_nonvoter\",\"leader_addr\":%q,\"target_addr\":%q,"+
		"\"target_suffrage\":%q,\"demote_err\":%q,\"transfer_err\":%q,"+
		"\"target_ever_leader\":%t,\"original_leader_led_again\":%t,\"leaders_seen\":%q,"+
		"\"leader_state_at_end\":%q,\"target_state_at_end\":%q,"+
		"\"term_before\":%d,\"term_after\":%d}\n",
		leaderAddr, targetAddr, suffrage, demoteErr, transferErr,
		targetEverLeader, originalLeaderLedAgain, leaders,
		leaderState, targetState, termBefore, termAfter)
}
