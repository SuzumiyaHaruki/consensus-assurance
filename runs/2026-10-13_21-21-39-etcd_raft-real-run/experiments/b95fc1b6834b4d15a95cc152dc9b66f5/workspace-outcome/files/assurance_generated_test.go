package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	pb "go.etcd.io/raft/v3/raftpb"
	"google.golang.org/protobuf/proto"
)

// caEvent emits a single machine-parsable event line.
func caEvent(t *testing.T, v map[string]any) {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceEmptyExplicitConfChangeJoint enters a joint configuration, then
// proposes an empty ConfChangeV2 whose transition is explicit rather than auto,
// and records what propose-time validation does with it and what applying it
// does.
func TestAssuranceEmptyExplicitConfChangeJoint(t *testing.T) {
	r := newTestRaft(1, 3, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r.becomeCandidate()
	r.becomeLeader()

	enter := &pb.ConfChangeV2{
		Transition: pb.ConfChangeTransitionJointExplicit.Enum(),
		Changes:    []*pb.ConfChangeSingle{{Type: pb.ConfChangeAddNode.Enum(), NodeId: new(uint64(4))}},
	}
	cs := r.applyConfChange(enter)

	bad := &pb.ConfChangeV2{Transition: pb.ConfChangeTransitionJointExplicit.Enum()}
	_, enterOK := bad.EnterJoint()
	caEvent(t, map[string]any{
		"event":          "empty_cc_joint_setup",
		"alias":          "joint_empty_explicit",
		"joint":          len(cs.GetVotersOutgoing()) > 0,
		"voters":         cs.GetVoters(),
		"voters_outgoing": cs.GetVotersOutgoing(),
		"transition":     bad.GetTransition().String(),
		"changes":        len(bad.GetChanges()),
		"leave_joint":    bad.LeaveJoint(),
		"enter_joint_ok": enterOK,
	})

	data, err := proto.Marshal(bad)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	lastBefore := r.raftLog.lastIndex()
	stepErr := r.Step(&pb.Message{
		From: new(uint64(1)),
		Type: pb.MsgProp.Enum(),
		Entries: []*pb.Entry{{Type: pb.EntryConfChangeV2.Enum(), Data: data}},
	})
	ents, err := r.raftLog.entries(r.raftLog.lastIndex(), noLimit)
	if err != nil {
		t.Fatalf("entries: %v", err)
	}
	lastType := ""
	if len(ents) > 0 {
		lastType = ents[len(ents)-1].GetType().String()
	}
	caEvent(t, map[string]any{
		"event":       "empty_cc_joint_prop",
		"alias":       "joint_empty_explicit",
		"step_err":    fmt.Sprint(stepErr),
		"appended":    r.raftLog.lastIndex() - lastBefore,
		"last_type":   lastType,
		"data_len":    len(data),
	})

	panicked := false
	panicText := ""
	func() {
		defer func() {
			if rec := recover(); rec != nil {
				panicked = true
				panicText = fmt.Sprint(rec)
			}
		}()
		r.applyConfChange(bad)
	}()
	caEvent(t, map[string]any{
		"event":     "empty_cc_joint_apply",
		"alias":     "joint_empty_explicit",
		"panicked":  panicked,
		"panic":     panicText,
		"still_joint": len(r.trk.Config.Voters[1]) > 0,
	})
}

// TestAssuranceEmptyAutoConfChangeLeavesJoint is the control for the previous
// test: the Auto-transition empty ConfChangeV2 is the documented leave-joint
// idiom, so it must leave the joint configuration without panicking.
func TestAssuranceEmptyAutoConfChangeLeavesJoint(t *testing.T) {
	r := newTestRaft(1, 3, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r.becomeCandidate()
	r.becomeLeader()
	enter := &pb.ConfChangeV2{
		Transition: pb.ConfChangeTransitionJointExplicit.Enum(),
		Changes:    []*pb.ConfChangeSingle{{Type: pb.ConfChangeAddNode.Enum(), NodeId: new(uint64(4))}},
	}
	cs := r.applyConfChange(enter)
	good := &pb.ConfChangeV2{}
	caEvent(t, map[string]any{
		"event":          "empty_cc_auto_setup",
		"alias":          "joint_empty_auto",
		"joint":          len(cs.GetVotersOutgoing()) > 0,
		"voters":         cs.GetVoters(),
		"transition":     good.GetTransition().String(),
		"changes":        len(good.GetChanges()),
		"leave_joint":    good.LeaveJoint(),
		"enter_joint_ok": func() bool { _, ok := good.EnterJoint(); return ok }(),
	})
	panicked := false
	panicText := ""
	var after *pb.ConfState
	func() {
		defer func() {
			if rec := recover(); rec != nil {
				panicked = true
				panicText = fmt.Sprint(rec)
			}
		}()
		after = r.applyConfChange(good)
	}()
	jointAfter := len(r.trk.Config.Voters[1]) > 0
	votersAfter := []uint64(nil)
	if after != nil {
		votersAfter = after.GetVoters()
	}
	caEvent(t, map[string]any{
		"event":        "empty_cc_auto_apply",
		"alias":        "joint_empty_auto",
		"panicked":     panicked,
		"panic":        panicText,
		"joint_after":  jointAfter,
		"voters_after": votersAfter,
	})
}

// TestAssuranceEmptyImplicitConfChangeJoint covers the sibling explicit
// transition: EnterJoint treats JointImplicit as a joint transition too, so an
// empty change set with that transition should be accepted by validation and
// then panic on apply exactly like JointExplicit.
func TestAssuranceEmptyImplicitConfChangeJoint(t *testing.T) {
	r := newTestRaft(1, 3, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r.becomeCandidate()
	r.becomeLeader()
	enter := &pb.ConfChangeV2{
		Transition: pb.ConfChangeTransitionJointExplicit.Enum(),
		Changes:    []*pb.ConfChangeSingle{{Type: pb.ConfChangeAddNode.Enum(), NodeId: new(uint64(4))}},
	}
	cs := r.applyConfChange(enter)
	bad := &pb.ConfChangeV2{Transition: pb.ConfChangeTransitionJointImplicit.Enum()}
	_, enterOK := bad.EnterJoint()
	caEvent(t, map[string]any{
		"event":           "empty_cc_implicit_setup",
		"alias":           "joint_empty_implicit",
		"joint":           len(cs.GetVotersOutgoing()) > 0,
		"voters":          cs.GetVoters(),
		"voters_outgoing": cs.GetVotersOutgoing(),
		"transition":      bad.GetTransition().String(),
		"changes":         len(bad.GetChanges()),
		"leave_joint":     bad.LeaveJoint(),
		"enter_joint_ok":  enterOK,
	})
	data, err := proto.Marshal(bad)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	lastBefore := r.raftLog.lastIndex()
	stepErr := r.Step(&pb.Message{
		From:    new(uint64(1)),
		Type:    pb.MsgProp.Enum(),
		Entries: []*pb.Entry{{Type: pb.EntryConfChangeV2.Enum(), Data: data}},
	})
	ents, err := r.raftLog.entries(r.raftLog.lastIndex(), noLimit)
	if err != nil {
		t.Fatalf("entries: %v", err)
	}
	lastType := ""
	if len(ents) > 0 {
		lastType = ents[len(ents)-1].GetType().String()
	}
	caEvent(t, map[string]any{
		"event":     "empty_cc_implicit_prop",
		"alias":     "joint_empty_implicit",
		"step_err":  fmt.Sprint(stepErr),
		"appended":  r.raftLog.lastIndex() - lastBefore,
		"last_type": lastType,
	})
	panicked := false
	panicText := ""
	func() {
		defer func() {
			if rec := recover(); rec != nil {
				panicked = true
				panicText = fmt.Sprint(rec)
			}
		}()
		r.applyConfChange(bad)
	}()
	caEvent(t, map[string]any{
		"event":       "empty_cc_implicit_apply",
		"alias":       "joint_empty_implicit",
		"panicked":    panicked,
		"panic":       panicText,
		"still_joint": len(r.trk.Config.Voters[1]) > 0,
	})
}

// TestAssuranceEmptyNonAutoConfChangeCommits closes the end-to-end gap: the
// malformed change is proposed on a real three-node network, commits, and only
// then is applied the way an application would.
func TestAssuranceEmptyNonAutoConfChangeCommits(t *testing.T) {
	nt := newNetwork(nil, nil, nil)
	nt.send(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgHup.Enum()})
	lead := nt.peers[1].(*raft)
	prop := func(cc *pb.ConfChangeV2) *pb.Message {
		data, err := proto.Marshal(cc)
		if err != nil {
			t.Fatalf("marshal: %v", err)
		}
		return &pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgProp.Enum(),
			Entries: []*pb.Entry{{Type: pb.EntryConfChangeV2.Enum(), Data: data}}}
	}
	enter := &pb.ConfChangeV2{
		Transition: pb.ConfChangeTransitionJointExplicit.Enum(),
		Changes:    []*pb.ConfChangeSingle{{Type: pb.ConfChangeAddNode.Enum(), NodeId: new(uint64(2))}},
	}
	nt.send(prop(enter))
	for _, p := range nt.peers {
		p.(*raft).applyConfChange(enter)
	}
	caEvent(t, map[string]any{
		"event":     "committed_cc_setup",
		"alias":     "committed_empty_nonauto",
		"state":     lead.state.String(),
		"joint":     len(lead.trk.Config.Voters[1]) > 0,
		"voters":    lead.trk.Config.Voters[0].Slice(),
		"outgoing":  lead.trk.Config.Voters[1].Slice(),
		"committed": lead.raftLog.committed,
	})

	bad := &pb.ConfChangeV2{Transition: pb.ConfChangeTransitionJointExplicit.Enum()}
	entryIndex := lead.raftLog.lastIndex() + 1
	nt.send(prop(bad))
	lastType := ""
	if ents, err := lead.raftLog.entries(entryIndex, noLimit); err == nil && len(ents) > 0 {
		lastType = ents[len(ents)-1].GetType().String()
	}
	caEvent(t, map[string]any{
		"event":            "committed_cc_probe",
		"alias":            "committed_empty_nonauto",
		"entry_index":      entryIndex,
		"committed":        lead.raftLog.committed,
		"committed_reached": lead.raftLog.committed >= entryIndex,
		"entry_type":       lastType,
	})

	panicked := false
	panicText := ""
	func() {
		defer func() {
			if rec := recover(); rec != nil {
				panicked = true
				panicText = fmt.Sprint(rec)
			}
		}()
		lead.applyConfChange(bad)
	}()
	caEvent(t, map[string]any{
		"event":       "committed_cc_apply",
		"alias":       "committed_empty_nonauto",
		"panicked":    panicked,
		"panic":       panicText,
		"still_joint": len(lead.trk.Config.Voters[1]) > 0,
	})
}

// TestAssuranceCommittedEmptyNonAutoConfChange closes the end-to-end gap: the
// application acknowledges applied entries (the effect of Advance) so the
// pending-conf guard is clear, then the malformed change is proposed on a real
// three-node network, commits, and is applied from the committed entry.
func TestAssuranceCommittedEmptyNonAutoConfChange(t *testing.T) {
	nt := newNetwork(nil, nil, nil)
	nt.send(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgHup.Enum()})
	lead := nt.peers[1].(*raft)
	prop := func(cc *pb.ConfChangeV2) *pb.Message {
		data, err := proto.Marshal(cc)
		if err != nil {
			t.Fatalf("marshal: %v", err)
		}
		return &pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgProp.Enum(),
			Entries: []*pb.Entry{{Type: pb.EntryConfChangeV2.Enum(), Data: data}}}
	}

	enter := &pb.ConfChangeV2{
		Transition: pb.ConfChangeTransitionJointExplicit.Enum(),
		Changes:    []*pb.ConfChangeSingle{{Type: pb.ConfChangeAddNode.Enum(), NodeId: new(uint64(2))}},
	}
	enterIdx := lead.raftLog.lastIndex() + 1
	nt.send(prop(enter))
	// Every application applies the committed joint change and acknowledges its
	// applied entries, which is what Advance does.
	for _, p := range nt.peers {
		r := p.(*raft)
		if r.raftLog.committed >= enterIdx {
			r.raftLog.appliedTo(r.raftLog.committed, 0)
		}
		r.applyConfChange(enter)
	}
	caEvent(t, map[string]any{
		"event":             "committed_cc_setup",
		"alias":             "committed_nonauto",
		"joint":             len(lead.trk.Config.Voters[1]) > 0,
		"voters":            lead.trk.Config.Voters[0].Slice(),
		"outgoing":          lead.trk.Config.Voters[1].Slice(),
		"committed":         lead.raftLog.committed,
		"applied":           lead.raftLog.applied,
		"pending_conf_idx":  lead.pendingConfIndex,
		"already_pending":   lead.pendingConfIndex > lead.raftLog.applied,
	})

	bad := &pb.ConfChangeV2{Transition: pb.ConfChangeTransitionJointExplicit.Enum()}
	badIdx := lead.raftLog.lastIndex() + 1
	nt.send(prop(bad))
	entryType := ""
	if ents, err := lead.raftLog.entries(badIdx, noLimit); err == nil && len(ents) > 0 {
		entryType = ents[len(ents)-1].GetType().String()
	}
	caEvent(t, map[string]any{
		"event":             "committed_cc_probe",
		"alias":             "committed_nonauto",
		"entry_index":       badIdx,
		"entry_type":        entryType,
		"committed":         lead.raftLog.committed,
		"committed_reached": lead.raftLog.committed >= badIdx,
	})

	panicked := false
	panicText := ""
	func() {
		defer func() {
			if rec := recover(); rec != nil {
				panicked = true
				panicText = fmt.Sprint(rec)
			}
		}()
		lead.applyConfChange(bad)
	}()
	caEvent(t, map[string]any{
		"event":       "committed_cc_apply",
		"alias":       "committed_nonauto",
		"panicked":    panicked,
		"panic":       panicText,
		"still_joint": len(lead.trk.Config.Voters[1]) > 0,
	})
}
