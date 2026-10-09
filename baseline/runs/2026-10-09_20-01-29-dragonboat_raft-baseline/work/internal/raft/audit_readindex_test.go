package raft

import (
	pb "github.com/lni/dragonboat/v3/raftpb"
	"testing"
)

// Uses the existing in-memory storage fixture and unmodified Raft handlers.
// A later heartbeat can be acknowledged before an earlier heartbeat: RPC
// ordering is not a requirement of Raft.
func TestAuditBatchedRemoteReadContexts(t *testing.T) {
	for _, sameRequester := range []bool{false, true} {
		name := "different_followers"
		if sameRequester {
			name = "same_follower"
		}
		t.Run(name, func(t *testing.T) {
			peers := []uint64{1, 2, 3}
			nodes := map[uint64]*raft{}
			for _, id := range peers {
				nodes[id] = newTestRaft(id, peers, 10, 1, NewTestLogDB())
			}
			leader := nodes[1]
			leader.becomeCandidate()
			leader.becomeLeader()
			// Replicate and commit the leader's current-term no-op using real replies.
			leader.broadcastReplicateMessage()
			queue := leader.readMessages()
			for len(queue) > 0 {
				m := queue[0]
				queue = queue[1:]
				nodes[m.To].Handle(m)
				queue = append(queue, nodes[m.To].readMessages()...)
			}
			if !leader.hasCommittedEntryAtCurrentTerm() {
				t.Fatal("setup did not commit no-op")
			}
			second := uint64(3)
			if sameRequester {
				second = 2
			}
			requests := []pb.Message{
				{Type: pb.ReadIndex, From: 2, Hint: 101, HintHigh: 30},
				{Type: pb.ReadIndex, From: second, Hint: 202, HintHigh: 30},
			}
			var latest []pb.Message
			for _, req := range requests {
				nodes[req.From].Handle(req)
				forwarded := nodes[req.From].readMessages()
				for _, m := range forwarded {
					leader.Handle(m)
				}
				latest = leader.readMessages() // Delay the earlier heartbeat round.
			}
			// Deliver one actual heartbeat and its actual reply from the later round.
			for _, hb := range latest {
				if hb.Type == pb.Heartbeat && hb.To == 2 {
					nodes[2].Handle(hb)
					for _, reply := range nodes[2].readMessages() {
						leader.Handle(reply)
					}
					break
				}
			}
			responses := leader.readMessages()
			for _, resp := range responses {
				if resp.Type == pb.ReadIndexResp {
					t.Logf("response: to=%d context=(%d,%d) index=%d", resp.To, resp.Hint, resp.HintHigh, resp.LogIndex)
					nodes[resp.To].Handle(resp)
				}
			}
			t.Logf("leader pending requests after confirmation: %d", len(leader.readIndex.pending))
			for _, req := range requests {
				found := false
				for _, ready := range nodes[req.From].readyToRead {
					if ready.SystemCtx.Low == req.Hint && ready.SystemCtx.High == req.HintHigh {
						found = true
					}
				}
				if !found {
					t.Errorf("confirmed read context (%d,%d) never returned to requesting node %d", req.Hint, req.HintHigh, req.From)
				}
			}
		})
	}
}
