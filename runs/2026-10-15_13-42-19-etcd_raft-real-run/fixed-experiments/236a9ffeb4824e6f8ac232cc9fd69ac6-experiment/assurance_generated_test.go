package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	"google.golang.org/protobuf/proto"

	pb "go.etcd.io/raft/v3/raftpb"
)

// assuranceEmit prints one machine-readable observation. Every event carries the
// scenario name so that observations of the two configuration-change variants
// stay distinguishable.
func assuranceEmit(t *testing.T, ev map[string]any) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("cannot marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// assuranceNet is a transport that preserves raft's message semantics (each
// message is Stepped by its target and the resulting messages are delivered in
// order) and adds the fault model this scenario needs: a node can be
// unreachable, and individual messages can be delayed in the network.
type assuranceNet struct {
	peers    map[uint64]*raft
	isolated map[uint64]bool
	hold     func(m *pb.Message) bool
	held     []*pb.Message
}

func (nt *assuranceNet) deliver(msgs ...*pb.Message) []*pb.Message {
	var delivered []*pb.Message
	for len(msgs) > 0 {
		m := msgs[0]
		msgs = msgs[1:]
		if nt.isolated[m.GetTo()] || nt.isolated[m.GetFrom()] {
			continue
		}
		if nt.hold != nil && nt.hold(m) {
			nt.held = append(nt.held, m)
			continue
		}
		p := nt.peers[m.GetTo()]
		if p == nil {
			continue
		}
		delivered = append(delivered, m)
		_ = p.Step(m)
		msgs = append(msgs, p.readMessages()...)
	}
	return delivered
}

func assuranceTypes(msgs []*pb.Message) []string {
	out := make([]string, 0, len(msgs))
	for _, m := range msgs {
		out = append(out, m.GetType().String())
	}
	return out
}

// assuranceEntries returns ten entries of term 1. Entry 10 is the supplied
// configuration change; entries 1..9 are ordinary entries.
func assuranceEntries(t *testing.T, cc pb.ConfChangeI) []*pb.Entry {
	t.Helper()
	typ, data, err := pb.MarshalConfChange(cc)
	if err != nil {
		t.Fatalf("cannot marshal conf change: %v", err)
	}
	ents := make([]*pb.Entry, 10)
	for i := 0; i < 9; i++ {
		ents[i] = &pb.Entry{Term: new(uint64(1)), Index: new(uint64(i + 1)), Data: []byte("payload")}
	}
	ents[9] = &pb.Entry{Term: new(uint64(1)), Index: new(uint64(10)), Type: typ.Enum(), Data: data}
	return ents
}

// assuranceNewNode bootstraps one node from a ConfState-only snapshot (the
// application-level bootstrap path), appends the committed entries up to index
// 10 and persists a HardState that commits index 10. The applied index is
// reported as 10 while the application's ApplyConfChange for the committed
// change at index 10 is still pending, which the Node interface allows: an
// application may call Advance while it is still applying the entries of a
// previous Ready.
func assuranceNewNode(t *testing.T, id uint64, cs *pb.ConfState, ents []*pb.Entry) *raft {
	t.Helper()
	s := newTestMemoryStorage()
	if err := s.ApplySnapshot(&pb.Snapshot{
		Metadata: &pb.SnapshotMetadata{ConfState: proto.Clone(cs).(*pb.ConfState)},
	}); err != nil {
		t.Fatalf("bootstrap snapshot: %v", err)
	}
	if err := s.Append(ents); err != nil {
		t.Fatalf("append entries: %v", err)
	}
	if err := s.SetHardState(&pb.HardState{Term: new(uint64(1)), Commit: new(uint64(10))}); err != nil {
		t.Fatalf("set hard state: %v", err)
	}
	cfg := newTestConfig(id, 10, 1, s)
	cfg.Applied = 10
	return newRaft(cfg)
}

func assuranceCommittedEntryInCurrentTerm(r *raft) (term uint64, ok bool) {
	t, err := r.raftLog.term(r.raftLog.committed)
	if err != nil {
		return 0, false
	}
	return t, t == r.Term
}

func assuranceDutyState(r *raft) map[string]any {
	t, inTerm := assuranceCommittedEntryInCurrentTerm(r)
	st := map[string]any{
		"committed_index":     r.raftLog.committed,
		"committed_entry_term": t,
		"leader_term":         r.Term,
		"last_index":          r.raftLog.lastIndex(),
		"applied_index":       r.raftLog.applied,
		"term_has_commit":     inTerm,
		"pending_reads":       len(r.pendingReadIndexMessages),
		"unconfirmed_reads":   len(r.readOnly.unconfirmedReads),
		"read_states":         len(r.readStates),
		"config":              r.trk.Config.String(),
	}
	return st
}

type assuranceCase struct {
	name      string
	confState *pb.ConfState
	change    pb.ConfChangeI
}

// TestAssurancePostponedReadIndexAcrossConfigCommit observes whether a read
// index request that the leader postponed (because it had not committed an
// entry in its term yet) is released when the leader's first commit of the term
// is performed inside switchToConfig while the application applies a committed
// configuration change. The two cases differ only in how the applied change
// makes the leader's term entry committable: removing an unreachable voter, and
// leaving a joint configuration whose outgoing half contains an unreachable
// voter.
func TestAssurancePostponedReadIndexAcrossConfigCommit(t *testing.T) {
	cases := []assuranceCase{
		{
			name:      "apply-removal-of-unreachable-voter-4",
			confState: &pb.ConfState{Voters: []uint64{1, 2, 3, 4}},
			change: &pb.ConfChangeV2{Changes: []*pb.ConfChangeSingle{
				{Type: pb.ConfChangeRemoveNode.Enum(), NodeId: new(uint64(4))},
			}},
		},
		{
			name:      "apply-leave-joint-config",
			confState: &pb.ConfState{Voters: []uint64{1, 2, 3}, VotersOutgoing: []uint64{1, 2, 3, 4}},
			change:    &pb.ConfChangeV2{},
		},
	}
	for _, c := range cases {
		assuranceRunCase(t, c)
	}
}

func assuranceRunCase(t *testing.T, c assuranceCase) {
	ents := assuranceEntries(t, c.change)
	peers := map[uint64]*raft{}
	for id := uint64(1); id <= 4; id++ {
		peers[id] = assuranceNewNode(t, id, c.confState, ents)
	}
	n1 := peers[1]

	assuranceEmit(t, map[string]any{
		"event":                 "setup",
		"case":                  c.name,
		"node":                  1,
		"bootstrap_conf_state":  DescribeConfState(c.confState),
		"last_log_entry_type":   ents[9].GetType().String(),
		"last_log_entry_index":  ents[9].GetIndex(),
		"persisted_commit":      n1.raftLog.committed,
		"persisted_commit_term": 1,
		"applied_index":         n1.raftLog.applied,
		"config":                n1.trk.Config.String(),
	})

	nt := &assuranceNet{peers: peers, isolated: map[uint64]bool{4: true}}
	// Voter 3 votes but its append acknowledgements are delayed in the network:
	// the leader cannot yet commit anything under the configuration that is
	// still active in its tracker.
	nt.hold = func(m *pb.Message) bool {
		return m.GetType() == pb.MsgAppResp && m.GetFrom() == 3
	}

	// Elect node 1 (term 2). Voters 1, 2 and 3 are reachable, voter 4 is not.
	nt.deliver(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgHup.Enum()})

	ev := map[string]any{"event": "election", "case": c.name, "node": 1, "state": n1.state.String()}
	for k, v := range assuranceDutyState(n1) {
		ev[k] = v
	}
	ev["match"] = map[uint64]uint64{
		1: n1.trk.Progress[1].Match,
		2: n1.trk.Progress[2].Match,
		3: n1.trk.Progress[3].Match,
		4: n1.trk.Progress[4].Match,
	}
	ev["held_messages"] = len(nt.held)
	assuranceEmit(t, ev)

	// A linearizable read request reaches the leader before it has committed an
	// entry in its term, so the leader postpones it.
	nt.deliver(&pb.Message{
		From:    new(uint64(1)),
		To:      new(uint64(1)),
		Type:    pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("A")}},
	})
	ev = map[string]any{
		"event":               "readindex_received",
		"case":                c.name,
		"node":                1,
		"request_ctx":         "A",
		"committed_at_receipt": n1.raftLog.committed,
		"stashed":             len(n1.pendingReadIndexMessages) == 1,
	}
	for k, v := range assuranceDutyState(n1) {
		ev[k] = v
	}
	assuranceEmit(t, ev)

	// The application applies the committed configuration change at index 10
	// (the change is taken from the log entry it applies).
	entry, err := n1.raftLog.slice(10, 11, noLimit)
	if err != nil || len(entry) != 1 {
		t.Fatalf("cannot read entry 10: %v", err)
	}
	change := &pb.ConfChangeV2{}
	if err := proto.Unmarshal(entry[0].GetData(), change); err != nil {
		t.Fatalf("cannot unmarshal applied change: %v", err)
	}
	committedBefore := n1.raftLog.committed
	n1.applyConfChange(change)
	emitted := nt.deliver(n1.readMessages()...)

	ev = map[string]any{
		"event":             "confchange_applied",
		"case":              c.name,
		"node":              1,
		"applied_change":    DescribeConfChange(change),
		"committed_before":  committedBefore,
		"messages_emitted":  assuranceTypes(emitted),
		"readindex_responses_emitted": func() int {
			n := 0
			for _, m := range emitted {
				if m.GetType() == pb.MsgReadIndexResp {
					n++
				}
			}
			return n
		}(),
	}
	for k, v := range assuranceDutyState(n1) {
		ev[k] = v
	}
	assuranceEmit(t, ev)

	// The delayed acknowledgement of the configuration that is no longer active
	// reaches the leader now (the delay is removed for this delivery).
	nt.hold = nil
	held := nt.held
	nt.held = nil
	rt := nt.deliver(held...)
	ev = map[string]any{
		"event":            "delayed_ack_delivered",
		"case":             c.name,
		"node":             1,
		"delayed_from":     3,
		"delivered_types":  assuranceTypes(rt),
		"match_3":          n1.trk.Progress[3].Match,
	}
	for k, v := range assuranceDutyState(n1) {
		ev[k] = v
	}
	assuranceEmit(t, ev)

	// A periodic heartbeat round: the postponed request is not part of
	// readOnly.unconfirmedReads, so the heartbeats carry no read context and the
	// returning acknowledgements cannot release it.
	n1.tick()
	emitted = nt.deliver(n1.readMessages()...)
	heartbeats, ctxLen := 0, -1
	for _, m := range emitted {
		if m.GetType() == pb.MsgHeartbeat {
			heartbeats++
			ctxLen = len(m.GetContext())
		}
	}
	ev = map[string]any{
		"event":               "heartbeat_round",
		"case":                c.name,
		"node":                1,
		"heartbeats_sent":     heartbeats,
		"heartbeat_ctx_len":   ctxLen,
		"delivered_types":     assuranceTypes(emitted),
	}
	for k, v := range assuranceDutyState(n1) {
		ev[k] = v
	}
	assuranceEmit(t, ev)

	// An unrelated proposal is committed by the (now active) configuration. This
	// is the only path that releases the postponed request.
	committedBeforeProposal := n1.raftLog.committed
	if err := n1.Step(&pb.Message{
		From:    new(uint64(1)),
		To:      new(uint64(1)),
		Type:    pb.MsgProp.Enum(),
		Entries: []*pb.Entry{{Data: []byte("unrelated")}},
	}); err != nil {
		t.Fatalf("propose: %v", err)
	}
	emitted = nt.deliver(n1.readMessages()...)
	ev = map[string]any{
		"event":            "unrelated_commit",
		"case":             c.name,
		"node":             1,
		"committed_before": committedBeforeProposal,
		"delivered_types":  assuranceTypes(emitted),
	}
	for k, v := range assuranceDutyState(n1) {
		ev[k] = v
	}
	if len(n1.readStates) > 0 {
		ev["released_request_ctx"] = string(n1.readStates[0].RequestCtx)
		ev["released_read_index"] = n1.readStates[0].Index
	}
	assuranceEmit(t, ev)

	assuranceEmit(t, map[string]any{
		"event": "case_end",
		"case":  c.name,
		"node":  1,
	})
}

// TestAssuranceForwardedReadIndexAcrossConfigCommit is the forwarded-completion
// variant of the postponed-read scenario: the client's read reaches follower 2,
// which forwards it to leader 1, so the answer owed by the leader is a
// MsgReadIndexResp rather than a local ReadState.
func TestAssuranceForwardedReadIndexAcrossConfigCommit(t *testing.T) {
	const name = "remove-voter-4-forwarded-read"
	change := &pb.ConfChangeV2{Changes: []*pb.ConfChangeSingle{
		{Type: pb.ConfChangeRemoveNode.Enum(), NodeId: new(uint64(4))},
	}}
	ents := assuranceEntries(t, change)
	confState := &pb.ConfState{Voters: []uint64{1, 2, 3, 4}}
	peers := map[uint64]*raft{}
	for id := uint64(1); id <= 4; id++ {
		peers[id] = assuranceNewNode(t, id, confState, ents)
	}
	n1 := peers[1]

	assuranceEmit(t, map[string]any{
		"event":                "fwd_setup",
		"case":                 name,
		"node":                 1,
		"bootstrap_conf_state": DescribeConfState(confState),
		"applied_index":        n1.raftLog.applied,
		"persisted_commit":     n1.raftLog.committed,
		"config":               n1.trk.Config.String(),
	})

	nt := &assuranceNet{peers: peers, isolated: map[uint64]bool{4: true}}
	nt.hold = func(m *pb.Message) bool {
		return m.GetType() == pb.MsgAppResp && m.GetFrom() == 3
	}
	nt.deliver(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgHup.Enum()})
	ev := map[string]any{"event": "fwd_election", "case": name, "node": 1, "state": n1.state.String()}
	for k, v := range assuranceDutyState(n1) {
		ev[k] = v
	}
	assuranceEmit(t, ev)

	// The client sends its read index request to follower 2, which forwards it
	// to the leader it knows.
	if err := peers[2].Step(&pb.Message{
		Type:    pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("A")}},
	}); err != nil {
		t.Fatalf("follower read index: %v", err)
	}
	fwd := nt.deliver(peers[2].readMessages()...)
	assuranceEmit(t, map[string]any{
		"event":                 "fwd_readindex_forwarded",
		"case":                  name,
		"node":                  2,
		"state":                 peers[2].state.String(),
		"known_leader":          peers[2].lead,
		"forwarded_to_leader":   peers[2].lead == 1,
		"node2_read_states":     len(peers[2].readStates),
		"messages_emitted":      assuranceTypes(fwd),
	})
	ev = map[string]any{
		"event":             "fwd_readindex_stashed",
		"case":              name,
		"node":              1,
		"pending_reads":     len(n1.pendingReadIndexMessages),
		"node2_read_states": len(peers[2].readStates),
	}
	for k, v := range assuranceDutyState(n1) {
		ev[k] = v
	}
	assuranceEmit(t, ev)

	entry, err := n1.raftLog.slice(10, 11, noLimit)
	if err != nil || len(entry) != 1 {
		t.Fatalf("cannot read entry 10: %v", err)
	}
	applied := &pb.ConfChangeV2{}
	if err := proto.Unmarshal(entry[0].GetData(), applied); err != nil {
		t.Fatalf("cannot unmarshal applied change: %v", err)
	}
	committedBefore := n1.raftLog.committed
	n1.applyConfChange(applied)
	emitted := nt.deliver(n1.readMessages()...)
	responses := 0
	for _, m := range emitted {
		if m.GetType() == pb.MsgReadIndexResp {
			responses++
		}
	}
	ev = map[string]any{
		"event":                    "fwd_confchange_applied",
		"case":                     name,
		"node":                     1,
		"committed_before":         committedBefore,
		"messages_emitted":         assuranceTypes(emitted),
		"readindex_responses_emitted": responses,
		"node2_read_states":        len(peers[2].readStates),
	}
	for k, v := range assuranceDutyState(n1) {
		ev[k] = v
	}
	assuranceEmit(t, ev)

	nt.hold = nil
	held := nt.held
	nt.held = nil
	nt.deliver(held...)
	ev = map[string]any{
		"event":             "fwd_delayed_ack_delivered",
		"case":              name,
		"node":              1,
		"node2_read_states": len(peers[2].readStates),
	}
	for k, v := range assuranceDutyState(n1) {
		ev[k] = v
	}
	assuranceEmit(t, ev)

	n1.tick()
	nt.deliver(n1.readMessages()...)
	ev = map[string]any{
		"event":             "fwd_heartbeat_round",
		"case":              name,
		"node":              1,
		"node2_read_states": len(peers[2].readStates),
	}
	for k, v := range assuranceDutyState(n1) {
		ev[k] = v
	}
	assuranceEmit(t, ev)

	committedBeforeProposal := n1.raftLog.committed
	if err := n1.Step(&pb.Message{
		From:    new(uint64(1)),
		To:      new(uint64(1)),
		Type:    pb.MsgProp.Enum(),
		Entries: []*pb.Entry{{Data: []byte("unrelated")}},
	}); err != nil {
		t.Fatalf("propose: %v", err)
	}
	emitted = nt.deliver(n1.readMessages()...)
	responses = 0
	for _, m := range emitted {
		if m.GetType() == pb.MsgReadIndexResp {
			responses++
		}
	}
	ev = map[string]any{
		"event":                    "fwd_unrelated_commit",
		"case":                     name,
		"node":                     1,
		"committed_before":         committedBeforeProposal,
		"readindex_responses_emitted": responses,
		"node2_read_states":        len(peers[2].readStates),
	}
	for k, v := range assuranceDutyState(n1) {
		ev[k] = v
	}
	if len(peers[2].readStates) > 0 {
		last := peers[2].readStates[len(peers[2].readStates)-1]
		ev["node2_read_index"] = last.Index
		ev["node2_request_ctx"] = string(last.RequestCtx)
	}
	assuranceEmit(t, ev)
}
