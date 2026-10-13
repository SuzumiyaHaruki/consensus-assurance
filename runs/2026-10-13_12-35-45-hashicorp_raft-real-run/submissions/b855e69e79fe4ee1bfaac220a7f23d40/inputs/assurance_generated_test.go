// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"sort"
	"testing"
	"time"
)

// caEmit prints one observation as a CA_EVENT JSON line.
func caEmit(ev map[string]interface{}) {
	b, err := json.Marshal(ev)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func caErrString(err error) string {
	if err == nil {
		return "nil"
	}
	return err.Error()
}

func caFsmHasLog(f FSM, want string) bool {
	m := getMockFSM(f)
	if m == nil {
		return false
	}
	for _, l := range m.Logs() {
		if string(l) == want {
			return true
		}
	}
	return false
}

func caVoters(cfg Configuration) (voters int, nonvoters int) {
	for _, s := range cfg.Servers {
		if s.Suffrage == Voter {
			voters++
		} else {
			nonvoters++
		}
	}
	return voters, nonvoters
}

// caScenario builds a real 4-node in-memory cluster, optionally moves one node
// from voter to non-voter through the public membership API, partitions the
// cluster so that the leader keeps only that node reachable, and then asks the
// leader whether it is still the leader (VerifyLeader).
//
// It returns true when a leader that answered "still leader" was observed
// while a different node was already leader in the voter majority.
func caScenario(t *testing.T, caseName string, attempt int, demote bool, isolateLeader bool, hb time.Duration) bool {
	conf := DefaultConfig()
	conf.HeartbeatTimeout = hb
	conf.ElectionTimeout = hb
	conf.LeaderLeaseTimeout = hb
	conf.CommitTimeout = 50 * time.Millisecond
	conf.SnapshotInterval = 120 * time.Second
	conf.Logger = newTestLogger(t)

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:           4,
		Bootstrap:       true,
		Conf:            conf,
		LongstopTimeout: 60 * time.Second,
	})
	defer c.Close()

	leader := c.Leader()
	followers := c.Followers()

	// Deterministic choice of the node that stays with the leader.
	sort.Slice(followers, func(i, j int) bool {
		return followers[i].localAddr < followers[j].localAddr
	})
	nearNode := followers[0]
	farNodes := followers[1:]

	if demote {
		if err := leader.DemoteVoter(nearNode.localID, 0, 10*time.Second).Error(); err != nil {
			caEmit(map[string]interface{}{
				"event": "setup", "case": caseName, "attempt": attempt,
				"setup_error": "demote failed: " + err.Error(),
			})
			return false
		}
		// Wait until the far side has applied the demotion, otherwise it would
		// still believe a 4-voter cluster needs 3 votes.
		deadline := time.Now().Add(5 * time.Second)
		for time.Now().Before(deadline) {
			done := true
			for _, f := range farNodes {
				if hasVote(c.getConfiguration(f), nearNode.localID) {
					done = false
				}
			}
			if done {
				break
			}
			time.Sleep(10 * time.Millisecond)
		}
	}

	cfg := c.getConfiguration(leader)
	voters, nonvoters := caVoters(cfg)

	caEmit(map[string]interface{}{
		"event": "setup", "case": caseName, "attempt": attempt,
		"hb_ms":            hb.Milliseconds(),
		"lease_ms":         conf.LeaderLeaseTimeout.Milliseconds(),
		"leader_id":        string(leader.localID),
		"near_node_id":     string(nearNode.localID),
		"near_node_voter":  hasVote(cfg, nearNode.localID),
		"voters":           voters,
		"nonvoters":        nonvoters,
		"quorum_size":      voters/2 + 1,
		"demoted":          demote,
		"isolate_leader":   isolateLeader,
		"far_node_ids":     []string{string(farNodes[0].localID), string(farNodes[1].localID)},
	})

	// Cut the leader off from the voter majority, keeping only nearNode
	// reachable (or cutting everything when isolateLeader is set).
	if isolateLeader {
		c.Disconnect(leader.localAddr)
	} else {
		// Keep the leader and nearNode connected to each other and cut both
		// off from the remaining (voting) nodes.
		c.Partition([]ServerAddress{leader.localAddr, nearNode.localAddr})
	}
	partAt := time.Now()
	caEmit(map[string]interface{}{
		"event": "partition", "case": caseName, "attempt": attempt,
		"leader_id": string(leader.localID), "near_node_id": string(nearNode.localID),
		"isolate_leader": isolateLeader,
	})

	resultCh := make(chan error, 1)
	go func() { resultCh <- leader.VerifyLeader().Error() }()

	var (
		gotResult   bool
		verifyErr   error
		seenBefore  bool
		otherLeader *Raft
	)
	ticker := time.NewTicker(20 * time.Millisecond)
	defer ticker.Stop()
	deadline := time.After(20 * time.Second)
WAIT:
	for {
		select {
		case err := <-resultCh:
			verifyErr = err
			gotResult = true
			break WAIT
		case <-deadline:
			break WAIT
		case <-ticker.C:
			for _, f := range farNodes {
				if f.State() == Leader {
					otherLeader = f
					seenBefore = true
				}
			}
		}
	}

	for _, f := range farNodes {
		if f.State() == Leader && otherLeader == nil {
			otherLeader = f
		}
	}

	caEmit(map[string]interface{}{
		"event": "verify_result", "case": caseName, "attempt": attempt,
		"returned":                   caErrString(verifyErr),
		"verify_returned_nil":        verifyErr == nil,
		"result_received":            gotResult,
		"elapsed_ms":                 time.Since(partAt).Milliseconds(),
		"leader_state":               leader.State().String(),
		"leader_id":                  string(leader.localID),
		"other_leader_before_result": seenBefore,
		"other_leader_after_result":  otherLeader != nil,
	})

	if verifyErr != nil {
		return false
	}

	// Give the voter majority the chance to elect a new leader while the
	// partitioned leader still reports success.
	waitUntil := time.Now().Add(4 * time.Second)
	for otherLeader == nil && time.Now().Before(waitUntil) {
		for _, f := range farNodes {
			if f.State() == Leader {
				otherLeader = f
			}
		}
		if otherLeader == nil {
			time.Sleep(20 * time.Millisecond)
		}
	}
	if otherLeader == nil {
		return false
	}

	const writePayload = "assurance-stale-write"
	idxFuture := otherLeader.Apply([]byte(writePayload), 5*time.Second)
	applyErr := idxFuture.Error()
	applyIndex := idxFuture.Index()

	leaderFSM := c.fsms[c.IndexOf(leader)]
	newLeaderFSM := c.fsms[c.IndexOf(otherLeader)]
	leaderHasWrite := caFsmHasLog(leaderFSM, writePayload)
	newLeaderHasWrite := caFsmHasLog(newLeaderFSM, writePayload)

	overlap := leader.State() == Leader && !leaderHasWrite && newLeaderHasWrite
	caEmit(map[string]interface{}{
		"event": "stale_read_window", "case": caseName, "attempt": attempt,
		"verify_returned_nil_earlier": true,
		"leader_state":                leader.State().String(),
		"leader_id":                   string(leader.localID),
		"new_leader_id":               string(otherLeader.localID),
		"apply_error":                 caErrString(applyErr),
		"apply_index":                 applyIndex,
		"elapsed_ms":                  time.Since(partAt).Milliseconds(),
		"leader_applied_index":        leader.AppliedIndex(),
		"new_leader_commit_index":     otherLeader.CommitIndex(),
		"leader_fsm_has_write":        leaderHasWrite,
		"new_leader_fsm_has_write":    newLeaderHasWrite,
		"stale_confirmed":             overlap,
	})
	return overlap
}

func TestAssuranceVerifyLeaderNonvoterQuorum(t *testing.T) {
	// Treatment: the node kept with the leader is a non-voter.
	for attempt := 1; attempt <= 3; attempt++ {
		if caScenario(t, "nonvoter_reachable", attempt, true, false, 3*time.Second) {
			break
		}
	}
	// Control 1: same reachable set, but that node is still a voter.
	caScenario(t, "control_same_set_voter", 1, false, false, 2*time.Second)
	// Control 2: same suffrage (non-voter), but the leader reaches nobody.
	caScenario(t, "control_nonvoter_unreachable", 1, true, true, 2*time.Second)
}
