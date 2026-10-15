package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	pb "go.etcd.io/raft/v3/raftpb"
)

func assurance2Emit(t *testing.T, ev map[string]any) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("cannot marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func assurance2Types(msgs []*pb.Message) []string {
	out := make([]string, 0, len(msgs))
	for _, m := range msgs {
		out = append(out, m.GetType().String())
	}
	return out
}

func assurance2IsVoter(r *raft) bool {
	_, ok := r.trk.Voters.IDs()[r.id]
	return ok
}

// TestAssuranceReadIndexFromRemovedSingletonLeader observes what raft answers
// for a ReadIndex request that arrives at a node which the application removed
// from the configuration while it was leading (StepDownOnRemoval is false, the
// default), after the only remaining voter became leader of the reduced
// configuration and committed a new entry that the removed leader never sees.
func TestAssuranceReadIndexFromRemovedSingletonLeader(t *testing.T) {
	s1 := newTestMemoryStorage(withPeers(1, 2))
	s2 := newTestMemoryStorage(withPeers(1, 2))
	n1 := newTestRaft(1, 10, 1, s1)
	n2 := newTestRaft(2, 10, 1, s2)
	nt := newNetwork(n1, n2)
	setRandomizedElectionTimeout(n2, n2.electionTimeout*10)

	assurance2Emit(t, map[string]any{
		"scenario": "removed-singleton-leader-read",
		"event":                 "setup",
		"step":                  "setup",
		"cluster":               "voters=(1 2)",
		"step_down_on_removal":  false,
		"read_only_option":      "ReadOnlySafe",
		"checkquorum_and_prevote": false,
	})

	// Node 1 is elected leader of {1,2} and the application applies what is
	// committed (the new leader's empty entry) on both nodes.
	nt.send(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgHup.Enum()})
	nextEnts(n1, s1)
	nextEnts(n2, s2)

	// The application proposes removing node 1 - the leader - and then applies
	// the committed change on both nodes.
	cc := &pb.ConfChange{Type: pb.ConfChangeRemoveNode.Enum(), NodeId: new(uint64(1))}
	m, err := confChangeToMsg(cc)
	if err != nil {
		t.Fatalf("conf change message: %v", err)
	}
	// A proposal is a local message: address it to the proposing node so that
	// the transport delivers it as the application's ProposeConfChange would.
	m.From, m.To = new(uint64(1)), new(uint64(1))
	nt.send(m)
	ccv2 := cc.AsV2()
	n1.applyConfChange(ccv2)
	n2.applyConfChange(ccv2)
	nextEnts(n1, s1)
	nextEnts(n2, s2)

	assurance2Emit(t, map[string]any{
		"scenario": "removed-singleton-leader-read",
		"event":           "leader_removed",
		"step":            "leader-1-removed",
		"node":            1,
		"state":           n1.state.String(),
		"term":            n1.Term,
		"config":          n1.trk.Config.String(),
		"singleton":       n1.trk.IsSingleton(),
		"is_voter":        assurance2IsVoter(n1),
		"progress_size":   len(n1.trk.Progress),
		"committed_index": n1.raftLog.committed,
		"last_index":      n1.raftLog.lastIndex(),
	})

	// The remaining voter becomes leader of {2} and commits a new entry.
	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgHup.Enum()})
	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgProp.Enum(),
		Entries: []*pb.Entry{{Data: []byte("w")}}})
	n2Committed := n2.raftLog.committed
	n1Committed := n1.raftLog.committed

	assurance2Emit(t, map[string]any{
		"scenario": "removed-singleton-leader-read",
		"event":                        "new_leader_committed",
		"step":                         "node-2-leads",
		"node":                         2,
		"state":                        n2.state.String(),
		"term":                         n2.Term,
		"config":                       n2.trk.Config.String(),
		"committed_index":              n2Committed,
		"last_index":                   n2.raftLog.lastIndex(),
		"removed_leader_committed_index": n1Committed,
		"removed_leader_term":          n1.Term,
		"removed_leader_state":         n1.state.String(),
		"actual_leader_ahead":          n2Committed > n1Committed,
	})

	// A client issues a linearizable read through the removed leader, after the
	// new leader has committed the entry above.
	if err := n1.Step(&pb.Message{
		From:    new(uint64(1)),
		To:      new(uint64(1)),
		Type:    pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("R")}},
	}); err != nil {
		t.Fatalf("read index: %v", err)
	}
	emitted := n1.readMessages()
	nt.send(emitted...)
	ev := map[string]any{
		"scenario": "removed-singleton-leader-read",
		"event":          "stale_read_answered",
		"step":           "read-via-removed-leader",
		"node":           1,
		"request_ctx":    "R",
		"read_states":    len(n1.readStates),
		"pending_reads":  len(n1.pendingReadIndexMessages),
		"unconfirmed_reads": len(n1.readOnly.unconfirmedReads),
		"heartbeats_emitted": func() int {
			n := 0
			for _, m := range emitted {
				if m.GetType() == pb.MsgHeartbeat {
					n++
				}
			}
			return n
		}(),
		"messages_emitted":          assurance2Types(emitted),
		"singleton":                 n1.trk.IsSingleton(),
		"is_voter":                  assurance2IsVoter(n1),
		"term":                      n1.Term,
		"state":                     n1.state.String(),
		"committed_index":           n1.raftLog.committed,
		"other_committed_index":     n2.raftLog.committed,
	}
	if len(n1.readStates) > 0 {
		ev["read_index"] = n1.readStates[len(n1.readStates)-1].Index
		ev["read_index_ctx"] = string(n1.readStates[len(n1.readStates)-1].RequestCtx)
		ev["read_index_at_least_other_committed"] = n1.readStates[len(n1.readStates)-1].Index >= n2.raftLog.committed
		ev["first_read_index"] = n1.readStates[0].Index
	}
	assurance2Emit(t, ev)

	// Control: the same read issued through the node that is the actual leader
	// of the remaining configuration.
	if err := n2.Step(&pb.Message{
		From:    new(uint64(2)),
		To:      new(uint64(2)),
		Type:    pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("R")}},
	}); err != nil {
		t.Fatalf("control read index: %v", err)
	}
	emitted2 := n2.readMessages()
	nt.send(emitted2...)
	ev = map[string]any{
		"scenario": "removed-singleton-leader-read",
		"event":             "control_read_actual_leader",
		"step":              "read-via-actual-leader",
		"node":              2,
		"request_ctx":       "R",
		"read_states":       len(n2.readStates),
		"own_committed_index": n2.raftLog.committed,
		"messages_emitted":  assurance2Types(emitted2),
		"singleton":         n2.trk.IsSingleton(),
		"term":              n2.Term,
		"state":             n2.state.String(),
	}
	if len(n2.readStates) > 0 {
		ev["read_index"] = n2.readStates[len(n2.readStates)-1].Index
		ev["read_index_at_least_own_committed"] = n2.readStates[len(n2.readStates)-1].Index >= n2.raftLog.committed
	}
	assurance2Emit(t, ev)

	// Give the removed leader three heartbeat intervals and deliver everything
	// it emits; nothing in the current configuration talks back to it.
	heartbeats := 0
	for i := 0; i < 3; i++ {
		n1.tick()
		out := n1.readMessages()
		for _, msg := range out {
			if msg.GetType() == pb.MsgHeartbeat {
				heartbeats++
			}
		}
		nt.send(out...)
	}
	if err := n1.Step(&pb.Message{
		From:    new(uint64(1)),
		To:      new(uint64(1)),
		Type:    pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("R2")}},
	}); err != nil {
		t.Fatalf("second read index: %v", err)
	}
	out := n1.readMessages()
	nt.send(out...)
	ev = map[string]any{
		"scenario": "removed-singleton-leader-read",
		"event":                      "second_stale_read",
		"step":                       "read-via-removed-leader-after-heartbeats",
		"node":                       1,
		"request_ctx":                "R2",
		"read_states":                len(n1.readStates),
		"heartbeats_sent":            heartbeats,
		"replies_to_removed_leader":  0,
		"term":                       n1.Term,
		"state":                      n1.state.String(),
		"committed_index":            n1.raftLog.committed,
		"other_committed_index":      n2.raftLog.committed,
		"messages_emitted":           assurance2Types(out),
	}
	if len(n1.readStates) >= 2 {
		last := n1.readStates[len(n1.readStates)-1].Index
		ev["read_index"] = last
		ev["same_stale_index_as_first"] = last == n1.readStates[0].Index
		ev["still_leader_and_same_term"] = n1.state == StateLeader && n1.Term == 1
	}
	assurance2Emit(t, ev)
}

// TestAssuranceReadIndexFromRemovedNonSingletonLeader is the control for the
// singleton shortcut: the same removal, but the reduced configuration has two
// voters, so tracker.IsSingleton() is false on the removed leader.
func TestAssuranceReadIndexFromRemovedNonSingletonLeader(t *testing.T) {
	s1 := newTestMemoryStorage(withPeers(1, 2, 3))
	s2 := newTestMemoryStorage(withPeers(1, 2, 3))
	s3 := newTestMemoryStorage(withPeers(1, 2, 3))
	n1 := newTestRaft(1, 10, 1, s1)
	n2 := newTestRaft(2, 10, 1, s2)
	n3 := newTestRaft(3, 10, 1, s3)
	nt := newNetwork(n1, n2, n3)
	setRandomizedElectionTimeout(n2, n2.electionTimeout*10)
	setRandomizedElectionTimeout(n3, n3.electionTimeout*10)

	assurance2Emit(t, map[string]any{
		"scenario": "removed-non-singleton-leader-read",
		"event":    "b_setup",
		"step":     "setup",
		"cluster":  "voters=(1 2 3)",
	})

	nt.send(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgHup.Enum()})
	nextEnts(n1, s1)
	nextEnts(n2, s2)
	nextEnts(n3, s3)

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
	nextEnts(n1, s1)
	nextEnts(n2, s2)
	nextEnts(n3, s3)

	assurance2Emit(t, map[string]any{
		"scenario":        "removed-non-singleton-leader-read",
		"event":           "b_leader_removed",
		"step":            "leader-1-removed",
		"node":            1,
		"state":           n1.state.String(),
		"term":            n1.Term,
		"config":          n1.trk.Config.String(),
		"singleton":       n1.trk.IsSingleton(),
		"is_voter":        assurance2IsVoter(n1),
		"committed_index": n1.raftLog.committed,
	})

	// The remaining voters elect node 2 in {2,3} and commit one entry.
	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgHup.Enum()})
	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgProp.Enum(),
		Entries: []*pb.Entry{{Data: []byte("w")}}})
	assurance2Emit(t, map[string]any{
		"scenario":                       "removed-non-singleton-leader-read",
		"event":                          "b_new_leader_committed",
		"step":                           "node-2-leads",
		"node":                           2,
		"state":                          n2.state.String(),
		"term":                           n2.Term,
		"config":                         n2.trk.Config.String(),
		"committed_index":                n2.raftLog.committed,
		"removed_leader_committed_index": n1.raftLog.committed,
		"removed_leader_term":            n1.Term,
		"removed_leader_state":           n1.state.String(),
		"actual_leader_ahead":            n2.raftLog.committed > n1.raftLog.committed,
	})

	// The same read request now reaches the removed leader, whose configuration
	// has two voters.
	if err := n1.Step(&pb.Message{
		From:    new(uint64(1)),
		To:      new(uint64(1)),
		Type:    pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("R")}},
	}); err != nil {
		t.Fatalf("read index: %v", err)
	}
	emitted := n1.readMessages()
	nt.send(emitted...)
	heartbeats, ctxLen := 0, -1
	for _, msg := range emitted {
		if msg.GetType() == pb.MsgHeartbeat {
			heartbeats++
			ctxLen = len(msg.GetContext())
		}
	}
	assurance2Emit(t, map[string]any{
		"scenario":            "removed-non-singleton-leader-read",
		"event":               "b_read_attempt",
		"step":                "read-via-removed-non-singleton-leader",
		"node":                1,
		"singleton":           n1.trk.IsSingleton(),
		"is_voter":            assurance2IsVoter(n1),
		"term":                n1.Term,
		"state":               n1.state.String(),
		"read_states":         len(n1.readStates),
		"read_answered":       len(n1.readStates) > 0,
		"pending_reads":       len(n1.pendingReadIndexMessages),
		"unconfirmed_reads":   len(n1.readOnly.unconfirmedReads),
		"heartbeats_emitted":  heartbeats,
		"heartbeat_ctx_len":   ctxLen,
		"messages_emitted":    assurance2Types(emitted),
		"committed_index":     n1.raftLog.committed,
		"other_committed_index": n2.raftLog.committed,
	})

	heartbeatsSent := 0
	for i := 0; i < 3; i++ {
		n1.tick()
		out := n1.readMessages()
		for _, msg := range out {
			if msg.GetType() == pb.MsgHeartbeat {
				heartbeatsSent++
			}
		}
		nt.send(out...)
	}
	assurance2Emit(t, map[string]any{
		"scenario":           "removed-non-singleton-leader-read",
		"event":              "b_read_after_heartbeats",
		"step":               "read-attempt-after-heartbeats",
		"node":               1,
		"read_states":        len(n1.readStates),
		"read_answered":      len(n1.readStates) > 0,
		"unconfirmed_reads":  len(n1.readOnly.unconfirmedReads),
		"pending_reads":      len(n1.pendingReadIndexMessages),
		"heartbeats_sent":    heartbeatsSent,
		"replies_to_removed_leader": 0,
		"term":               n1.Term,
		"state":              n1.state.String(),
		"committed_index":    n1.raftLog.committed,
		"other_committed_index": n2.raftLog.committed,
	})
}

// TestAssuranceReadIndexFromRemovedLeaderWithCheckQuorum measures how long the
// removed leader keeps answering reads when the quorum check is enabled: the
// same removal and read as the first scenario, but Config.CheckQuorum is true.
func TestAssuranceReadIndexFromRemovedLeaderWithCheckQuorum(t *testing.T) {
	mk := func(id uint64) *raft {
		s := newTestMemoryStorage(withPeers(1, 2))
		cfg := newTestConfig(id, 10, 1, s)
		cfg.CheckQuorum = true
		return newRaft(cfg)
	}
	n1, n2 := mk(1), mk(2)
	nt := newNetwork(n1, n2)
	setRandomizedElectionTimeout(n2, n2.electionTimeout*10)

	assurance2Emit(t, map[string]any{
		"scenario":     "removed-singleton-leader-read-checkquorum",
		"event":        "c_setup",
		"step":         "setup",
		"cluster":      "voters=(1 2)",
		"checkquorum":  true,
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

	assurance2Emit(t, map[string]any{
		"scenario":        "removed-singleton-leader-read-checkquorum",
		"event":           "c_leader_removed",
		"step":            "leader-1-removed",
		"node":            1,
		"state":           n1.state.String(),
		"term":            n1.Term,
		"config":          n1.trk.Config.String(),
		"singleton":       n1.trk.IsSingleton(),
		"is_voter":        assurance2IsVoter(n1),
		"committed_index": n1.raftLog.committed,
	})

	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgHup.Enum()})
	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgProp.Enum(),
		Entries: []*pb.Entry{{Data: []byte("w")}}})
	assurance2Emit(t, map[string]any{
		"scenario":                       "removed-singleton-leader-read-checkquorum",
		"event":                          "c_new_leader_committed",
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
		"scenario":              "removed-singleton-leader-read-checkquorum",
		"event":                 "c_read_before_stepdown",
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
	assurance2Emit(t, ev)

	// One heartbeat interval is enough for the current leader to answer the
	// removed leader's old-term heartbeat with its term.
	ticks := 0
	for n1.state == StateLeader && ticks < 5*n1.heartbeatTimeout {
		n1.tick()
		ticks++
		nt.send(n1.readMessages()...)
	}
	assurance2Emit(t, map[string]any{
		"scenario":          "removed-singleton-leader-read-checkquorum",
		"event":             "c_stepdown",
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
	assurance2Emit(t, map[string]any{
		"scenario":             "removed-singleton-leader-read-checkquorum",
		"event":                "c_read_after_stepdown",
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

// TestAssuranceReadIndexFromRemovedLeaderWithCheckQuorum measures how long the
// removed leader keeps answering reads when the quorum check is enabled: the
// same removal and read as the first scenario, but Config.CheckQuorum is true.
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

	assurance2Emit(t, map[string]any{
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

	assurance2Emit(t, map[string]any{
		"scenario":        "removed-singleton-leader-read-prevote",
		"event":           "e_leader_removed",
		"step":            "leader-1-removed",
		"node":            1,
		"state":           n1.state.String(),
		"term":            n1.Term,
		"config":          n1.trk.Config.String(),
		"singleton":       n1.trk.IsSingleton(),
		"is_voter":        assurance2IsVoter(n1),
		"committed_index": n1.raftLog.committed,
	})

	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgHup.Enum()})
	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgProp.Enum(),
		Entries: []*pb.Entry{{Data: []byte("w")}}})
	assurance2Emit(t, map[string]any{
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
	assurance2Emit(t, ev)

	// One heartbeat interval is enough for the current leader to answer the
	// removed leader's old-term heartbeat with its term.
	ticks := 0
	for n1.state == StateLeader && ticks < 5*n1.heartbeatTimeout {
		n1.tick()
		ticks++
		nt.send(n1.readMessages()...)
	}
	assurance2Emit(t, map[string]any{
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
	assurance2Emit(t, map[string]any{
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
