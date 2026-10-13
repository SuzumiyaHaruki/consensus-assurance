// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
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

func caStart(t *testing.T, n *caNode, hb, lease time.Duration, configuration Configuration, bootstrap bool) *Raft {
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
			t.Fatalf("bootstrap %s: %v", n.id, err)
		}
	}
	r, err := NewRaft(conf, n.fsm, n.store, n.store, n.snap, n.trans)
	if err != nil {
		t.Fatalf("newraft %s: %v", n.id, err)
	}
	return r
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

// caViewOf reads one node's own configuration view of member id.
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

func TestAssuranceDemotionViewLag(t *testing.T) {
	for i := 1; i <= 3; i++ {
		caViewLagRun(t, fmt.Sprintf("run_%d", i))
	}
}

// caViewLagRun performs one voter-to-non-voter transition in a 4-node cluster
// with the per-node timing used by the extended-window scenario, sampling every
// node's own configuration view and log index continuously across the change.
func caViewLagRun(t *testing.T, caseName string) {
	const (
		leaderHB    = 20 * time.Second
		nearHB      = 6 * time.Second
		farHB       = 3 * time.Second
		sampleEvery = 20 * time.Millisecond
		observeFor  = 10 * time.Second
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
	leader, near := nodes[0], nodes[1]

	configuration := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: leader.id, Address: leader.addr},
		{Suffrage: Voter, ID: near.id, Address: near.addr},
		{Suffrage: Voter, ID: nodes[2].id, Address: nodes[2].addr},
		{Suffrage: Voter, ID: nodes[3].id, Address: nodes[3].addr},
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

	leader.raft = caStart(t, leader, leaderHB, leaderHB, configuration, true)
	near.raft = caStart(t, near, nearHB, nearHB, configuration, false)
	for _, n := range nodes[2:] {
		n.raft = caStart(t, n, farHB, farHB, configuration, false)
	}
	if !caWaitState(leader.raft, Leader, 60*time.Second) {
		t.Fatalf("%s: bootstrapped node did not become leader", caseName)
	}

	// Baseline: every follower has the configuration and the leader's no-op.
	baselineDeadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(baselineDeadline) {
		ready := true
		for _, n := range nodes[1:] {
			present, voter := caViewOf(n, n.id)
			if !present || !voter || n.raft.LastIndex() < 2 {
				ready = false
			}
		}
		if ready {
			break
		}
		time.Sleep(sampleEvery)
	}

	baseline := map[string]interface{}{"event": "baseline", "case": caseName}
	for _, n := range nodes {
		present, voter := caViewOf(n, near.id)
		baseline[n.role+"_near_present"] = present
		baseline[n.role+"_near_voter"] = voter
		baseline[n.role+"_last_index"] = n.raft.LastIndex()
	}
	baseline["leader_hb_ms"] = leaderHB.Milliseconds()
	baseline["near_hb_ms"] = nearHB.Milliseconds()
	baseline["far_hb_ms"] = farHB.Milliseconds()
	caEmit(baseline)

	demoteAt := time.Now()
	demoteErr := leader.raft.DemoteVoter(near.id, 0, 10*time.Second).Error()
	committedAt := time.Now()
	configIndex := leader.raft.LastIndex()

	type nodeObs struct {
		converged     bool
		convergedMs   int64
		staleObserved bool
		staleMaxIndex uint64
	}
	obs := map[string]*nodeObs{}
	for _, n := range nodes {
		obs[n.role] = &nodeObs{convergedMs: -1}
	}

	observeDeadline := time.Now().Add(observeFor)
	for time.Now().Before(observeDeadline) {
		allDone := true
		for _, n := range nodes {
			o := obs[n.role]
			if o.converged {
				continue
			}
			allDone = false
			_, voter := caViewOf(n, near.id)
			lastIdx := n.raft.LastIndex()
			if voter {
				o.staleObserved = true
				if lastIdx > o.staleMaxIndex {
					o.staleMaxIndex = lastIdx
				}
			} else {
				o.converged = true
				o.convergedMs = time.Since(committedAt).Milliseconds()
			}
		}
		if allDone {
			break
		}
		time.Sleep(sampleEvery)
	}

	for _, n := range nodes {
		o := obs[n.role]
		passed := o.staleObserved && o.staleMaxIndex >= configIndex
		caEmit(map[string]interface{}{
			"event":                    "demotion_view",
			"case":                     caseName,
			"role":                     n.role,
			"node_id":                  string(n.id),
			"converged":                o.converged,
			"converged_ms":             o.convergedMs,
			"stale_observed":           o.staleObserved,
			"stale_max_last_index":     o.staleMaxIndex,
			"config_index":             configIndex,
			"index_passed_while_stale": passed,
			"last_index_end":           n.raft.LastIndex(),
			"state_end":                n.raft.State().String(),
			"demote_error":             caErrString(demoteErr),
			"demote_commit_ms":         committedAt.Sub(demoteAt).Milliseconds(),
			"observed_ms":              time.Since(demoteAt).Milliseconds(),
		})
	}
}
