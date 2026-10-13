// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
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

func caFsmHasLog(m *MockFSM, want string) bool {
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

func caCountVoters(cfg Configuration) (voters int, nonvoters int) {
	for _, s := range cfg.Servers {
		if s.Suffrage == Voter {
			voters++
		} else {
			nonvoters++
		}
	}
	return voters, nonvoters
}

// caNode is one real target instance with its own stores, FSM and transport.
type caNode struct {
	id    ServerID
	addr  ServerAddress
	trans *InmemTransport
	store *InmemStore
	snap  *InmemSnapshotStore
	fsm   *MockFSM
	raft  *Raft
}

func caConfigured(node *caNode) Configuration {
	f := node.raft.GetConfiguration()
	if err := f.Error(); err != nil {
		return Configuration{}
	}
	return f.Configuration()
}

// caProbe issues the public VerifyLeader call and waits up to deadline for the
// future to be answered.
func caProbe(r *Raft, deadline time.Duration) (err error, received bool) {
	ch := make(chan error, 1)
	go func() { ch <- r.VerifyLeader().Error() }()
	select {
	case err := <-ch:
		return err, true
	case <-time.After(deadline):
		return nil, false
	}
}

func caVoteOf(n *caNode, id ServerID) (inConfig bool, hasVote bool) {
	for _, s := range caConfigured(n).Servers {
		if s.ID == id {
			return true, s.Suffrage == Voter
		}
	}
	return false, false
}

func caWaitState(r *Raft, want RaftState, limit time.Duration) bool {
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if r.State() == want {
			return true
		}
		time.Sleep(10 * time.Millisecond)
	}
	return false
}

// caExtendedWindow builds a 4-node cluster in which only the leader has the
// long heartbeat/lease timing, so the two voting peers can elect a leader of
// their own long before the partitioned leader's lease expires. It then asks
// the partitioned leader whether it is still leader: immediately after the
// partition, and again once a competing leader exists.
func caExtendedWindow(t *testing.T, caseName string, demote bool, probeDeadline time.Duration) {
	const (
		leaderHB    = 20 * time.Second
		leaderLease = 20 * time.Second
		nearHB      = 6 * time.Second
		farHB       = 3 * time.Second
	)

	// Nodes must exist before the bootstrap configuration can list their
	// transport addresses.
	nodes := []*caNode{
		{id: "", addr: "", trans: nil, store: NewInmemStore(), snap: NewInmemSnapshotStore(), fsm: &MockFSM{}},
		{id: "", addr: "", trans: nil, store: NewInmemStore(), snap: NewInmemSnapshotStore(), fsm: &MockFSM{}},
		{id: "", addr: "", trans: nil, store: NewInmemStore(), snap: NewInmemSnapshotStore(), fsm: &MockFSM{}},
		{id: "", addr: "", trans: nil, store: NewInmemStore(), snap: NewInmemSnapshotStore(), fsm: &MockFSM{}},
	}
	for _, n := range nodes {
		addr, trans := NewInmemTransport("")
		n.addr = addr
		n.trans = trans
		n.id = ServerID("server-" + string(addr))
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

	// Only the leader is bootstrapped, so only it can campaign; the other
	// nodes have no configuration yet and adopt it from replication.
	leader.raft = caStart(t, leader, leaderHB, leaderLease, configuration, true)
	near.raft = caStart(t, near, nearHB, nearHB, configuration, false)
	far1.raft = caStart(t, far1, farHB, farHB, configuration, false)
	far2.raft = caStart(t, far2, farHB, farHB, configuration, false)

	if !caWaitState(leader.raft, Leader, 60*time.Second) {
		t.Fatalf("bootstrapped node did not become leader")
	}

	if demote {
		_, nearHoldsVote := caVoteOf(near, near.id)
		caEmit(map[string]interface{}{
			"event":            "pre_demote",
			"case":             caseName,
			"leader_is_leader": leader.raft.State() == Leader,
			"near_holds_vote":  nearHoldsVote,
			"near_last_index":  near.raft.LastIndex(),
		})
		if err := leader.raft.DemoteVoter(near.id, 0, 10*time.Second).Error(); err != nil {
			caEmit(map[string]interface{}{"event": "setup", "case": caseName, "setup_error": "demote failed: " + err.Error()})
			t.Fatalf("demote failed: %v", err)
		}
		deadline := time.Now().Add(10 * time.Second)
		for time.Now().Before(deadline) {
			_, ok1 := caVoteOf(far1, near.id)
			_, ok2 := caVoteOf(far2, near.id)
			if !ok1 && !ok2 {
				break
			}
			time.Sleep(20 * time.Millisecond)
		}
	}

	cfg := caConfigured(leader)
	voters, nonvoters := caCountVoters(cfg)
	nearVoterLeaderView := false
	for _, s := range cfg.Servers {
		if s.ID == near.id {
			nearVoterLeaderView = s.Suffrage == Voter
		}
	}
	// Give the near node's own view of the demotion a bounded chance to settle,
	// then record it separately from the leader's view.
	nearSelfVoter, _ := caVoteOf(near, near.id)
	if nearSelfVoter && !nearVoterLeaderView {
		settleUntil := time.Now().Add(3 * time.Second)
		for time.Now().Before(settleUntil) {
			selfVoter, _ := caVoteOf(near, near.id)
			nearSelfVoter = selfVoter
			if !nearSelfVoter {
				break
			}
			time.Sleep(20 * time.Millisecond)
		}
	}

	caEmit(map[string]interface{}{
		"event":                "setup",
		"case":                 caseName,
		"leader_id":            string(leader.id),
		"near_node_id":         string(near.id),
		"far_node_ids":         []string{string(far1.id), string(far2.id)},
		"near_node_voter":      nearVoterLeaderView,
		"near_node_self_voter": nearSelfVoter,
		"voters":               voters,
		"nonvoters":            nonvoters,
		"quorum_size":          voters/2 + 1,
		"leader_hb_ms":         leaderHB.Milliseconds(),
		"leader_lease_ms":      leaderLease.Milliseconds(),
		"far_hb_ms":            farHB.Milliseconds(),
		"demoted":              demote,
		"near_view_old":        nearSelfVoter,
		"near_last_index":      near.raft.LastIndex(),
		"near_commit_index":    near.raft.CommitIndex(),
		"near_applied_index":   near.raft.AppliedIndex(),
		"near_state":           near.raft.State().String(),
		"config_index":         leader.raft.LastIndex(),
		"view_old_and_log_complete": nearSelfVoter && near.raft.LastIndex() >= leader.raft.LastIndex(),
		"view_old_and_log_short":    nearSelfVoter && near.raft.LastIndex() < leader.raft.LastIndex(),
	})

	// Partition the leader (and the near node) from the two voting peers.
	partAt := time.Now()
	for _, a := range []*caNode{leader, near} {
		a.trans.Disconnect(far1.addr)
		a.trans.Disconnect(far2.addr)
	}
	for _, b := range []*caNode{far1, far2} {
		b.trans.Disconnect(leader.addr)
		b.trans.Disconnect(near.addr)
	}
	caEmit(map[string]interface{}{
		"event": "partition", "case": caseName,
		"leader_id": string(leader.id), "near_node_id": string(near.id),
	})

	err1, got1 := caProbe(leader.raft, probeDeadline)
	caEmit(map[string]interface{}{
		"event":               "verify_after_partition",
		"case":                caseName,
		"returned":            caErrString(err1),
		"verify_returned_nil": got1 && err1 == nil,
		"result_received":     got1,
		"elapsed_ms":          time.Since(partAt).Milliseconds(),
		"leader_lease_ms":     leaderLease.Milliseconds(),
		"leader_state":        leader.raft.State().String(),
	})

	// Wait for the voting peers to elect a leader of their own.
	var newLeader *caNode
	waitUntil := time.Now().Add(15 * time.Second)
	for newLeader == nil && time.Now().Before(waitUntil) {
		for _, n := range []*caNode{far1, far2} {
			if n.raft.State() == Leader {
				newLeader = n
			}
		}
		if newLeader == nil {
			time.Sleep(20 * time.Millisecond)
		}
	}

	if newLeader != nil {
		// Decisive probe: ask the old leader again while a competing leader
		// exists and while its own lease has not expired.
		err2, got2 := caProbe(leader.raft, 3*time.Second)
		caEmit(map[string]interface{}{
			"event":               "verify_while_superseded",
			"case":                caseName,
			"returned":            caErrString(err2),
			"verify_returned_nil": got2 && err2 == nil,
			"result_received":     got2,
			"elapsed_ms":          time.Since(partAt).Milliseconds(),
			"leader_lease_ms":     leaderLease.Milliseconds(),
			"old_leader_state":    leader.raft.State().String(),
			"new_leader_exists":   true,
			"new_leader_id":       string(newLeader.id),
			"new_leader_state":    newLeader.raft.State().String(),
		})

		const payload = "assurance-superseded-write"
		future := newLeader.raft.Apply([]byte(payload), 5*time.Second)
		applyErr := future.Error()
		applyIndex := future.Index()
		caEmit(map[string]interface{}{
			"event":                    "stale_write",
			"case":                     caseName,
			"elapsed_ms":               time.Since(partAt).Milliseconds(),
			"apply_error":              caErrString(applyErr),
			"apply_index":              applyIndex,
			"new_leader_id":            string(newLeader.id),
			"new_leader_fsm_has_write": caFsmHasLog(newLeader.fsm, payload),
			"new_leader_commit_index":  newLeader.raft.CommitIndex(),
			"old_leader_id":            string(leader.id),
			"old_leader_fsm_has_write": caFsmHasLog(leader.fsm, payload),
			"old_leader_applied_index": leader.raft.AppliedIndex(),
			"old_leader_state":         leader.raft.State().String(),
			"old_leader_is_leader":     leader.raft.State() == Leader,
		})
	}
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

func TestAssuranceVerifyLeaderSupersededLeader(t *testing.T) {
	// Treatment: the node kept with the leader is a non-voter, so the two
	// voting peers hold a majority and elect their own leader.
	caExtendedWindow(t, "long_leader_lease", true, 3*time.Second)
	// Control: same per-node timing, but the node kept with the leader still
	// votes, so no quorum exists on the far side and no competitor can appear.
	caExtendedWindow(t, "control_same_set_voter_long_lease", false, 45*time.Second)
}
