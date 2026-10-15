package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	pb "go.etcd.io/raft/v3/raftpb"
)

func assurance8Emit(t *testing.T, ev map[string]any) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("cannot marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func assurance8IsVoter(r *raft) bool {
	_, ok := r.trk.Voters.IDs()[r.id]
	return ok
}

// TestAssuranceReadIndexFromRemovedLeaderTwoVoterRemainderWithCheckQuorum observes
// what happens to a ReadIndex request that reaches a leader whose removal left
// a configuration with more than one voter, in the configuration in which only
// PreVote is enabled: the request cannot use the singleton shortcut, so the
// leader takes it into readOnly.unconfirmedReads and broadcasts heartbeats, and
// the receipt records whether the caller is ever answered or refused.
func TestAssuranceReadIndexFromRemovedLeaderTwoVoterRemainderWithCheckQuorum(t *testing.T) {
	const scenario = "removed-two-voter-remainder-read-checkquorum"

	mk := func(id uint64) *raft {
		cfg := newTestConfig(id, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
		cfg.CheckQuorum = true
		return newRaft(cfg)
	}
	n1, n2, n3 := mk(1), mk(2), mk(3)
	nt := newNetwork(n1, n2, n3)
	setRandomizedElectionTimeout(n2, n2.electionTimeout*10)
	setRandomizedElectionTimeout(n3, n3.electionTimeout*10)

	assurance8Emit(t, map[string]any{
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

	assurance8Emit(t, map[string]any{
		"scenario":        scenario,
		"event":           "e_leader_removed",
		"step":            "leader-1-removed",
		"node":            1,
		"state":           n1.state.String(),
		"term":            n1.Term,
		"config":          n1.trk.Config.String(),
		"singleton":       n1.trk.IsSingleton(),
		"is_voter":        assurance8IsVoter(n1),
		"voter_count":     len(n1.trk.Voters.IDs()),
		"committed_index": n1.raftLog.committed,
	})

	// The removed leader keeps hearing from the voters it still counts, so it
	// keeps its lease: three heartbeat rounds pass without a new leader.
	rounds := 0
	for rounds < 3 {
		n1.tick()
		rounds++
		nt.send(n1.readMessages()...)
	}
	otherCommitted := n2.raftLog.committed

	assurance8Emit(t, map[string]any{
		"scenario":                       scenario,
		"event":                          "e_no_new_leader",
		"step":                           "no-replacement-after-heartbeat-rounds",
		"node":                           2,
		"state":                          n2.state.String(),
		"term":                           n2.Term,
		"config":                         n2.trk.Config.String(),
		"committed_index":                otherCommitted,
		"removed_leader_committed_index": n1.raftLog.committed,
		"removed_leader_state":           n1.state.String(),
		"removed_leader_term":            n1.Term,
		"node2_state":                    n2.state.String(),
		"node2_term":                     n2.Term,
		"node3_state":                    n3.state.String(),
		"node3_term":                     n3.Term,
		"heartbeat_rounds":               rounds,
		"new_leader_elected":             n2.state == StateLeader || n3.state == StateLeader,
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
	assurance8Emit(t, map[string]any{
		"scenario":                        scenario,
		"event":                           "e_read_taken",
		"step":                            "read-via-removed-leader",
		"node":                            1,
		"state":                           n1.state.String(),
		"term":                            n1.Term,
		"singleton":                       n1.trk.IsSingleton(),
		"is_voter":                        assurance8IsVoter(n1),
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

	// More rounds of the same heartbeats: the request is still unanswered.
	for i := 0; i < 3; i++ {
		n1.tick()
		nt.send(n1.readMessages()...)
	}
	assurance8Emit(t, map[string]any{
		"scenario":                       scenario,
		"event":                          "e_lease_after_rounds",
		"step":                           "state-after-further-heartbeat-rounds",
		"node":                           1,
		"state":                          n1.state.String(),
		"state_is_leader":                n1.state == StateLeader,
		"term":                           n1.Term,
		"lead":                           n1.lead,
		"read_states":                    len(n1.readStates),
		"read_answered":                  len(n1.readStates) > 0,
		"unconfirmed_reads":              len(n1.readOnly.unconfirmedReads),
		"pending_reads":                  len(n1.pendingReadIndexMessages),
		"removed_leader_committed_index": n1.raftLog.committed,
		"other_committed_index":          otherCommitted,
		"node2_state":                    n2.state.String(),
		"node2_term":                     n2.Term,
		"node3_state":                    n3.state.String(),
		"node3_term":                     n3.Term,
		"new_leader_elected":             n2.state == StateLeader || n3.state == StateLeader,
	})
}
