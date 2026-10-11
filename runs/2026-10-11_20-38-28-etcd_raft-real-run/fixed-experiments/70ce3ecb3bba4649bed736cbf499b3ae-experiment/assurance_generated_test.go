// Copyright 2025 The etcd Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	pb "go.etcd.io/raft/v3/raftpb"
)

// Generated audit harness. It never changes production logic. It drives the
// real ReadIndex producer and the real replication path of a three-voter
// cluster and reports what each admitted read request was answered with.

func assuranceEmit(t *testing.T, event map[string]any) {
	t.Helper()
	raw, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(raw))
}

func assuranceCluster(t *testing.T) (leader, follower2, follower3 *raft) {
	t.Helper()
	r1 := newTestRaft(1, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r2 := newTestRaft(2, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r3 := newTestRaft(3, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	nt := newNetwork(r1, r2, r3)
	nt.send(pb.Message{From: 1, To: 1, Type: pb.MsgHup})
	if r1.state != StateLeader || !r1.committedEntryInCurrentTerm() {
		t.Fatalf("node 1 state %v committedInTerm %v", r1.state, r1.committedEntryInCurrentTerm())
	}
	for _, r := range []*raft{r1, r2, r3} {
		r.readMessages()
	}
	return r1, r2, r3
}

func assurancePump(t *testing.T, nodes map[uint64]*raft, pending []pb.Message, budget int) []pb.Message {
	t.Helper()
	for len(pending) > 0 && budget > 0 {
		budget--
		m := pending[0]
		pending = pending[1:]
		target, ok := nodes[m.To]
		if !ok {
			t.Fatalf("message %s addressed to unknown node %d", m.Type, m.To)
		}
		if err := target.Step(m); err != nil {
			t.Fatalf("node %d step %s: %v", m.To, m.Type, err)
		}
		pending = append(pending, target.readMessages()...)
	}
	return pending
}

func TestAssuranceReadIndexCoalescedIndex(t *testing.T) {
	probe := func(probeID string, reuseRctx bool) {
		leader, f2, f3 := assuranceCluster(t)
		nodes := map[uint64]*raft{1: leader, 2: f2, 3: f3}
		ctx1 := []byte("assurance-coalesced-rctx-1")
		ctx2 := ctx1
		if !reuseRctx {
			ctx2 = []byte("assurance-coalesced-rctx-2")
		}

		// First admission: follower 2 forwards ReadIndex(ctx1); the leader
		// admits it and broadcasts heartbeats carrying the rctx.
		_ = f2.Step(pb.Message{From: 2, To: 2, Type: pb.MsgReadIndex, Entries: []pb.Entry{{Data: ctx1}}})
		fwd1 := f2.readMessages()
		if len(fwd1) != 1 {
			t.Fatalf("first read index not forwarded: %+v", fwd1)
		}
		_ = leader.Step(fwd1[0])
		heldHeartbeats := leader.readMessages()
		firstAdmissionCommitted := leader.raftLog.committed
		assuranceEmit(t, map[string]any{
			"event":                    "read_index_admission",
			"probe_id":                 probeID,
			"request_id":               "first",
			"reuse_rctx":               reuseRctx,
			"rctx":                     string(ctx1),
			"committed_at_admission":   firstAdmissionCommitted,
			"pending_after":            len(leader.readOnly.pendingReadIndex),
			"queue_after":              len(leader.readOnly.readIndexQueue),
			"leader_state":             leader.state.String(),
		})

		// A write is committed while the first read request is still pending,
		// so the leader's committed index advances past the index recorded for
		// that pending request.
		_ = leader.Step(pb.Message{From: 1, To: 1, Type: pb.MsgProp, Entries: []pb.Entry{{Data: []byte("assurance-write")}}})
		assurancePump(t, nodes, leader.readMessages(), 200)
		committedAfterWrite := leader.raftLog.committed

		// Second admission while the first status is still pending.
		_ = f2.Step(pb.Message{From: 2, To: 2, Type: pb.MsgReadIndex, Entries: []pb.Entry{{Data: ctx2}}})
		fwd2 := f2.readMessages()
		if len(fwd2) != 1 {
			t.Fatalf("second read index not forwarded: %+v", fwd2)
		}
		_ = leader.Step(fwd2[0])
		secondHeartbeats := leader.readMessages()
		secondAdmissionCommitted := leader.raftLog.committed
		assuranceEmit(t, map[string]any{
			"event":                  "read_index_admission",
			"probe_id":               probeID,
			"request_id":             "second",
			"reuse_rctx":             reuseRctx,
			"rctx":                   string(ctx2),
			"committed_at_admission": secondAdmissionCommitted,
			"pending_after":          len(leader.readOnly.pendingReadIndex),
			"queue_after":            len(leader.readOnly.readIndexQueue),
			"leader_state":           leader.state.String(),
		})

		// Deliver real follower acknowledgments for the rctx of both
		// admissions and collect the answers the leader produces.
		acks := []pb.Message{}
		for _, hb := range append(append([]pb.Message{}, heldHeartbeats...), secondHeartbeats...) {
			target, ok := nodes[hb.To]
			if !ok {
				t.Fatalf("heartbeat to unknown node %d", hb.To)
			}
			_ = target.Step(hb)
			acks = append(acks, target.readMessages()...)
		}
		answers := []pb.Message{}
		for _, a := range acks {
			_ = leader.Step(a)
			for _, out := range leader.readMessages() {
				if out.Type == pb.MsgReadIndexResp {
					answers = append(answers, out)
				}
			}
		}
		byRctx := map[string]uint64{}
		for _, a := range answers {
			byRctx[string(a.Entries[0].Data)] = a.Index
		}
		answerIndex, answered := byRctx[string(ctx2)]
		answerRctx := ""
		if answered {
			answerRctx = string(ctx2)
		}
		assuranceEmit(t, map[string]any{
			"event":                          "read_index_answer",
			"probe_id":                       probeID,
			"request_id":                     "second",
			"reuse_rctx":                     reuseRctx,
			"rctx":                           answerRctx,
			"committed_at_first_admission":   firstAdmissionCommitted,
			"committed_at_second_admission":  secondAdmissionCommitted,
			"committed_after_write":          committedAfterWrite,
			"answer_index":                   answerIndex,
			"answers":                        len(answers),
			"answer_index_at_least_admission": answerIndex >= secondAdmissionCommitted,
			"leader_state":                   leader.state.String(),
		})
		// Harness expectation for the observed behaviour: with a reused rctx
		// the second admission has no status of its own, so the single answer
		// carries the first admission's index.
		if reuseRctx && secondAdmissionCommitted > firstAdmissionCommitted {
			if answerIndex >= secondAdmissionCommitted {
				t.Fatalf("expected the coalesced answer to carry the first admission's index, got %d (second admission committed %d)",
					answerIndex, secondAdmissionCommitted)
			}
		}
		if !reuseRctx && answerIndex < secondAdmissionCommitted {
			t.Fatalf("control: distinct rctx answered %d, want >= %d", answerIndex, secondAdmissionCommitted)
		}
	}

	probe("reuse-rctx", true)
	probe("distinct-rctx", false)
}
