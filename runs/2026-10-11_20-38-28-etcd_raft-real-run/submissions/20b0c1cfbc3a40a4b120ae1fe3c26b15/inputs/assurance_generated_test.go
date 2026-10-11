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
// read-index producer of a real leader whose first entry in its term has not
// been committed yet, which is the path that queues read requests.

func assuranceEmit(t *testing.T, event map[string]any) {
	t.Helper()
	raw, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(raw))
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

func TestAssuranceReadIndexQueuedUntilTermCommit(t *testing.T) {
	r1 := newTestRaft(1, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r2 := newTestRaft(2, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r3 := newTestRaft(3, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	nodes := map[uint64]*raft{1: r1, 2: r2, 3: r3}

	// Become leader without letting any follower acknowledge the new entry, so
	// the leader has no committed entry in its term yet. This is the state the
	// library reaches right after an election before the empty entry commits.
	r1.becomeCandidate()
	r1.becomeLeader()
	r1.bcastAppend()
	firstEntry := r1.readMessages() // MsgApp carrying the empty entry, plus self-ack processing
	committedInTerm := r1.committedEntryInCurrentTerm()

	ctx := []byte("assurance-queued-read")
	_ = r1.Step(pb.Message{From: 1, To: 1, Type: pb.MsgReadIndex, Entries: []pb.Entry{{Data: ctx}}})
	queuedMsgs := r1.readMessages()
	assuranceEmit(t, map[string]any{
		"event":                     "read_index_queued",
		"request_id":                "queued",
		"scenario":                  "queued_before_term_commit",
		"committed_in_term":         committedInTerm,
		"committed":                 r1.raftLog.committed,
		"queued_after":              len(r1.pendingReadIndexMessages),
		"heartbeats_emitted":        len(queuedMsgs),
		"read_states_after":         len(r1.readStates),
		"leader_state":              r1.state.String(),
		"term":                      r1.Term,
	})

	// The application delivers the replicated entry; the followers acknowledge
	// it and the resulting commit is the leader's first commit in its term.
	pending := assurancePump(t, nodes, firstEntry, 100)
	assuranceEmit(t, map[string]any{
		"event":                  "read_index_released",
		"request_id":             "queued",
		"scenario":               "queued_before_term_commit",
		"committed":              r1.raftLog.committed,
		"committed_in_term":      r1.committedEntryInCurrentTerm(),
		"queued_after":           len(r1.pendingReadIndexMessages),
		"read_states_after":      len(r1.readStates),
		"delivered":              len(r1.readStates) == 1,
		"read_state_index":       readStateIndex(r1),
		"undelivered_messages":   len(pending),
		"leader_state":           r1.state.String(),
		"term":                   r1.Term,
	})

	// Contrast: once the leader has committed an entry in its term, a further
	// read request is answered immediately without queueing.
	before := len(r1.readStates)
	_ = r1.Step(pb.Message{From: 1, To: 1, Type: pb.MsgReadIndex, Entries: []pb.Entry{{Data: []byte("assurance-immediate-read")}}})
	immediateMsgs := r1.readMessages()
	acks := []pb.Message{}
	for _, m := range immediateMsgs {
		target, ok := nodes[m.To]
		if !ok {
			t.Fatalf("immediate heartbeat to unknown node %d", m.To)
		}
		_ = target.Step(m)
		acks = append(acks, target.readMessages()...)
	}
	for _, a := range acks {
		_ = r1.Step(a)
	}
	r1.readMessages()
	assuranceEmit(t, map[string]any{
		"event":             "read_index_immediate",
		"request_id":        "immediate",
		"scenario":          "after_term_commit",
		"queued_after":      len(r1.pendingReadIndexMessages),
		"read_states_added": len(r1.readStates) - before,
		"heartbeats":        len(immediateMsgs),
		"acks_from_voters":  len(acks),
		"delivered":         len(r1.readStates) > before,
		"committed":         r1.raftLog.committed,
		"leader_state":      r1.state.String(),
	})

	if committedInTerm {
		t.Fatalf("harness precondition failed: leader already committed in term %d", r1.Term)
	}
	if len(r1.readStates) < 2 {
		t.Fatalf("expected both read requests to be delivered, got %d read states", len(r1.readStates))
	}
}

func readStateIndex(r *raft) uint64 {
	if len(r.readStates) == 0 {
		return 0
	}
	return r.readStates[len(r.readStates)-1].Index
}
