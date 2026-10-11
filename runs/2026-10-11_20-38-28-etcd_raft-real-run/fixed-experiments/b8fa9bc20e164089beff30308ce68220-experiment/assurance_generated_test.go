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
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	pb "go.etcd.io/raft/v3/raftpb"
)

// Generated audit harness. It never changes production logic. It drives one
// voter through the Node API while two other voters are bare raft instances, so
// that the proposal path of a node which applied its own removal is observable
// without touching raft state from a racing goroutine.

func assuranceEmit(t *testing.T, event map[string]any) {
	t.Helper()
	raw, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(raw))
}

func TestAssuranceNodeProposeAfterRemoval(t *testing.T) {
	const callTimeout = 200 * time.Millisecond

	s1 := newTestMemoryStorage(withPeers(1, 2, 3))
	r1 := newTestRaft(1, 10, 1, s1)
	s2 := newTestMemoryStorage(withPeers(1, 2, 3))
	r2 := newTestRaft(2, 10, 1, s2)
	s3 := newTestMemoryStorage(withPeers(1, 2, 3))
	rn3 := newTestRawNode(3, 10, 1, s3)
	n3 := newNode(rn3)

	bare := map[uint64]*raft{1: r1, 2: r2}
	var pending []pb.Message

	go n3.run()
	defer n3.Stop()

	// Deliver every message to the instance it addresses; node 3 receives its
	// messages through the Node API.
	pump := func(budget int) {
		for len(pending) > 0 && budget > 0 {
			budget--
			m := pending[0]
			pending = pending[1:]
			if m.To == 3 {
				_ = n3.Step(context.TODO(), m)
				continue
			}
			r, ok := bare[m.To]
			if !ok {
				t.Fatalf("message %s addressed to unknown node %d", m.Type, m.To)
			}
			if err := r.Step(m); err != nil {
				t.Fatalf("node %d step %s: %v", m.To, m.Type, err)
			}
			pending = append(pending, r.readMessages()...)
		}
	}
	// drive hands the Node's Readys back and moves everything it produced into
	// the delivery queue until the condition holds or the deadline passes.
	drive := func(done func() bool, limit time.Duration) {
		deadline := time.Now().Add(limit)
		for {
			select {
			case rd := <-n3.Ready():
				s3.Append(rd.Entries)
				for _, e := range rd.CommittedEntries {
					if e.Type == pb.EntryConfChangeV2 || e.Type == pb.EntryConfChange {
						var cc pb.ConfChangeV2
						if err := cc.Unmarshal(e.Data); err != nil {
							t.Fatalf("unmarshal conf change: %v", err)
						}
						_ = n3.ApplyConfChange(cc)
					}
				}
				pending = append(pending, rd.Messages...)
				n3.Advance()
			case <-time.After(3 * time.Millisecond):
			}
			pump(500)
			if done() {
				return
			}
			if time.Now().After(deadline) {
				t.Fatalf("application loop timed out")
			}
		}
	}

	// Elect node 1 as a bare leader and let node 3 follow it.
	r1.becomeCandidate()
	r1.becomeLeader()
	r1.bcastAppend()
	pending = append(pending, r1.readMessages()...)
	drive(func() bool { return r1.raftLog.committed >= 1 && r2.raftLog.committed >= 1 }, 5*time.Second)
	assuranceEmit(t, map[string]any{
		"event":            "node_setup",
		"probe_id":         "member",
		"leader":           "1",
		"term":             r1.Term,
		"committed":        r1.raftLog.committed,
		"node3_in_config":  true,
		"node3_state":      "StateFollower",
		"call_timeout_ms":  callTimeout.Milliseconds(),
	})

	// Control: a proposal made through the Node API while node 3 is a member.
	{
		ctx, cancel := context.WithTimeout(context.Background(), callTimeout)
		start := time.Now()
		err := n3.Propose(ctx, []byte("assurance-member-write"))
		elapsed := time.Since(start)
		cancel()
		pump(500)
		blocked := fmt.Sprint(err) == context.DeadlineExceeded.Error() && elapsed >= callTimeout/2
		assuranceEmit(t, map[string]any{
			"event":                  "node_propose",
			"probe_id":               "member",
			"scenario":               "member",
			"error_text":             fmt.Sprint(err),
			"elapsed_ms":             elapsed.Milliseconds(),
			"timeout_ms":             callTimeout.Milliseconds(),
			"blocked_until_deadline": blocked,
			"node3_in_config":        true,
		})
		if err != nil {
			t.Fatalf("control proposal on a member node returned %v", err)
		}
	}

	// Remove node 3 from the configuration through the leader, then let node 3's
	// application apply the committed entry.
	removal := pb.ConfChangeV2{Changes: []pb.ConfChangeSingle{{Type: pb.ConfChangeRemoveNode, NodeID: 3}}}
	data, err := removal.Marshal()
	if err != nil {
		t.Fatalf("marshal removal: %v", err)
	}
	if err := r1.Step(pb.Message{From: 1, To: 1, Type: pb.MsgProp,
		Entries: []pb.Entry{{Type: pb.EntryConfChangeV2, Data: data}}}); err != nil {
		t.Fatalf("propose removal on the leader: %v", err)
	}
	pending = append(pending, r1.readMessages()...)
	drive(func() bool { return rn3.raft.trk.Progress[3] == nil }, 5*time.Second)
	assuranceEmit(t, map[string]any{
		"event":           "self_removal_applied",
		"probe_id":        "removed",
		"node3_in_config": rn3.raft.trk.Progress[3] != nil,
		"voters":          rn3.raft.trk.ConfState().Voters,
		"node3_lead":      rn3.raft.lead,
		"node3_state":     rn3.raft.state.String(),
		"committed":       rn3.raft.raftLog.committed,
	})

	// Witness: a proposal made through the Node API after node 3 applied its
	// own removal.
	{
		ctx, cancel := context.WithTimeout(context.Background(), callTimeout)
		start := time.Now()
		err := n3.Propose(ctx, []byte("assurance-removed-write"))
		elapsed := time.Since(start)
		cancel()
		blocked := fmt.Sprint(err) == context.DeadlineExceeded.Error() && elapsed >= callTimeout/2
		assuranceEmit(t, map[string]any{
			"event":                  "node_propose",
			"probe_id":               "removed",
			"scenario":               "removed",
			"error_text":             fmt.Sprint(err),
			"elapsed_ms":             elapsed.Milliseconds(),
			"timeout_ms":             callTimeout.Milliseconds(),
			"blocked_until_deadline": blocked,
			"node3_in_config":        rn3.raft.trk.Progress[3] != nil,
		})
		if !blocked {
			t.Fatalf("expected the removed node's proposal to block until the deadline, got %v after %v", err, elapsed)
		}
	}
}
