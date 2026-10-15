package raft

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	pb "go.etcd.io/raft/v3/raftpb"
)

func assurance4Emit(t *testing.T, ev map[string]any) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("cannot marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceReadIndexPostponedAcrossConfigCommitViaNode observes the first
// question's defect through the public Node/Ready contract: the application
// consumes the wrapped leader's Readys and advances while it is still applying
// the committed configuration change (which node.go:166-187 permits), campaigns,
// issues a ReadIndex request, and only then calls ApplyConfChange for the change
// it had already observed. The observation is whether any Ready delivers a
// ReadState for that request once the applied change makes the leader's term
// entry committable.
func TestAssuranceReadIndexPostponedAcrossConfigCommitViaNode(t *testing.T) {
	// Fixture: four voters, ten term-1 entries whose last one removes voter 4,
	// persisted commit 10, and the application has not yet applied that change.
	cc := &pb.ConfChangeV2{Changes: []*pb.ConfChangeSingle{
		{Type: pb.ConfChangeRemoveNode.Enum(), NodeId: new(uint64(4))},
	}}
	typ, data, err := pb.MarshalConfChange(cc)
	if err != nil {
		t.Fatalf("marshal conf change: %v", err)
	}
	ents := make([]*pb.Entry, 10)
	for i := 0; i < 9; i++ {
		ents[i] = &pb.Entry{Term: new(uint64(1)), Index: new(uint64(i + 1)), Data: []byte("payload")}
	}
	ents[9] = &pb.Entry{Term: new(uint64(1)), Index: new(uint64(10)), Type: typ.Enum(), Data: data}

	n1Store := newTestMemoryStorage(withPeers(1, 2, 3, 4))
	if err := n1Store.Append(ents); err != nil {
		t.Fatalf("append entries: %v", err)
	}
	if err := n1Store.SetHardState(&pb.HardState{Term: new(uint64(1)), Commit: new(uint64(10))}); err != nil {
		t.Fatalf("set hard state: %v", err)
	}
	ctx, cancel, h := newNodeTestHarness(context.Background(), t, newTestConfig(1, 10, 1, n1Store))
	defer cancel()

	n2 := newTestRaft(2, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3, 4)))
	n3 := newTestRaft(3, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3, 4)))

	held := []*pb.Message{}
	var readStates []ReadState
	ready := func(timeout time.Duration) (bool, ReadState, bool) {
		tick, tcancel := context.WithTimeout(ctx, timeout)
		defer tcancel()
		select {
		case rd := <-h.Ready():
			if rd.Snapshot != nil {
				if err := n1Store.ApplySnapshot(rd.Snapshot); err != nil && err != ErrSnapOutOfDate {
					t.Logf("apply snapshot: %v", err)
				}
			}
			if len(rd.Entries) > 0 {
				if err := n1Store.Append(rd.Entries); err != nil {
					t.Logf("append entries: %v", err)
				}
			}
			if !IsEmptyHardState(rd.HardState) {
				if err := n1Store.SetHardState(rd.HardState); err != nil {
					t.Logf("hard state: %v", err)
				}
			}
			if len(rd.ReadStates) > 0 {
				readStates = append(readStates, rd.ReadStates...)
			}
			h.Advance()
			var out []*pb.Message
			for _, m := range rd.Messages {
				switch m.GetTo() {
				case 2:
					if err := n2.Step(m); err != nil {
						t.Logf("node 2 step: %v", err)
					}
					out = append(out, n2.readMessages()...)
				case 3:
					if err := n3.Step(m); err != nil {
						t.Logf("node 3 step: %v", err)
					}
					out = append(out, n3.readMessages()...)
				}
			}
			for _, m := range out {
				if m.GetFrom() == 3 && m.GetType() == pb.MsgAppResp {
					// voter 3's append acknowledgements are delayed, so the
					// leader cannot commit under the configuration it still has.
					held = append(held, m)
					continue
				}
				if err := h.Step(ctx, m); err != nil {
					t.Logf("leader step: %v", err)
				}
			}
			ok := false
			if len(readStates) > 0 {
				for _, rs := range readStates {
					if string(rs.RequestCtx) == "A" {
						ok = true
					}
				}
			}
			return true, ReadState{Index: 0}, ok
		case <-tick.Done():
			return false, ReadState{}, false
		}
	}
	pump := func() {
		for i := 0; i < 30; i++ {
			if handled, _, _ := ready(200 * time.Millisecond); !handled {
				return
			}
		}
	}
	// The application consumes Readys (including the committed entries) and
	// calls Advance while it is still applying the change: applied progress is
	// reported without ApplyConfChange having been called.
	pump()
	st := h.Status()
	assurance4Emit(t, map[string]any{
		"event": "applied_progress_reported", "scenario": "node-api-postponed-read",
		"node": 1, "state": st.RaftState.String(), "term": st.GetTerm(),
		"applied_index": st.Applied, "committed_index": st.GetCommit(),
		"tracker_config": h.rn.raft.trk.Config.String(),
		"conf_change_applied_by_app": false,
	})

	if err := h.Campaign(ctx); err != nil {
		t.Logf("campaign: %v", err)
	}
	pump()
	st = h.Status()
	assurance4Emit(t, map[string]any{
		"event": "leader_elected", "scenario": "node-api-postponed-read",
		"node": 1, "state": st.RaftState.String(), "term": st.GetTerm(),
		"committed_index": st.GetCommit(), "applied_index": st.Applied,
		"last_index": h.rn.raft.raftLog.lastIndex(),
		"tracker_config": h.rn.raft.trk.Config.String(),
		"match": map[uint64]uint64{
			1: h.rn.raft.trk.Progress[1].Match,
			2: h.rn.raft.trk.Progress[2].Match,
			3: h.rn.raft.trk.Progress[3].Match,
			4: h.rn.raft.trk.Progress[4].Match,
		},
	})

	if err := h.ReadIndex(ctx, []byte("A")); err != nil {
		t.Logf("read index: %v", err)
	}
	pump()
	st = h.Status()
	assurance4Emit(t, map[string]any{
		"event": "readindex_requested", "scenario": "node-api-postponed-read",
		"node": 1, "term": st.GetTerm(), "committed_index": st.GetCommit(),
		"pending_reads":       len(h.rn.raft.pendingReadIndexMessages),
		"unconfirmed_reads":   len(h.rn.raft.readOnly.unconfirmedReads),
		"read_states_delivered": len(readStates),
	})

	// The application now applies the change it had already observed.
	cs := h.ApplyConfChange(cc)
	pump()
	st = h.Status()
	ev := map[string]any{
		"event": "conf_change_applied", "scenario": "node-api-postponed-read",
		"node": 1, "term": st.GetTerm(), "committed_index": st.GetCommit(),
		"applied_index":     st.Applied,
		"conf_state":        DescribeConfState(cs),
		"tracker_config":    h.rn.raft.trk.Config.String(),
		"pending_reads":     len(h.rn.raft.pendingReadIndexMessages),
		"unconfirmed_reads": len(h.rn.raft.readOnly.unconfirmedReads),
		"read_states_delivered": len(readStates),
		"held_messages": len(held), "read_states_for_request": 0,
	}
	for _, rs := range readStates {
		if string(rs.RequestCtx) == "A" {
			ev["read_states_for_request"] = ev["read_states_for_request"].(int) + 1
		}
	}
	term, err := h.rn.raft.raftLog.term(h.rn.raft.raftLog.committed)
	if err == nil {
		ev["committed_entry_term"] = term
	}
	ev["term_has_commit"] = h.rn.raft.committedEntryInCurrentTerm()
	assurance4Emit(t, ev)
}
