// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"strconv"
	"testing"
	"time"
)

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

type caNode struct {
	id    ServerID
	addr  ServerAddress
	trans *InmemTransport
	store *InmemStore
	snap  *InmemSnapshotStore
	fsm   *MockFSM
	raft  *Raft
	role  string
}

func caTerm(n *caNode) uint64 {
	v, err := strconv.ParseUint(n.raft.Stats()["term"], 10, 64)
	if err != nil {
		return 0
	}
	return v
}

func caWaitState(r *Raft, want RaftState, limit time.Duration) bool {
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if r.State() == want {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	return false
}

func caViewOf(n *caNode, id ServerID) (present bool, voter bool) {
	f := n.raft.GetConfiguration()
	if err := f.Error(); err != nil {
		return false, false
	}
	for _, s := range f.Configuration().Servers {
		if s.ID == id {
			return true, s.Suffrage == Voter
		}
	}
	return false, false
}

// caTransferRun transfers leadership to a target that either holds a vote or
// does not, and records what happens to the current leadership and to the
// target.
func caTransferRun(t *testing.T, caseName string, targetIsNonvoter bool) {
	const (
		hb    = 2 * time.Second
		lease = time.Second
	)

	nodes := make([]*caNode, 4)
	for i := range nodes {
		addr, trans := NewInmemTransport("")
		nodes[i] = &caNode{
			id:    ServerID("server-" + string(addr)),
			addr:  addr,
			trans: trans,
			store: NewInmemStore(),
			snap:  NewInmemSnapshotStore(),
			fsm:   &MockFSM{},
		}
	}
	for i, role := range []string{"leader", "near", "far1", "far2"} {
		nodes[i].role = role
	}
	leader, near, far1, far2 := nodes[0], nodes[1], nodes[2], nodes[3]

	configuration := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: leader.id, Address: leader.addr},
		{Suffrage: Voter, ID: near.id, Address: near.addr},
		{Suffrage: Voter, ID: far1.id, Address: far1.addr},
		{Suffrage: Voter, ID: far2.id, Address: far2.addr},
	}}
	for i, n1 := range nodes {
		for j, n2 := range nodes {
			if i != j {
				n1.trans.Connect(n2.addr, n2.trans)
			}
		}
	}
	defer func() {
		for _, n := range nodes {
			if n.raft != nil {
				_ = n.raft.Shutdown().Error()
			}
			n.trans.Close()
		}
	}()

	start := func(n *caNode, bootstrap bool) {
		conf := DefaultConfig()
		conf.HeartbeatTimeout = hb
		conf.ElectionTimeout = hb
		conf.LeaderLeaseTimeout = lease
		conf.CommitTimeout = 200 * time.Millisecond
		conf.SnapshotInterval = 120 * time.Second
		conf.LocalID = n.id
		conf.Logger = newTestLoggerWithPrefix(t, string(n.id))
		if bootstrap {
			if err := BootstrapCluster(conf, n.store, n.store, n.snap, n.trans, configuration); err != nil {
				t.Fatalf("bootstrap: %v", err)
			}
		}
		r, err := NewRaft(conf, n.fsm, n.store, n.store, n.snap, n.trans)
		if err != nil {
			t.Fatalf("newraft: %v", err)
		}
		n.raft = r
	}
	start(leader, true)
	for _, n := range []*caNode{near, far1, far2} {
		start(n, false)
	}
	if !caWaitState(leader.raft, Leader, 60*time.Second) {
		t.Fatalf("%s: bootstrapped node did not become leader", caseName)
	}

	// Make the target a non-voter for the treatment, and wait for the change
	// to be visible to the two far nodes.
	if targetIsNonvoter {
		if err := leader.raft.DemoteVoter(near.id, 0, 10*time.Second).Error(); err != nil {
			t.Fatalf("%s: demote failed: %v", caseName, err)
		}
		deadline := time.Now().Add(10 * time.Second)
		for time.Now().Before(deadline) {
			_, v1 := caViewOf(far1, near.id)
			_, v2 := caViewOf(far2, near.id)
			if !v1 && !v2 {
				break
			}
			time.Sleep(20 * time.Millisecond)
		}
	}

	target := far1
	targetRole := "far1_voter"
	if targetIsNonvoter {
		target = near
		targetRole = "near_nonvoter"
	}

	termsBefore := map[string]uint64{}
	for _, n := range nodes {
		termsBefore[n.role] = caTerm(n)
	}
	_, targetVoter := caViewOf(leader, target.id)
	caEmit(map[string]interface{}{
		"event":            "setup",
		"case":             caseName,
		"target_role":      targetRole,
		"target_id":        string(target.id),
		"target_has_vote":  targetVoter,
		"leader_id":        string(leader.id),
		"leader_is_leader": leader.raft.State() == Leader,
		"leader_term":      termsBefore["leader"],
	})

	resultCh := make(chan error, 1)
	transferAt := time.Now()
	go func() { resultCh <- leader.raft.LeadershipTransferToServer(target.id, target.addr).Error() }()

	var (
		transferErr error
		gotResult   bool
	)
	select {
	case err := <-resultCh:
		transferErr = err
		gotResult = true
	case <-time.After(15 * time.Second):
	}
	caEmit(map[string]interface{}{
		"event":             "transfer_result",
		"case":              caseName,
		"target_role":       targetRole,
		"returned":          caErrString(transferErr),
		"returned_nil":      gotResult && transferErr == nil,
		"result_received":   gotResult,
		"elapsed_ms":        time.Since(transferAt).Milliseconds(),
		"leader_state":      leader.raft.State().String(),
		"target_state":      target.raft.State().String(),
		"leader_is_leader":  leader.raft.State() == Leader,
		"target_is_leader":  target.raft.State() == Leader,
	})

	// Watch the cluster for a while: does leadership survive, and does the
	// target ever take it?
	var (
		anyLeaderAfter       bool
		leaderAfterID        string
		targetBecameLeader   bool
		oldLeaderStillLeader bool
		termsIncreased       bool
	)
	watchUntil := time.Now().Add(8 * time.Second)
	for time.Now().Before(watchUntil) {
		for _, n := range nodes {
			if n.raft.State() == Leader {
				anyLeaderAfter = true
				leaderAfterID = string(n.id)
				if n.id == target.id {
					targetBecameLeader = true
				}
				if n.id == leader.id {
					oldLeaderStillLeader = true
				}
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	for _, n := range nodes {
		if caTerm(n) > termsBefore[n.role] {
			termsIncreased = true
		}
	}
	caEmit(map[string]interface{}{
		"event":                  "transfer_summary",
		"case":                   caseName,
		"target_role":            targetRole,
		"old_leader_still_leader": oldLeaderStillLeader,
		"old_leader_state_end":   leader.raft.State().String(),
		"target_became_leader":   targetBecameLeader,
		"target_state_end":       target.raft.State().String(),
		"any_leader_after":       anyLeaderAfter,
		"leader_after_id":        leaderAfterID,
		"terms_increased":        termsIncreased,
		"observed_ms":            time.Since(transferAt).Milliseconds(),
	})
}

func TestAssuranceLeadershipTransferTargetSuffrage(t *testing.T) {
	caTransferRun(t, "transfer_to_nonvoter", true)
	caTransferRun(t, "transfer_to_voter", false)
}
