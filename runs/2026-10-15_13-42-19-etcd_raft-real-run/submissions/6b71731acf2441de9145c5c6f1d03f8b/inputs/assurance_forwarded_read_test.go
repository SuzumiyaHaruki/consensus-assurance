package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	pb "go.etcd.io/raft/v3/raftpb"
)

func assurance6Emit(t *testing.T, ev map[string]any) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("cannot marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func assurance6IsVoter(r *raft) bool {
	_, ok := r.trk.Voters.IDs()[r.id]
	return ok
}

// TestAssuranceReadIndexForwardedToRemovedSingletonLeader measures the second
// route into the same missing membership check: a ReadIndex request that was
// issued on another node, forwarded by that node to the leader it knows, and
// delivered to that leader while it is still leading a configuration whose only
// voter is someone else. The requester is the group's learner, and the
// forwarded request is delivered only after the application has applied the
// committed removal of the leader and the remaining voter has become leader of
// the reduced configuration and committed a further entry.
func TestAssuranceReadIndexForwardedToRemovedSingletonLeader(t *testing.T) {
	const scenario = "removed-singleton-leader-read-forwarded"

	mk := func(id uint64) *raft {
		s := newTestMemoryStorage(withPeers(1, 2), withLearners(3))
		cfg := newTestConfig(id, 10, 1, s)
		cfg.PreVote = true
		return newRaft(cfg)
	}
	n1, n2, n3 := mk(1), mk(2), mk(3)
	nt := newNetwork(n1, n2, n3)
	setRandomizedElectionTimeout(n2, n2.electionTimeout*10)
	setRandomizedElectionTimeout(n3, n3.electionTimeout*10)

	assurance6Emit(t, map[string]any{
		"scenario":       scenario,
		"event":          "c_setup",
		"step":           "setup",
		"cluster":        "voters=(1 2), learner=(3)",
		"prevote":        true,
		"heartbeat_tick": n1.heartbeatTimeout,
		"election_tick":  n1.electionTimeout,
		"requester_role": "learner",
		"delivery":       "the requester's forwarded request and its answer are held until after the removal",
	})

	// Node 1 is elected leader of {1,2}; every node hears from it, so node 3
	// knows node 1 as its leader.
	nt.send(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgHup.Enum()})
	nextEnts(n1, n1.raftLog.storage.(*MemoryStorage))
	nextEnts(n2, n2.raftLog.storage.(*MemoryStorage))

	// The requester's application issues a read while node 1 is still the leader
	// it knows. The forwarded message leaves the requester, but its delivery is
	// held back, so it reaches node 1 only after the group has moved on.
	if err := n3.Step(&pb.Message{
		From:    new(uint64(3)),
		To:      new(uint64(3)),
		Type:    pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("R")}},
	}); err != nil {
		t.Fatalf("read index on the requester: %v", err)
	}
	held := n3.readMessages()
	requesterReadStates := len(n3.readStates)
	requesterLead := n3.lead
	requesterTerm := n3.Term
	requesterConfig := n3.trk.Config.String()
	forwardType, forwardTo := "", uint64(0)
	if len(held) > 0 {
		forwardType, forwardTo = held[0].GetType().String(), held[0].GetTo()
	}

	// The application proposes removing node 1 - the leader - and applies the
	// committed change on the two voters.
	cc := &pb.ConfChange{Type: pb.ConfChangeRemoveNode.Enum(), NodeId: new(uint64(1))}
	m, err := confChangeToMsg(cc)
	if err != nil {
		t.Fatalf("conf change message: %v", err)
	}
	m.From, m.To = new(uint64(1)), new(uint64(1))
	nt.send(m)
	ccv2 := cc.AsV2()
	n1.applyConfChange(ccv2)
	n2.applyConfChange(ccv2)
	nextEnts(n1, n1.raftLog.storage.(*MemoryStorage))
	nextEnts(n2, n2.raftLog.storage.(*MemoryStorage))

	assurance6Emit(t, map[string]any{
		"scenario":        scenario,
		"event":           "e_leader_removed",
		"step":            "leader-1-removed",
		"node":            1,
		"state":           n1.state.String(),
		"term":            n1.Term,
		"config":          n1.trk.Config.String(),
		"singleton":       n1.trk.IsSingleton(),
		"is_voter":        assurance6IsVoter(n1),
		"committed_index": n1.raftLog.committed,
	})

	// The remaining voter becomes leader of {2} and commits a new entry. Its
	// messages are drained instead of delivered: the requester has not heard
	// from the new leader yet.
	if err := n2.Step(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgHup.Enum()}); err != nil {
		t.Fatalf("node 2 campaign: %v", err)
	}
	n2.readMessages()
	if err := n2.Step(&pb.Message{
		From:    new(uint64(2)),
		To:      new(uint64(2)),
		Type:    pb.MsgProp.Enum(),
		Entries: []*pb.Entry{{Data: []byte("w")}},
	}); err != nil {
		t.Fatalf("node 2 proposal: %v", err)
	}
	n2.readMessages()
	otherCommitted := n2.raftLog.committed

	assurance6Emit(t, map[string]any{
		"scenario":                       scenario,
		"event":                          "e_new_leader_committed",
		"step":                           "node-2-leads",
		"node":                           2,
		"state":                          n2.state.String(),
		"term":                           n2.Term,
		"config":                         n2.trk.Config.String(),
		"committed_index":                otherCommitted,
		"last_index":                     n2.raftLog.lastIndex(),
		"removed_leader_committed_index": n1.raftLog.committed,
		"removed_leader_term":            n1.Term,
		"removed_leader_state":           n1.state.String(),
		"actual_leader_ahead":            otherCommitted > n1.raftLog.committed,
	})

	// The held request now reaches the removed leader.
	for _, heldMsg := range held {
		if err := n1.Step(heldMsg); err != nil {
			t.Fatalf("step held request into the removed leader: %v", err)
		}
	}
	answers := n1.readMessages()

	assurance6Emit(t, map[string]any{
		"scenario":                       scenario,
		"event":                          "e_forwarded_request",
		"step":                           "held-forward-reaches-removed-leader",
		"node":                           3,
		"requester_lead":                 requesterLead,
		"requester_term":                 requesterTerm,
		"requester_state":                n3.state.String(),
		"requester_config":               requesterConfig,
		"requester_read_states":          requesterReadStates,
		"forward_type":                   forwardType,
		"forward_to":                     forwardTo,
		"forwarded_to_removed_leader":    forwardTo == 1 && forwardType == pb.MsgReadIndex.String(),
		"removed_leader_state":           n1.state.String(),
		"removed_leader_config":          n1.trk.Config.String(),
		"removed_leader_committed_index": n1.raftLog.committed,
		"other_committed_index":          otherCommitted,
		"singleton":                      n1.trk.IsSingleton(),
		"answer_count":                   len(answers),
	})

	// The answer travels back to the requester, which consumes it.
	answerType, answerTo, answerIndex := "", uint64(0), uint64(0)
	for _, answer := range answers {
		if answer.GetType() == pb.MsgReadIndexResp {
			answerType, answerTo, answerIndex = answer.GetType().String(), answer.GetTo(), answer.GetIndex()
			break
		}
	}
	for _, answer := range answers {
		if err := n3.Step(answer); err != nil {
			t.Fatalf("step answer into the requester: %v", err)
		}
	}
	readIndex := uint64(0)
	if len(n3.readStates) > 0 {
		readIndex = n3.readStates[len(n3.readStates)-1].Index
	}

	assurance6Emit(t, map[string]any{
		"scenario":                            scenario,
		"event":                               "e_forwarded_read_state",
		"step":                                "requester-consumes-the-answer",
		"node":                                3,
		"answer_type":                         answerType,
		"answer_to":                           answerTo,
		"answer_index":                        answerIndex,
		"read_states":                         len(n3.readStates),
		"read_index":                          readIndex,
		"other_committed_index":               otherCommitted,
		"read_index_at_least_other_committed": readIndex >= otherCommitted,
		"removed_leader_state":                n1.state.String(),
		"removed_leader_committed_index":      n1.raftLog.committed,
	})

	// Control: the node that is the configuration's voter answers its own read
	// with an index that covers its commit index.
	if err := n2.Step(&pb.Message{
		From:    new(uint64(2)),
		To:      new(uint64(2)),
		Type:    pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("C")}},
	}); err != nil {
		t.Fatalf("read index on the actual leader: %v", err)
	}
	leaderReadIndex := uint64(0)
	if len(n2.readStates) > 0 {
		leaderReadIndex = n2.readStates[len(n2.readStates)-1].Index
	}
	assurance6Emit(t, map[string]any{
		"scenario":                          scenario,
		"event":                             "e_leader_control",
		"step":                              "actual-leader-answers-its-own-read",
		"node":                              2,
		"state":                             n2.state.String(),
		"term":                              n2.Term,
		"singleton":                         n2.trk.IsSingleton(),
		"is_voter":                          assurance6IsVoter(n2),
		"committed_index":                   otherCommitted,
		"read_states":                       len(n2.readStates),
		"read_index":                        leaderReadIndex,
		"read_index_at_least_own_committed": leaderReadIndex >= otherCommitted,
	})

	// One heartbeat interval is enough for the removed leader to learn of the
	// new term and leave the leader state.
	ticks := 0
	for n1.state == StateLeader && ticks < 5*n1.heartbeatTimeout {
		n1.tick()
		ticks++
		nt.send(n1.readMessages()...)
	}
	assurance6Emit(t, map[string]any{
		"scenario":                       scenario,
		"event":                          "e_stepdown",
		"step":                           "stepdown-after-heartbeat",
		"node":                           1,
		"state":                          n1.state.String(),
		"term":                           n1.Term,
		"lead":                           n1.lead,
		"ticks_until_stepdown":           ticks,
		"removed_leader_committed_index": n1.raftLog.committed,
		"other_committed_index":          otherCommitted,
	})

	// After the window closed the requester issues the read again. Whatever
	// comes back must not be an index below what the actual leader committed.
	before := len(n3.readStates)
	if err := n3.Step(&pb.Message{
		From:    new(uint64(3)),
		To:      new(uint64(3)),
		Type:    pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("R2")}},
	}); err != nil {
		t.Fatalf("second read index on the requester: %v", err)
	}
	held2 := n3.readMessages()
	answers2 := 0
	for _, heldMsg := range held2 {
		if err := n1.Step(heldMsg); err != nil {
			t.Fatalf("step second held request: %v", err)
		}
	}
	for _, answer := range n1.readMessages() {
		answers2++
		if err := n3.Step(answer); err != nil {
			t.Fatalf("step second answer: %v", err)
		}
	}
	retryIndex := uint64(0)
	if len(n3.readStates) > before {
		retryIndex = n3.readStates[len(n3.readStates)-1].Index
	}
	answered := len(n3.readStates) > before
	assurance6Emit(t, map[string]any{
		"scenario":                  scenario,
		"event":                     "e_after_stepdown_read_state",
		"step":                      "requester-asks-again-after-stepdown",
		"node":                      3,
		"read_states_before":        before,
		"read_states":               len(n3.readStates),
		"new_read_states":           len(n3.readStates) - before,
		"read_answered":             answered,
		"forwarded_again":           len(held2) > 0,
		"answers_from_removed_node": answers2,
		"read_index":                retryIndex,
		"other_committed_index":     otherCommitted,
		"removed_leader_state":      n1.state.String(),
		"removed_leader_lead":       n1.lead,
		// The read is either refused or answered with an index that covers what
		// the actual leader has committed.
		"safe_outcome": !answered || retryIndex >= otherCommitted,
	})
}
