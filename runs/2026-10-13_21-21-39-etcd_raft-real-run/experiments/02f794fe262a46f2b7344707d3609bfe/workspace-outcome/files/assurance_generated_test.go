package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	pb "go.etcd.io/raft/v3/raftpb"
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

// TestAssuranceReadIndexPendingGrowth drives a real leader that cannot obtain
// quorum acknowledgements (no MsgAppResp / MsgHeartbeatResp is ever delivered)
// and retries ReadIndex with the same RequestCtx.
func TestAssuranceReadIndexPendingGrowth(t *testing.T) {
	r := newTestRaft(1, 3, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r.becomeCandidate()
	r.becomeLeader()
	caEvent(t, map[string]any{
		"event":          "read_growth_setup",
		"alias":          "isolated_leader",
		"state":          r.state.String(),
		"term":           r.Term,
		"committed":      r.raftLog.committed,
		"last_index":     r.raftLog.lastIndex(),
		"check_quorum":   r.checkQuorum,
		"read_only_safe": r.readOnly.option == ReadOnlySafe,
		"voter_count":    len(r.trk.Voters.IDs()),
	})

	rounds := 64
	ctx := []byte("same-ctx")
	for i := 0; i < rounds; i++ {
		_ = r.Step(&pb.Message{Type: pb.MsgReadIndex.Enum(), Entries: []*pb.Entry{{Data: ctx}}})
		// Drop outbound traffic so growth is measured in raft state, not in msgs.
		r.msgs = nil
		r.msgsAfterAppend = nil
	}
	caEvent(t, map[string]any{
		"event":       "read_growth_probe",
		"alias":       "isolated_leader",
		"rounds":      rounds,
		"pending":     len(r.pendingReadIndexMessages),
		"unconfirmed": len(r.readOnly.unconfirmedReads),
		"state_after": r.state.String(),
	})

	// A higher-term heartbeat deposes the node; the queued duty is not cleared.
	_ = r.Step(&pb.Message{From: new(uint64(2)), Term: new(r.Term + 1), Type: pb.MsgHeartbeat.Enum()})
	caEvent(t, map[string]any{
		"event":             "read_growth_after_stepdown",
		"alias":             "isolated_leader",
		"state_after":       r.state.String(),
		"pending_after":     len(r.pendingReadIndexMessages),
		"unconfirmed_after": len(r.readOnly.unconfirmedReads),
	})
}

// TestAssuranceReadIndexAdmittedGrowth drives the admitted (not queued) path: a
// leader that has committed in its term but whose followers stop acknowledging
// heartbeats still admits every retried ReadIndex into unconfirmedReads and
// broadcasts a heartbeat per request.
func TestAssuranceReadIndexAdmittedGrowth(t *testing.T) {
	r := newTestRaft(1, 3, 1, newTestMemoryStorage(withPeers(1, 2)))
	r.becomeCandidate()
	r.becomeLeader()
	// Deliver the leader's own self-ack for the empty entry, then let node 2
	// acknowledge it, so the leader commits in its term.
	for _, m := range r.msgsAfterAppend {
		_ = r.Step(m)
	}
	_ = r.Step(&pb.Message{From: new(uint64(2)), Type: pb.MsgAppResp.Enum(), Index: new(r.raftLog.lastIndex())})
	r.msgs = nil
	r.msgsAfterAppend = nil
	caEvent(t, map[string]any{
		"event":          "read_admitted_setup",
		"alias":          "committed_no_acks",
		"state":          r.state.String(),
		"term":           r.Term,
		"committed":      r.raftLog.committed,
		"last_index":     r.raftLog.lastIndex(),
		"in_term":        r.committedEntryInCurrentTerm(),
		"check_quorum":   r.checkQuorum,
		"read_only_safe": r.readOnly.option == ReadOnlySafe,
		"voter_count":    len(r.trk.Voters.IDs()),
	})

	rounds := 64
	broadcasts := 0
	ctx := []byte("same-ctx")
	for i := 0; i < rounds; i++ {
		_ = r.Step(&pb.Message{Type: pb.MsgReadIndex.Enum(), Entries: []*pb.Entry{{Data: ctx}}})
		for _, m := range r.msgs {
			if m.GetType() == pb.MsgHeartbeat {
				broadcasts++
			}
		}
		r.msgs = nil
		r.msgsAfterAppend = nil
	}
	caEvent(t, map[string]any{
		"event":       "read_admitted_probe",
		"alias":       "committed_no_acks",
		"rounds":      rounds,
		"unconfirmed": len(r.readOnly.unconfirmedReads),
		"broadcasts":  broadcasts,
		"pending":     len(r.pendingReadIndexMessages),
		"confirmed":   r.readOnly.confirmedReads,
		"state_after": r.state.String(),
	})
}

// TestAssuranceReadIndexQueuedDrainBurst measures what happens when a leader
// that accumulated queued read requests finally commits in its term: the whole
// queue is released in one step, each entry re-admitted and rebroadcast.
func TestAssuranceReadIndexQueuedDrainBurst(t *testing.T) {
	r := newTestRaft(1, 3, 1, newTestMemoryStorage(withPeers(1, 2)))
	r.becomeCandidate()
	r.becomeLeader()
	r.msgs = nil
	r.msgsAfterAppend = nil

	rounds := 64
	ctx := []byte("same-ctx")
	for i := 0; i < rounds; i++ {
		_ = r.Step(&pb.Message{Type: pb.MsgReadIndex.Enum(), Entries: []*pb.Entry{{Data: ctx}}})
		r.msgs = nil
		r.msgsAfterAppend = nil
	}
	caEvent(t, map[string]any{
		"event":       "read_drain_setup",
		"alias":       "queued_then_commit",
		"rounds":      rounds,
		"pending":     len(r.pendingReadIndexMessages),
		"committed":   r.raftLog.committed,
		"in_term":     r.committedEntryInCurrentTerm(),
		"unconfirmed": len(r.readOnly.unconfirmedReads),
	})

	// Now let the leader commit in its term: its own ack, then node 2's ack for
	// the empty entry. The follower's MsgAppResp takes the leader fast path that
	// calls releasePendingReadIndexMessages.
	_ = r.Step(&pb.Message{From: new(uint64(1)), Type: pb.MsgAppResp.Enum(), Index: new(r.raftLog.lastIndex())})
	_ = r.Step(&pb.Message{From: new(uint64(2)), Type: pb.MsgAppResp.Enum(), Index: new(r.raftLog.lastIndex())})
	broadcasts := 0
	for _, m := range r.msgs {
		if m.GetType() == pb.MsgHeartbeat {
			broadcasts++
		}
	}
	caEvent(t, map[string]any{
		"event":       "read_drain_after_commit",
		"alias":       "queued_then_commit",
		"committed":   r.raftLog.committed,
		"in_term":     r.committedEntryInCurrentTerm(),
		"pending":     len(r.pendingReadIndexMessages),
		"unconfirmed": len(r.readOnly.unconfirmedReads),
		"broadcasts":  broadcasts,
		"state_after": r.state.String(),
	})
}
