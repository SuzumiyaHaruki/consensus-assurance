package raft

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	pb "go.etcd.io/raft/v3/raftpb"
)

func assurance3WaitFor(t *testing.T, what string, pred func() bool) bool {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if pred() {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Logf("transition not observed: %s", what)
	return false
}

func assurance3Emit(t *testing.T, ev map[string]any) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("cannot marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceProposeAfterReAdd observes the Node wrapper's proposal channel
// for a follower that is removed from the configuration and then added back by
// the same leader in the same term: the code comments the channel reset as
// "not very sound and likely has bugs" (node.go:409-411) and registers the node
// as a member again, so the app-side proposal path is compared before the
// removal, after the re-add, and after a leadership change.
func TestAssuranceProposeAfterReAdd(t *testing.T) {
	n2Store := newTestMemoryStorage(withPeers(1, 2))
	ctx, cancel, h := newNodeTestHarness(context.Background(), t, newTestConfig(2, 10, 1, n2Store))
	defer cancel()
	n1 := newTestRaft(1, 10, 1, newTestMemoryStorage(withPeers(1, 2)))

	// node 1 leads the group without an election round trip; node 2 learns that
	// from the appends it receives below.
	n1.becomeCandidate()
	n1.becomeLeader()
	n1.bcastAppend()

	// handleReady drains one Ready of the wrapped node, steps the messages it
	// carries (and the ones node 1 produces in response) as the application's
	// message pump would, and then advances the node.
	handleReady := func(timeout time.Duration) bool {
		tick, tcancel := context.WithTimeout(ctx, timeout)
		defer tcancel()
		select {
		case rd := <-h.Ready():
			// Application duty: HardState, Entries and Snapshot must be on
			// stable storage before this Ready's messages are sent.
			if rd.Snapshot != nil {
				if err := n2Store.ApplySnapshot(rd.Snapshot); err != nil && err != ErrSnapOutOfDate {
					t.Logf("node 2 apply snapshot: %v", err)
				}
			}
			if len(rd.Entries) > 0 {
				if err := n2Store.Append(rd.Entries); err != nil {
					t.Logf("node 2 append entries: %v", err)
				}
			}
			if !IsEmptyHardState(rd.HardState) {
				if err := n2Store.SetHardState(rd.HardState); err != nil {
					t.Logf("node 2 hard state: %v", err)
				}
			}
			var toNode1 []*pb.Message
			for _, m := range rd.Messages {
				if m.GetTo() == 1 {
					toNode1 = append(toNode1, m)
				}
			}
			h.Advance()
			var toNode2 []*pb.Message
			for _, m := range toNode1 {
				if err := n1.Step(m); err != nil {
					t.Logf("node 1 step: %v", err)
				}
			}
			toNode2 = append(toNode2, n1.readMessages()...)
			for _, m := range toNode2 {
				if m.GetTo() != 2 {
					continue
				}
				if err := h.Step(ctx, m); err != nil {
					t.Logf("node 2 step: %v", err)
				}
			}
			return true
		case <-tick.Done():
			return false
		}
	}
	// pump alternates delivering node 1's outgoing messages to node 2 with
	// draining one of node 2's Readys until neither side produces anything.
	pump := func() {
		for i := 0; i < 50; i++ {
			progressed := false
			for _, m := range n1.readMessages() {
				if m.GetTo() == 2 {
					if err := h.Step(ctx, m); err != nil {
						t.Logf("node 2 step: %v", err)
					}
					progressed = true
				}
			}
			if handleReady(300 * time.Millisecond) {
				progressed = true
			}
			if !progressed {
				return
			}
		}
	}
	// Deliver the new leader's appends, then wait until the wrapped node has
	// demonstrably processed them: Node.Step only hands a message to the run
	// loop, so an observation taken immediately after Step would read state
	// that the node has not updated yet.
	for i := 0; i < 12; i++ {
		pump()
	}
	assurance3WaitFor(t, "node 2 knows leader 1", func() bool { return h.Status().Lead == 1 })

	propose := func(what string) (err error, dur time.Duration) {
		pctx, pcancel := context.WithTimeout(ctx, 300*time.Millisecond)
		defer pcancel()
		start := time.Now()
		err = h.Propose(pctx, []byte(what))
		return err, time.Since(start)
	}
	state := func() map[string]any {
		st := h.Status()
		return map[string]any{
			"snapshot_via":     "status-channel",
			"node":              st.ID,
			"state":             st.RaftState.String(),
			"known_leader":      st.Lead,
			"term":              st.GetTerm(),
			"committed_index":   st.GetCommit(),
			"applied_index":     st.Applied,
			"leader_last_index": n1.raftLog.lastIndex(),
			"leader_sees_member": func() bool { _, ok := n1.trk.Progress[2]; return ok }(),
			"leader_config":     n1.trk.Config.String(),
		}
	}

	assurance3Emit(t, map[string]any{
		"scenario": "node-propose-after-readd","event": "setup", "step": "before-removal",
		"cluster": "voters=(1 2)", "node2_state": state()})

	// Control 1: while node 2 is a plain member it proposes successfully (the
	// follower forwards the proposal to leader 1).
	err1, dur1 := propose("control-before-removal")
	pump()
	ev := map[string]any{
		"scenario": "node-propose-after-readd","event": "propose_before_removal", "step": "propose-before-removal",
		"proposal_returned_error": err1 != nil, "proposal_duration_ms": dur1.Milliseconds()}
	for k, v := range state() {
		ev[k] = v
	}
	if err1 != nil {
		ev["proposal_error"] = err1.Error()
	}
	assurance3Emit(t, ev)

	// The leader removes node 2 and both nodes apply the committed change.
	remove, err := confChangeToMsg(&pb.ConfChange{Type: pb.ConfChangeRemoveNode.Enum(), NodeId: new(uint64(2))})
	if err != nil {
		t.Fatalf("remove message: %v", err)
	}
	remove.From, remove.To = new(uint64(1)), new(uint64(1))
	if err := n1.Step(remove); err != nil {
		t.Fatalf("propose removal: %v", err)
	}
	pump()
	removeChange := &pb.ConfChange{Type: pb.ConfChangeRemoveNode.Enum(), NodeId: new(uint64(2))}
	n1.applyConfChange(removeChange.AsV2())
	h.ApplyConfChange(removeChange.AsV2())
	pump()

	assurance3Emit(t, map[string]any{
		"scenario": "node-propose-after-readd","event": "node2_removed", "step": "after-removal",
		"leader_config": n1.trk.Config.String(), "node2_state": state()})

	// The same leader adds node 2 back in the same term.
	add, err := confChangeToMsg(&pb.ConfChange{Type: pb.ConfChangeAddNode.Enum(), NodeId: new(uint64(2))})
	if err != nil {
		t.Fatalf("add message: %v", err)
	}
	add.From, add.To = new(uint64(1)), new(uint64(1))
	if err := n1.Step(add); err != nil {
		t.Fatalf("propose re-add: %v", err)
	}
	pump()
	addChange := &pb.ConfChange{Type: pb.ConfChangeAddNode.Enum(), NodeId: new(uint64(2))}
	n1.applyConfChange(addChange.AsV2())
	h.ApplyConfChange(addChange.AsV2())
	pump()

	assurance3Emit(t, map[string]any{
		"scenario": "node-propose-after-readd","event": "node2_readded", "step": "after-re-add",
		"leader_config": n1.trk.Config.String(), "node2_state": state()})

	// Witness: node 2 is a member again, knows the same leader, and its proposal
	// is not delivered to the group.
	leaderIndexBefore := n1.raftLog.lastIndex()
	err2, dur2 := propose("witness-after-re-add")
	pump()
	ev = map[string]any{
		"scenario": "node-propose-after-readd","event": "propose_after_readd", "step": "propose-after-re-add",
		"proposal_returned_error": err2 != nil, "proposal_duration_ms": dur2.Milliseconds(),
		"leader_index_before":     leaderIndexBefore,
		"leader_last_index":       n1.raftLog.lastIndex(),
		"leader_advanced":         n1.raftLog.lastIndex() > leaderIndexBefore}
	for k, v := range state() {
		ev[k] = v
	}
	if err2 != nil {
		ev["proposal_error"] = err2.Error()
	}
	assurance3Emit(t, ev)


}
