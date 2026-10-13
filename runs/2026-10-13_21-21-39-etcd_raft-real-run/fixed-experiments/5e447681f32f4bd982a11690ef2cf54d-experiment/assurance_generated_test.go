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

// TestAssuranceCommittedNonAutoConfChange is the single case in this harness:
// a real three-node network, the application caught up so no conf change is
// pending unapplied, then an empty ConfChangeV2 with an explicit transition
// proposed, committed, and applied the way an application must apply it.
func TestAssuranceCommittedNonAutoConfChange(t *testing.T) {
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
	for _, p := range nt.peers {
		r := p.(*raft)
		if r.raftLog.committed >= enterIdx {
			r.raftLog.appliedTo(r.raftLog.committed, 0)
		}
		r.applyConfChange(enter)
	}
	caEvent(t, map[string]any{
		"event":            "nonauto_setup",
		"alias":            "committed_nonauto",
		"state":            lead.state.String(),
		"joint":            len(lead.trk.Config.Voters[1]) > 0,
		"voters":           lead.trk.Config.Voters[0].Slice(),
		"outgoing":         lead.trk.Config.Voters[1].Slice(),
		"committed":        lead.raftLog.committed,
		"applied":          lead.raftLog.applied,
		"pending_conf_idx": lead.pendingConfIndex,
		"already_pending":  lead.pendingConfIndex > lead.raftLog.applied,
	})

	bad := &pb.ConfChangeV2{Transition: pb.ConfChangeTransitionJointExplicit.Enum()}
	badIdx := lead.raftLog.lastIndex() + 1
	nt.send(prop(bad))
	entryType := ""
	if ents, err := lead.raftLog.entries(badIdx, noLimit); err == nil && len(ents) > 0 {
		entryType = ents[len(ents)-1].GetType().String()
	}
	caEvent(t, map[string]any{
		"event":             "nonauto_probe",
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
		"event":       "nonauto_apply",
		"alias":       "committed_nonauto",
		"panicked":    panicked,
		"panic":       panicText,
		"still_joint": len(lead.trk.Config.Voters[1]) > 0,
	})
}
