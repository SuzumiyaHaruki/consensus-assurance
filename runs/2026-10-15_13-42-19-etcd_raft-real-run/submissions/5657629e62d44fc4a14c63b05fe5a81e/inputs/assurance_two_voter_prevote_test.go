package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	pb "go.etcd.io/raft/v3/raftpb"
)

func assurance7Emit(t *testing.T, ev map[string]any) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("cannot marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func assurance7IsVoter(r *raft) bool {
	_, ok := r.trk.Voters.IDs()[r.id]
	return ok
}

// TestAssuranceReadIndexFromRemovedLeaderTwoVoterRemainderWithPreVote observes
// what happens to a ReadIndex request that reaches a leader whose removal left
// a configuration with more than one voter, in the configuration in which only
// PreVote is enabled: the request cannot use the singleton shortcut, so the
// leader takes it into readOnly.unconfirmedReads and broadcasts heartbeats, and
// the receipt records whether the caller is ever answered or refused.
func TestAssuranceReadIndexFromRemovedLeaderTwoVoterRemainderWithPreVote(t *testing.T) {
	const scenario = "removed-two-voter-remainder-read-prevote"

	mk := func(id uint64) *raft {
		cfg := newTestConfig(id, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
		cfg.PreVote = true
		return newRaft(cfg)
	}
	n1, n2, n3 := mk(1), mk(2), mk(3)
	nt := newNetwork(n1, n2, n3)
	setRandomizedElectionTimeout(n2, n2.electionTimeout*10)
	setRandomizedElectionTimeout(n3, n3.electionTimeout*10)

	assurance7Emit(t, map[string]any{
		"scenario":       scenario,
		"event":          "c_setup",
		"step":           "setup",
		"cluster":        "voters=(1 2 3)",
		"prevote":        true,
		"heartbeat_tick": n1.heartbeatTimeout,
		"election_tick":  n1.electionTimeout,
	})

	nt.send(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgHup.Enum()})
	for _, n := range []*raft{n1, n2, n3} {
		nextEnts(n, n.raftLog.storage.(*MemoryStorage))
	}

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
	n3.applyConfChange(ccv2)
	for _, n := range []*raft{n1, n2, n3} {
		nextEnts(n, n.raftLog.storage.(*MemoryStorage))
	}

	assurance7Emit(t, map[string]any{
		"scenario":        scenario,
		"event":           "e_leader_removed",
		"step":            "leader-1-removed",
		"node":            1,
		"state":           n1.state.String(),
		"term":            n1.Term,
		"config":          n1.trk.Config.String(),
		"singleton":       n1.trk.IsSingleton(),
		"is_voter":        assurance7IsVoter(n1),
		"voter_count":     len(n1.trk.Voters.IDs()),
		"committed_index": n1.raftLog.committed,
	})

	// The two remaining voters elect node 2 and it commits a new entry.
	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgHup.Enum()})
	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgProp.Enum(),
		Entries: []*pb.Entry{{Data: []byte("w")}}})
	otherCommitted := n2.raftLog.committed

	assurance7Emit(t, map[string]any{
		"scenario":                       scenario,
		"event":                          "e_new_leader_committed",
		"step":                           "node-2-leads",
		"node":                           2,
		"state":                          n2.state.String(),
		"term":                           n2.Term,
		"config":                         n2.trk.Config.String(),
		"committed_index":                otherCommitted,
		"removed_leader_committed_index": n1.raftLog.committed,
		"removed_leader_state":           n1.state.String(),
		"actual_leader_ahead":            otherCommitted > n1.raftLog.committed,
	})

	// The application issues the read through the removed leader.
	if err := n1.Step(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("R")}}}); err != nil {
		t.Fatalf("read index: %v", err)
	}
	emitted := n1.readMessages()
	heartbeats := 0
	for _, msg := range emitted {
		if msg.GetType() == pb.MsgHeartbeat {
			heartbeats++
		}
	}
	assurance7Emit(t, map[string]any{
		"scenario":                        scenario,
		"event":                           "e_read_taken",
		"step":                            "read-via-removed-leader",
		"node":                            1,
		"state":                           n1.state.String(),
		"term":                            n1.Term,
		"singleton":                       n1.trk.IsSingleton(),
		"is_voter":                        assurance7IsVoter(n1),
		"state_is_leader":                 n1.state == StateLeader,
		"committed_entry_in_current_term": n1.committedEntryInCurrentTerm(),
		"read_states":                     len(n1.readStates),
		"pending_reads":                   len(n1.pendingReadIndexMessages),
		"unconfirmed_reads":               len(n1.readOnly.unconfirmedReads),
		"heartbeats_emitted":              heartbeats,
		"committed_index":                 n1.raftLog.committed,
		"other_committed_index":           otherCommitted,
		"read_pending_confirmation":       len(n1.readStates) == 0 && len(n1.readOnly.unconfirmedReads) == 1,
	})

	// One heartbeat interval is enough for the removed leader to learn of the
	// new term.
	ticks := 0
	for n1.state == StateLeader && ticks < 5*n1.heartbeatTimeout {
		n1.tick()
		ticks++
		nt.send(n1.readMessages()...)
	}
	assurance7Emit(t, map[string]any{
		"scenario":              scenario,
		"event":                 "e_stepdown",
		"step":                  "stepdown-after-heartbeat",
		"node":                  1,
		"state":                 n1.state.String(),
		"term":                  n1.Term,
		"lead":                  n1.lead,
		"ticks_until_stepdown":  ticks,
		"committed_index":       n1.raftLog.committed,
		"other_committed_index": otherCommitted,
	})

	// What the caller ends up with: no read state and no refusal.
	readStatesAfter := len(n1.readStates)
	pendingAfter := len(n1.pendingReadIndexMessages)
	unconfirmedAfter := len(n1.readOnly.unconfirmedReads)
	readIndexAfter := uint64(0)
	if readStatesAfter > 0 {
		readIndexAfter = n1.readStates[readStatesAfter-1].Index
	}
	assurance7Emit(t, map[string]any{
		"scenario":                scenario,
		"event":                   "e_after_stepdown_state",
		"step":                    "request-state-after-stepdown",
		"node":                    1,
		"state":                   n1.state.String(),
		"term":                    n1.Term,
		"read_states":             readStatesAfter,
		"read_answered":           readStatesAfter > 0,
		"read_index":              readIndexAfter,
		"stale_answer_handed_out": readStatesAfter > 0 && readIndexAfter < otherCommitted,
		"pending_reads":           pendingAfter,
		"unconfirmed_reads":       unconfirmedAfter,
		"request_still_pending":   pendingAfter > 0 || unconfirmedAfter > 0,
		"refused_to_caller":       false,
		"committed_index":         n1.raftLog.committed,
		"other_committed_index":   otherCommitted,
	})
}
