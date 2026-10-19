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
