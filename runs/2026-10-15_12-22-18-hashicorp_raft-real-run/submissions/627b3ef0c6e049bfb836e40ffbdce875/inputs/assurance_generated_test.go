// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"testing"
	"time"
)

// assuranceProbeNode is one real Raft instance in this process, with its own
// store, snapshot store and in-memory transport.
type assuranceProbeNode struct {
	id    ServerID
	addr  ServerAddress
	trans *InmemTransport
	raft  *Raft
}

func assuranceProbeConfig(t *testing.T, tag string, localID ServerID) *Config {
	conf := DefaultConfig()
	conf.HeartbeatTimeout = 200 * time.Millisecond
	conf.ElectionTimeout = 200 * time.Millisecond
	conf.LeaderLeaseTimeout = 200 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.LocalID = localID
	conf.Logger = newTestLoggerWithPrefix(t, tag)
	return conf
}

func assuranceNewNode() *assuranceProbeNode {
	addr, trans := NewInmemTransport("")
	return &assuranceProbeNode{addr: addr, trans: trans, id: ServerID("server-" + string(addr))}
}

func assuranceStartNode(t *testing.T, n *assuranceProbeNode, bootstrap *Configuration) {
	pc := assuranceProbeConfig(t, string(n.id), n.id)
	store := NewInmemStore()
	snap := NewInmemSnapshotStore()
	if bootstrap != nil {
		if err := BootstrapCluster(pc, store, store, snap, n.trans, *bootstrap); err != nil {
			t.Fatalf("BootstrapCluster failed: %v", err)
		}
	}
	r, err := NewRaft(pc, &MockFSM{}, store, store, snap, n.trans)
	if err != nil {
		t.Fatalf("NewRaft failed: %v", err)
	}
	n.raft = r
}

func assuranceWaitLeader(t *testing.T, nodes []*assuranceProbeNode, limit time.Duration) *assuranceProbeNode {
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		for _, n := range nodes {
			if n.raft.State() == Leader {
				return n
			}
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("no leader elected within %s", limit)
	return nil
}

func assuranceHasServer(c Configuration, id ServerID) bool {
	for _, s := range c.Servers {
		if s.ID == id {
			return true
		}
	}
	return false
}

func assuranceEmit(t *testing.T, event map[string]interface{}) {
	b, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	t.Log("CA_EVENT " + string(b))
}

func assuranceLeaderIDs(nodes []*assuranceProbeNode) []string {
	var ids []string
	for _, n := range nodes {
		if n.raft.State() == Leader {
			ids = append(ids, string(n.id))
		}
	}
	return ids
}

func assuranceMaxTerm(nodes []*assuranceProbeNode) uint64 {
	var maxTerm uint64
	for _, n := range nodes {
		if term := n.raft.getCurrentTerm(); term > maxTerm {
			maxTerm = term
		}
	}
	return maxTerm
}

// assuranceBuildCluster starts three voters plus one non-voter, joined through
// the elected leader's own AddNonvoter call, and returns them.
func assuranceBuildCluster(t *testing.T, tag string) ([]*assuranceProbeNode, *assuranceProbeNode, *assuranceProbeNode) {
	var voters Configuration
	var nodes []*assuranceProbeNode
	for i := 0; i < 3; i++ {
		n := assuranceNewNode()
		nodes = append(nodes, n)
		voters.Servers = append(voters.Servers, Server{Suffrage: Voter, ID: n.id, Address: n.addr})
	}
	nv := assuranceNewNode()
	nodes = append(nodes, nv)
	for _, a := range nodes {
		for _, b := range nodes {
			if a != b {
				a.trans.Connect(b.addr, b.trans)
			}
		}
	}
	for _, n := range nodes[:3] {
		assuranceStartNode(t, n, &voters)
	}
	assuranceStartNode(t, nv, nil)

	leader := assuranceWaitLeader(t, nodes[:3], 10*time.Second)
	if err := leader.raft.AddNonvoter(nv.id, nv.addr, 0, 5*time.Second).Error(); err != nil {
		t.Fatalf("AddNonvoter failed: %v", err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) && !assuranceHasServer(leader.raft.getLatestConfiguration(), nv.id) {
		time.Sleep(5 * time.Millisecond)
	}
	if !assuranceHasServer(leader.raft.getLatestConfiguration(), nv.id) {
		t.Fatalf("non-voter %v never appeared in the leader configuration", nv.id)
	}
	time.Sleep(300 * time.Millisecond)
	return nodes, leader, nv
}

// assuranceRunTransferCase asks the leader to transfer leadership to a chosen
// target and records what the call reported versus which server actually took
// leadership. The target is chosen by its role in the configuration, never by
// an observed outcome.
func assuranceRunTransferCase(t *testing.T, caseName string, useNonvoter bool) {
	nodes, leader, nv := assuranceBuildCluster(t, caseName)
	defer func() {
		for _, n := range nodes {
			_ = n.raft.Shutdown().Error()
			_ = n.trans.Close()
		}
	}()

	var target *assuranceProbeNode
	if useNonvoter {
		target = nv
	} else {
		for _, n := range nodes[:3] {
			if n != leader {
				target = n
				break
			}
		}
	}

	latest := leader.raft.getLatestConfiguration()
	targetSuffrage := "absent"
	var voterIDs, nonvoterIDs []string
	for _, s := range latest.Servers {
		if s.Suffrage == Voter {
			voterIDs = append(voterIDs, string(s.ID))
		} else {
			nonvoterIDs = append(nonvoterIDs, string(s.ID))
		}
		if s.ID == target.id {
			targetSuffrage = s.Suffrage.String()
		}
	}

	leaderTermBefore := leader.raft.getCurrentTerm()
	assuranceEmit(t, map[string]interface{}{
		"event":              "assurance_transfer_target",
		"case":               caseName,
		"leader_id":          string(leader.id),
		"target_id":          string(target.id),
		"target_is_nonvoter": useNonvoter,
		"target_suffrage":    targetSuffrage,
		"target_state_before": target.raft.State().String(),
		"leader_term_before": leaderTermBefore,
		"voters":             voterIDs,
		"voter_count":        len(voterIDs),
		"nonvoters":          nonvoterIDs,
		"election_timeout":   leader.raft.config().ElectionTimeout.String(),
		"pre_vote_default":   !leader.raft.preVoteDisabled,
	})

	future := leader.raft.LeadershipTransferToServer(target.id, target.addr)
	transferErr := "pending"
	done := make(chan error, 1)
	go func() { done <- future.Error() }()
	select {
	case err := <-done:
		if err == nil {
			transferErr = "nil"
		} else {
			transferErr = err.Error()
		}
	case <-time.After(5 * time.Second):
	}
	returnedAt := time.Now()

	// Wait up to 1500ms for the requested target, and separately for any
	// leader, recording both without filtering on the transfer result.
	targetBecameLeader := false
	msToTargetLeader := int64(0)
	deadline := time.Now().Add(1500 * time.Millisecond)
	for time.Now().Before(deadline) {
		if target.raft.State() == Leader {
			targetBecameLeader = true
			msToTargetLeader = time.Since(returnedAt).Milliseconds()
			break
		}
		time.Sleep(5 * time.Millisecond)
	}

	leaderIDsAfter := assuranceLeaderIDs(nodes)
	msToAnyLeader := int64(-1)
	for _, n := range nodes {
		if n.raft.State() == Leader {
			msToAnyLeader = 0
			break
		}
	}
	if msToAnyLeader < 0 {
		deadline = time.Now().Add(3 * time.Second)
		for time.Now().Before(deadline) {
			if len(assuranceLeaderIDs(nodes)) > 0 {
				msToAnyLeader = time.Since(returnedAt).Milliseconds()
				break
			}
			time.Sleep(5 * time.Millisecond)
		}
	}
	leaderIDsEndpoint := assuranceLeaderIDs(nodes)
	maxTermAfter := assuranceMaxTerm(nodes)

	assuranceEmit(t, map[string]interface{}{
		"event":                    "assurance_transfer_result",
		"case":                     caseName,
		"leader_id":                string(leader.id),
		"target_id":                string(target.id),
		"target_is_nonvoter":       useNonvoter,
		"target_suffrage":          targetSuffrage,
		"transfer_error":           transferErr,
		"target_became_leader":     targetBecameLeader,
		"target_state_after":       target.raft.State().String(),
		"old_leader_state_after":   leader.raft.State().String(),
		"leader_ids_after":         leaderIDsAfter,
		"leader_count_after":       len(leaderIDsAfter),
		"ms_to_target_leader":      msToTargetLeader,
		"ms_to_any_leader":         msToAnyLeader,
		"leader_ids_endpoint":      leaderIDsEndpoint,
		"leader_term_before":       leaderTermBefore,
		"max_term_after":           maxTermAfter,
		"max_term_increased":       maxTermAfter > leaderTermBefore,
		"election_timeout_ms":      leader.raft.config().ElectionTimeout.Milliseconds(),
	})
}

// TestAssuranceLeadershipTransferTargetSender compares a leadership transfer
// requested for a voter with the same call requested for a non-voter.
func TestAssuranceLeadershipTransferTarget(t *testing.T) {
	assuranceRunTransferCase(t, "target-voter", false)
	assuranceRunTransferCase(t, "target-nonvoter", true)
}
