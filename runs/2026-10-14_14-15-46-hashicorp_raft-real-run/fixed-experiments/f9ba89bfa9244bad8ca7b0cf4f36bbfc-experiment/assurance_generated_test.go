// Copyright (c) 2026. Assurance harness artifact (draft, not part of the target source).
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

func caEmit(t *testing.T, payload interface{}) {
	t.Helper()
	blob, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(blob))
}

func caErrString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

// caReachable counts the peers of a leader whose last replication contact is
// within the leader lease, split by suffrage. This is a contact reading, not a
// reachability probe: right after a partition it still reflects contacts made
// before the partition, so it is reported as an informational operand and the
// partition side is reported separately as the applicability condition.
func caReachable(leader *Raft) (voters int, nonvoters int) {
	lease := leader.config().LeaderLeaseTimeout
	now := time.Now()
	for _, server := range leader.configurations.latest.Servers {
		if server.ID == leader.localID {
			continue
		}
		repl, ok := leader.leaderState.replState[server.ID]
		if !ok {
			continue
		}
		if now.Sub(repl.LastContact()) > lease {
			continue
		}
		if server.Suffrage == Voter {
			voters++
		} else {
			nonvoters++
		}
	}
	return voters, nonvoters
}

// caVerify runs one verification through the exported client API and reports
// the outcome, the vote tally the future observed, and the quorum it was
// measured against. The tally and quorum are read through the same in-package
// accessors the target's own tests use.
func caVerify(leader *Raft, wait time.Duration) (verified bool, errText string, votes, quorum int, returned bool) {
	done := make(chan struct{})
	vf := &verifyFuture{}
	vf.init()
	go func() {
		defer close(done)
		leader.verifyCh <- vf
	}()
	<-done
	quorum = leader.quorumSize()
	waitCh := make(chan error, 1)
	go func() { waitCh <- vf.Error() }()
	select {
	case err := <-waitCh:
		return err == nil, caErrString(err), vf.votes, quorum, true
	case <-time.After(wait):
		return false, "verification did not resolve", vf.votes, quorum, false
	}
}

// TestAssurance_VerifyLeaderNonvoterAck asks whether a leader that can no
// longer reach any other voter can still be confirmed as leader because a
// nonvoter's acknowledgement is counted towards the voter quorum.
//
// The cluster is four voters with one of them demoted to nonvoter through the
// normal DemoteVoter contract, giving three voters and one nonvoter. The
// interrupted case partitions the leader together with the nonvoter, so the
// leader can reach the nonvoter but no other voter; the control case
// partitions the leader on its own, so it can reach no peer at all. In the
// interrupted case the two remaining voters are then allowed to elect their own
// leader and commit an entry, and the interrupted leader's applied index is
// compared with that commit.
func TestAssurance_VerifyLeaderNonvoterAck(t *testing.T) {
	conf := inmemConfig(t)
	conf.Logger = hclog.NewNullLogger()

	caRunVerifyTrial(t, conf, 0, true)
	caRunVerifyTrial(t, conf, 1, false)
}

func caRunVerifyTrial(t *testing.T, conf *Config, trial int, withNonvoter bool) {
	t.Helper()

	c := MakeCluster(4, t, conf)
	defer c.Close()

	leader := c.Leader()
	followers := c.Followers()
	nonvoter := followers[0]

	// Demote one voter so the configuration has three voters and one nonvoter.
	if err := leader.DemoteVoter(nonvoter.localID, 0, 0).Error(); err != nil {
		t.Fatalf("trial %d: demote: %v", trial, err)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if !hasVote(leader.GetConfiguration().Configuration(), nonvoter.localID) {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	cfg := leader.configurations.latest
	if hasVote(cfg, nonvoter.localID) {
		t.Fatalf("trial %d: nonvoter still has a vote", trial)
	}

	// Baseline: the leader verifies while it can reach everyone.
	baseVerified, baseErr, baseVotes, baseQuorum, baseReturned := caVerify(leader, 2*time.Second)
	baseVoters, baseNonvoters := caReachable(leader)
	caEmit(t, map[string]interface{}{
		"event":                           "verify_baseline",
		"trial":                           trial,
		"case":                            caCaseName(withNonvoter),
		"verified":                        baseVerified,
		"error":                           baseErr,
		"votes":                           baseVotes,
		"quorum_size":                     baseQuorum,
		"returned":                        baseReturned,
		"peers_in_contact_within_lease":   baseVoters + baseNonvoters,
		"voter_peers_in_contact":          baseVoters,
		"nonvoter_reachable_only":         withNonvoter,
		"partition_leader_side_suffrages": caLeaderSideSuffrages(withNonvoter),
		"leader_last_index":               leader.getLastIndex(),
	})

	// Record a known point in the interrupted leader's own FSM.
	if err := leader.Apply([]byte("pre-partition"), 0).Error(); err != nil {
		t.Fatalf("trial %d: pre-partition apply: %v", trial, err)
	}
	beforeIndex := leader.getLastIndex()

	if withNonvoter {
		c.Partition([]ServerAddress{leader.localAddr, nonvoter.localAddr})
	} else {
		c.Partition([]ServerAddress{leader.localAddr})
	}
	time.Sleep(5 * time.Millisecond)

	reachVoters, reachNonvoters := caReachable(leader)
	verified, errText, votes, quorum, returned := caVerify(leader, 2*time.Second)
	leaderState := leader.getState().String()
	caEmit(t, map[string]interface{}{
		"event":                           "verify_partitioned",
		"trial":                           trial,
		"case":                            caCaseName(withNonvoter),
		"verified":                        verified,
		"error":                           errText,
		"votes":                           votes,
		"quorum_size":                     quorum,
		"returned":                        returned,
		"peers_in_contact_within_lease":   reachVoters + reachNonvoters,
		"voter_peers_in_contact":          reachVoters,
		"nonvoter_reachable_only":         withNonvoter,
		"partition_leader_side_suffrages": caLeaderSideSuffrages(withNonvoter),
		"leader_state":                    leaderState,
		"leader_last_index":               leader.getLastIndex(),
	})

	if !withNonvoter {
		return
	}

	// What the voters the interrupted leader cannot reach do next.
	var peerLeader *Raft
	deadline = time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		for _, r := range c.rafts {
			if r == leader || r == nonvoter {
				continue
			}
			if r.getState() == Leader {
				peerLeader = r
			}
		}
		if peerLeader != nil {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	writeIndex := uint64(0)
	writeCommitted := false
	if peerLeader != nil {
		future := peerLeader.Apply([]byte("committed-after-partition"), 0)
		if err := future.Error(); err != nil {
			t.Logf("trial %d: peer apply: %v", trial, err)
		} else {
			writeIndex = future.Index()
			writeCommitted = true
		}
	}
	time.Sleep(100 * time.Millisecond)
	caEmit(t, map[string]interface{}{
		"event":                "peer_side",
		"trial":                trial,
		"case":                 caCaseName(withNonvoter),
		"new_leader_elected":   peerLeader != nil,
		"write_committed":      writeCommitted,
		"write_index":          writeIndex,
		"leader_applied_index": leader.getLastApplied(),
		"leader_last_index":    leader.getLastIndex(),
		"index_before_partition": beforeIndex,
		"leader_applied_lags_new_commit": writeCommitted && leader.getLastApplied() < writeIndex,
	})
}

func caCaseName(withNonvoter bool) string {
	if withNonvoter {
		return "leader_with_nonvoter_reachable"
	}
	return "leader_alone"
}

// caLeaderSideSuffrages reports which peer suffrages the harness left on the
// interrupted leader's side of the partition. This is the applicability
// condition of the two verification comparisons: in one case the only peer the
// leader can exchange RPCs with is a nonvoter, and in the control case it has
// no peer at all.
func caLeaderSideSuffrages(withNonvoter bool) []string {
	if withNonvoter {
		return []string{"Nonvoter"}
	}
	return []string{}
}
