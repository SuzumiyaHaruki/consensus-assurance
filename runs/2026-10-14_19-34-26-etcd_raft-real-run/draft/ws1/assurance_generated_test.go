package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	"google.golang.org/protobuf/proto"

	pb "go.etcd.io/raft/v3/raftpb"
)

func caEvent(t *testing.T, kind string, fields map[string]any) {
	t.Helper()
	fields["event"] = kind
	b, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// mkConfChangeVoter builds a voter (id=1) whose storage holds entries [1]=normal,
// [2]=entry of the requested type at term 1, a HardState committing index 2, and a
// Config that has applied only index 1 (so applied < committed).
func mkConfChangeVoter(t *testing.T, secondIsConfChange bool) *raft {
	t.Helper()
	cc := &pb.ConfChangeV2{Changes: []*pb.ConfChangeSingle{{
		Type:   pb.ConfChangeAddNode.Enum(),
		NodeId: new(uint64(4)),
	}}}
	data, err := proto.Marshal(cc)
	if err != nil {
		t.Fatal(err)
	}
	ms := newTestMemoryStorage(withPeers(1, 2, 3))
	ents := []*pb.Entry{{Term: new(uint64(1)), Index: new(uint64(1))}}
	if secondIsConfChange {
		ents = append(ents, &pb.Entry{Term: new(uint64(1)), Index: new(uint64(2)), Type: pb.EntryConfChangeV2.Enum(), Data: data})
	} else {
		ents = append(ents, &pb.Entry{Term: new(uint64(1)), Index: new(uint64(2))})
	}
	if err := ms.Append(ents); err != nil {
		t.Fatal(err)
	}
	if err := ms.SetHardState(&pb.HardState{Term: new(uint64(1)), Vote: new(uint64(0)), Commit: new(uint64(2))}); err != nil {
		t.Fatal(err)
	}
	cfg := newTestConfig(1, 10, 1, ms)
	cfg.Applied = 1 // index 2 is committed but not applied
	return newRaft(cfg)
}

// TestAssuranceCampaignWithUnappliedConfChange probes whether a voter with a
// committed-but-unapplied conf change campaigns on MsgHup / MsgTimeoutNow, which
// voter set it would use, and whether it can campaign once application catches up.
func TestAssuranceCampaignWithUnappliedConfChange(t *testing.T) {
	voterIDs := func(msgs []*pb.Message, typ pb.MessageType) []uint64 {
		var ids []uint64
		for _, m := range msgs {
			if m.GetType() == typ {
				ids = append(ids, m.GetTo())
			}
		}
		return ids
	}

	// Case A: conf-change entry committed but unapplied.
	a := mkConfChangeVoter(t, true)
	caEvent(t, "unapplied_conf_change", map[string]any{
		"case":                "committed_unapplied_v2",
		"promotable":          a.promotable(),
		"has_unapplied":       a.hasUnappliedConfChanges(),
		"applied":             a.raftLog.applied,
		"committed":           a.raftLog.committed,
		"state_before":        a.state.String(),
		"voters_before":       a.trk.VoterNodes(),
		"entry2_type":         a.raftLog.allEntries()[1].GetType().String(),
		"cfg_applied_note":    "newRaft applied Config.Applied=1",
	})
	if err := a.Step(&pb.Message{From: new(uint64(1)), Type: pb.MsgHup.Enum()}); err != nil {
		t.Fatalf("hup: %v", err)
	}
	msgsA := a.readMessages()
	caEvent(t, "hup_with_unapplied", map[string]any{
		"state":        a.state.String(),
		"term":         a.Term,
		"vote":         a.Vote,
		"msgs":         len(msgsA),
		"vote_targets": voterIDs(msgsA, pb.MsgVote),
	})

	// Case A2: same node, leadership-transfer trigger (MsgTimeoutNow carries the term).
	a2 := mkConfChangeVoter(t, true)
	if err := a2.Step(&pb.Message{From: new(uint64(3)), Term: new(a2.Term), Type: pb.MsgTimeoutNow.Enum()}); err != nil {
		t.Fatalf("timeoutnow: %v", err)
	}
	msgsA2 := a2.readMessages()
	caEvent(t, "timeoutnow_with_unapplied", map[string]any{
		"state":        a2.state.String(),
		"term":         a2.Term,
		"msgs":         len(msgsA2),
		"vote_targets": voterIDs(msgsA2, pb.MsgVote),
	})

	// Case A3: same node after the application catches up (applied == committed).
	a3 := mkConfChangeVoter(t, true)
	a3.raftLog.appliedTo(2, 0)
	hasUnappliedAfter := a3.hasUnappliedConfChanges()
	if err := a3.Step(&pb.Message{From: new(uint64(1)), Type: pb.MsgHup.Enum()}); err != nil {
		t.Fatalf("hup after apply: %v", err)
	}
	msgsA3 := a3.readMessages()
	caEvent(t, "hup_after_apply", map[string]any{
		"has_unapplied": hasUnappliedAfter,
		"state":         a3.state.String(),
		"term":          a3.Term,
		"vote":          a3.Vote,
		"msgs":          len(msgsA3),
		"vote_targets":  voterIDs(msgsA3, pb.MsgVote),
	})

	// Control: no conf change in the log at the same position, applied < committed.
	c := mkConfChangeVoter(t, false)
	caEvent(t, "control_no_conf_change", map[string]any{
		"case":          "committed_unapplied_normal_entry",
		"promotable":    c.promotable(),
		"has_unapplied": c.hasUnappliedConfChanges(),
		"applied":       c.raftLog.applied,
		"committed":     c.raftLog.committed,
		"entry2_type":   c.raftLog.allEntries()[1].GetType().String(),
	})
	if err := c.Step(&pb.Message{From: new(uint64(1)), Type: pb.MsgHup.Enum()}); err != nil {
		t.Fatalf("control hup: %v", err)
	}
	msgsC := c.readMessages()
	caEvent(t, "control_hup", map[string]any{
		"state":        c.state.String(),
		"term":         c.Term,
		"vote":         c.Vote,
		"msgs":         len(msgsC),
		"vote_targets": voterIDs(msgsC, pb.MsgVote),
	})
}

// TestAssuranceReadIndexAcrossTermChange probes what happens to an admitted but
// unconfirmed ReadOnlySafe read request when the leader's term changes before any
// quorum acknowledgement arrives, and whether the confirmation path still works
// for a read admitted after the new leader has committed in its own term.
func TestAssuranceReadIndexAcrossTermChange(t *testing.T) {
	r1 := newTestRaft(1, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r2 := newTestRaft(2, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r3 := newTestRaft(3, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	nt := newNetwork(r1, r2, r3)

	nt.send(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgHup.Enum()})
	nt.send(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgProp.Enum(), Entries: []*pb.Entry{{Data: []byte("op")}}})
	caEvent(t, "stale_leader_state", map[string]any{
		"state":                    r1.state.String(),
		"term":                     r1.Term,
		"committed":                r1.raftLog.committed,
		"committed_entry_in_term":  r1.committedEntryInCurrentTerm(),
		"read_states":              len(r1.readStates),
		"unconfirmed_reads":        len(r1.readOnly.unconfirmedReads),
	})

	// Admit a read request on the leader with no heartbeat responses delivered, so
	// no quorum acknowledgement can exist and the request cannot be confirmed.
	if err := r1.Step(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgReadIndex.Enum(), Entries: []*pb.Entry{{Data: []byte("A")}}}); err != nil {
		t.Fatalf("readindex: %v", err)
	}
	caEvent(t, "read_admitted", map[string]any{
		"read_states":       len(r1.readStates),
		"unconfirmed_reads": len(r1.readOnly.unconfirmedReads),
		"confirmed_reads":   r1.readOnly.confirmedReads,
		"commit_at_entry":   r1.readOnly.unconfirmedReads[0].index,
		"term":              r1.Term,
	})

	// A real peer campaigns at a higher term; its MsgVote reaches r1.
	nt.send(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgHup.Enum()})
	var ctxA []byte
	for _, rs := range r1.readStates {
		if string(rs.RequestCtx) == "A" {
			ctxA = rs.RequestCtx
		}
	}
	caEvent(t, "after_term_change", map[string]any{
		"state":              r1.state.String(),
		"term":               r1.Term,
		"vote":               r1.Vote,
		"read_states":        len(r1.readStates),
		"ctx_A_completed":    ctxA != nil,
		"unconfirmed_reads":  len(r1.readOnly.unconfirmedReads),
		"confirmed_reads":    r1.readOnly.confirmedReads,
		"new_leader_state":   r2.state.String(),
		"new_leader_term":    r2.Term,
	})

	// Control: the new leader admits a read in its own term and a single peer ack
	// echoing the leader's heartbeat context confirms it.
	_ = r2.Step(&pb.Message{From: new(uint64(2)), To: new(uint64(2)), Type: pb.MsgReadIndex.Enum(), Entries: []*pb.Entry{{Data: []byte("B")}}})
	var hbCtx []byte
	for _, m := range r2.readMessages() {
		if m.GetType() == pb.MsgHeartbeat && m.GetTo() == 3 {
			hbCtx = m.GetContext()
		}
	}
	beforeAck := len(r2.readStates)
	if err := r2.Step(&pb.Message{From: new(uint64(3)), Term: new(r2.Term), Type: pb.MsgHeartbeatResp.Enum(), Context: hbCtx}); err != nil {
		t.Fatalf("heartbeatresp: %v", err)
	}
	var idxB uint64
	var gotB bool
	for _, rs := range r2.readStates {
		if string(rs.RequestCtx) == "B" {
			idxB, gotB = rs.Index, true
		}
	}
	caEvent(t, "new_leader_read_confirmed", map[string]any{
		"read_states_before_ack": beforeAck,
		"read_states_after_ack":  len(r2.readStates),
		"ctx_B_completed":        gotB,
		"index_B":                idxB,
		"commit_now":             r2.raftLog.committed,
		"hb_ctx_set":             len(hbCtx) != 0,
	})
}
