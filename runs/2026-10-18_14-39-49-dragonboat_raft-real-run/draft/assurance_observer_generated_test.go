package raft

import (
	"encoding/json"
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

func emitObserverAssuranceEvent(t *testing.T, event map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("failed to marshal assurance event: %v", err)
	}
	t.Logf("CA_EVENT %s", b)
}

func TestAssuranceObserverReadIndexReplyContext(t *testing.T) {
	r := newTestRaft(1, []uint64{1, 2, 3}, 5, 1, NewTestLogDB())
	r.becomeFollower(1, NoLeader)
	r.becomeCandidate()
	r.becomeLeader()
	r.remotes[2].tryUpdate(r.log.lastIndex())
	if !r.tryCommit() {
		t.Fatal("failed to commit the leader no-op in its current term")
	}
	r.addObserver(4)

	ctxA := pb.SystemCtx{Low: 101, High: 1002}
	ctxB := pb.SystemCtx{Low: 202, High: 2003}
	r.Handle(pb.Message{
		From:     4,
		To:       1,
		Type:     pb.ReadIndex,
		Hint:     ctxA.Low,
		HintHigh: ctxA.High,
	})
	r.Handle(pb.Message{
		From:     3,
		To:       1,
		Type:     pb.ReadIndex,
		Hint:     ctxB.Low,
		HintHigh: ctxB.High,
	})
	if len(r.readIndex.pending) != 2 {
		t.Fatalf("expected two pending requests, got %d", len(r.readIndex.pending))
	}
	emitObserverAssuranceEvent(t, map[string]interface{}{
		"event":      "observer_readindex_requested",
		"request_id": "observer-read-A",
		"node_id":    uint64(4),
		"leader_id":  uint64(1),
		"ctx_low":    ctxA.Low,
		"ctx_high":   ctxA.High,
	})

	r.msgs = nil
	r.Handle(pb.Message{
		From:     3,
		To:       1,
		Type:     pb.HeartbeatResp,
		Hint:     ctxB.Low,
		HintHigh: ctxB.High,
	})
	var observerReply *pb.Message
	for i := range r.msgs {
		if r.msgs[i].Type == pb.ReadIndexResp && r.msgs[i].To == 4 {
			observerReply = &r.msgs[i]
			break
		}
	}
	if observerReply == nil {
		t.Fatal("no ReadIndex response was produced for observer 4")
	}
	emitObserverAssuranceEvent(t, map[string]interface{}{
		"event":              "observer_readindex_reply",
		"request_id":         "observer-read-A",
		"reply_to":           observerReply.To,
		"trigger_from":       uint64(3),
		"trigger_ctx_low":    ctxB.Low,
		"trigger_ctx_high":   ctxB.High,
		"response_ctx_low":   observerReply.Hint,
		"response_ctx_high":  observerReply.HintHigh,
		"response_log_index": observerReply.LogIndex,
		"pending_after":      len(r.readIndex.pending),
	})
}

// TestAssuranceUnknownSenderCannotConfirmReadIndex checks both admission layers
// for a ReadIndex confirmation: the Peer response filter and the leader's remote
// lookup. A heartbeat response from a node absent from every role map must not
// contribute a confirmation, while a known voter's response must confirm.
func TestAssuranceUnknownSenderCannotConfirmReadIndex(t *testing.T) {
	r := newTestRaft(1, []uint64{1, 2, 3}, 5, 1, NewTestLogDB())
	r.becomeFollower(1, NoLeader)
	r.becomeCandidate()
	r.becomeLeader()
	r.remotes[2].tryUpdate(r.log.lastIndex())
	if !r.tryCommit() {
		t.Fatal("failed to commit the leader no-op in its current term")
	}
	p := &Peer{raft: r}
	ctx := pb.SystemCtx{Low: 101, High: 1002}
	p.Handle(pb.Message{
		From:     2,
		To:       1,
		Type:     pb.ReadIndex,
		Hint:     ctx.Low,
		HintHigh: ctx.High,
	})
	queued := len(r.readIndex.pending)
	emitObserverAssuranceEvent(t, map[string]interface{}{
		"event":      "readindex_queued",
		"request_id": "node2-read-A",
		"node_id":    uint64(2),
		"ctx_low":    ctx.Low,
		"queued":     queued,
	})

	// A response from a node that is in no role map, delivered through the Peer
	// admission path.
	r.msgs = nil
	p.Handle(pb.Message{
		From:     4,
		To:       1,
		Type:     pb.HeartbeatResp,
		Hint:     ctx.Low,
		HintHigh: ctx.High,
	})
	emitObserverAssuranceEvent(t, map[string]interface{}{
		"event":         "unknown_sender_peer_path",
		"request_id":    "node2-read-A",
		"sender":        uint64(4),
		"pending_after": len(r.readIndex.pending),
		"replies_after": len(r.msgs),
	})

	// The same response handed straight to the raft state machine, bypassing the
	// Peer filter, so only the leader's remote lookup can reject it.
	r.msgs = nil
	r.Handle(pb.Message{
		From:     4,
		To:       1,
		Type:     pb.HeartbeatResp,
		Hint:     ctx.Low,
		HintHigh: ctx.High,
	})
	emitObserverAssuranceEvent(t, map[string]interface{}{
		"event":         "unknown_sender_raft_path",
		"request_id":    "node2-read-A",
		"sender":        uint64(4),
		"pending_after": len(r.readIndex.pending),
		"replies_after": len(r.msgs),
	})

	// A known voter's response must confirm the same context.
	r.msgs = nil
	p.Handle(pb.Message{
		From:     3,
		To:       1,
		Type:     pb.HeartbeatResp,
		Hint:     ctx.Low,
		HintHigh: ctx.High,
	})
	replies := 0
	for _, m := range r.msgs {
		if m.Type == pb.ReadIndexResp && m.To == 2 {
			replies++
		}
	}
	emitObserverAssuranceEvent(t, map[string]interface{}{
		"event":         "known_voter_response",
		"request_id":    "node2-read-A",
		"sender":        uint64(3),
		"pending_after": len(r.readIndex.pending),
		"replies_to_2":  replies,
	})
}
