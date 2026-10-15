package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	pb "go.etcd.io/raft/v3/raftpb"
)

func assurance5Emit(t *testing.T, ev map[string]any) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("cannot marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func assurance5Types(msgs []*pb.Message) []string {
	out := make([]string, 0, len(msgs))
	for _, m := range msgs {
		out = append(out, m.GetType().String())
	}
	return out
}

func assurance5IsVoter(r *raft) bool {
	_, ok := r.trk.Voters.IDs()[r.id]
	return ok
}

// TestAssuranceReadIndexFromRemovedSingletonLeader observes what raft answers
// for a ReadIndex request that arrives at a node which the application removed
// from the configuration while it was leading (StepDownOnRemoval is false, the
// default), after the only remaining voter became leader of the reduced
// configuration and committed a new entry that the removed leader never sees.
// TestAssuranceReadIndexFromRemovedLeaderWithPreVote observes the same removal and
// read as the CheckQuorum scenario with Config.PreVote set instead, so the receipt
// covers a configuration in which only the pre-vote option is enabled.
func TestAssuranceReadIndexFromRemovedLeaderWithPreVote(t *testing.T) {
	mk := func(id uint64) *raft {
		s := newTestMemoryStorage(withPeers(1, 2))
		cfg := newTestConfig(id, 10, 1, s)
		cfg.PreVote = true
		return newRaft(cfg)
	}
	n1, n2 := mk(1), mk(2)
	nt := newNetwork(n1, n2)
	setRandomizedElectionTimeout(n2, n2.electionTimeout*10)

	assurance5Emit(t, map[string]any{
		"scenario":     "removed-singleton-leader-read-prevote",
		"event":        "c_setup",
		"step":         "setup",
		"cluster":      "voters=(1 2)",
		"prevote": true,
		"heartbeat_tick": n1.heartbeatTimeout,
		"election_tick":  n1.electionTimeout,
	})

	nt.send(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgHup.Enum()})
	nextEnts(n1, n1.raftLog.storage.(*MemoryStorage))
	nextEnts(n2, n2.raftLog.storage.(*MemoryStorage))

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

	assurance5Emit(t, map[string]any{
		"scenario":        "removed-singleton-leader-read-prevote",
		"event":           "e_leader_removed",
		"step":            "leader-1-removed",
		"node":            1,
		"state":           n1.state.String(),
		"term":            n1.Term,
		"config":          n1.trk.Config.String(),
		"singleton":       n1.trk.IsSingleton(),
		"is_voter":        assurance5IsVoter(n1),
		"committed_index": n1.raftLog.committed,
	})

	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgHup.Enum()})
	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgProp.Enum(),
		Entries: []*pb.Entry{{Data: []byte("w")}}})
	assurance5Emit(t, map[string]any{
		"scenario":                       "removed-singleton-leader-read-prevote",
		"event":                          "e_new_leader_committed",
		"step":                           "node-2-leads",
		"node":                           2,
		"state":                          n2.state.String(),
		"term":                           n2.Term,
		"committed_index":                n2.raftLog.committed,
		"removed_leader_committed_index": n1.raftLog.committed,
		"removed_leader_state":           n1.state.String(),
		"actual_leader_ahead":            n2.raftLog.committed > n1.raftLog.committed,
	})

	// The read still arrives before the removed leader has sent anything to the
	// new leader, so the shortcut answers it exactly as without CheckQuorum.
	if err := n1.Step(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("R")}}}); err != nil {
		t.Fatalf("read index: %v", err)
	}
	emitted := n1.readMessages()
	nt.send(emitted...)
	ev := map[string]any{
		"scenario":              "removed-singleton-leader-read-prevote",
		"event":                 "e_read_before_stepdown",
		"step":                  "read-before-stepdown",
		"node":                  1,
		"read_states":           len(n1.readStates),
		"singleton":             n1.trk.IsSingleton(),
		"term":                  n1.Term,
		"state":                 n1.state.String(),
		"committed_index":       n1.raftLog.committed,
		"other_committed_index": n2.raftLog.committed,
	}
	if len(n1.readStates) > 0 {
		last := n1.readStates[len(n1.readStates)-1].Index
		ev["read_index"] = last
		ev["read_index_at_least_other_committed"] = last >= n2.raftLog.committed
	}
	assurance5Emit(t, ev)

	// One heartbeat interval is enough for the current leader to answer the
	// removed leader's old-term heartbeat with its term.
	ticks := 0
	for n1.state == StateLeader && ticks < 5*n1.heartbeatTimeout {
		n1.tick()
		ticks++
		nt.send(n1.readMessages()...)
	}
	assurance5Emit(t, map[string]any{
		"scenario":          "removed-singleton-leader-read-prevote",
		"event":             "e_stepdown",
		"step":              "stepdown-after-heartbeat",
		"node":              1,
		"state":             n1.state.String(),
		"term":              n1.Term,
		"lead":              n1.lead,
		"ticks_until_stepdown": ticks,
		"committed_index":   n1.raftLog.committed,
	})

	// A further read is not answered at all.
	before := len(n1.readStates)
	if err := n1.Step(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("R2")}}}); err != nil {
		t.Fatalf("second read index: %v", err)
	}
	nt.send(n1.readMessages()...)
	assurance5Emit(t, map[string]any{
		"scenario":             "removed-singleton-leader-read-prevote",
		"event":                "e_read_after_stepdown",
		"step":                 "read-after-stepdown",
		"node":                 1,
		"state":                n1.state.String(),
		"term":                 n1.Term,
		"lead":                 n1.lead,
		"read_states_before":   before,
		"read_states":          len(n1.readStates),
		"new_read_states":      len(n1.readStates) - before,
		"read_answered":        len(n1.readStates) > before,
		"committed_index":      n1.raftLog.committed,
		"other_committed_index": n2.raftLog.committed,
	})
}
