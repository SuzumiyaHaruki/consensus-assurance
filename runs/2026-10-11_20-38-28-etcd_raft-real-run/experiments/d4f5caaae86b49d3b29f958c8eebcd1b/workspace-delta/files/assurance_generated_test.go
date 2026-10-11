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

// Generated audit harness. It never changes production logic. It repeats the
// removed-leader probe with a varied timer and delivery schedule instead of a
// fixed round-robin order: the node tick order is rotated each round and the
// delivery order of the produced messages is reversed on alternating rounds.

func assuranceEmit(t *testing.T, event map[string]any) {
	t.Helper()
	raw, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(raw))
}

func TestAssuranceRemovedLeaderVariedSchedule(t *testing.T) {
	run := func(probeID string, stepDownOnRemoval bool, rounds int) {
		nt := newNetworkWithConfig(func(c *Config) {
			c.StepDownOnRemoval = stepDownOnRemoval
		}, nil, nil, nil)
		nt.send(pb.Message{From: 1, To: 1, Type: pb.MsgHup})
		r1 := nt.peers[1].(*raft)
		r2 := nt.peers[2].(*raft)
		r3 := nt.peers[3].(*raft)
		if r1.state != StateLeader {
			t.Fatalf("node 1 is %v, want %v", r1.state, StateLeader)
		}
		r1.appliedTo(r1.raftLog.committed, 0)
		nodes := map[uint64]*raft{1: r1, 2: r2, 3: r3}
		for _, r := range []*raft{r1, r2, r3} {
			r.readMessages()
		}

		pump := func(pending []pb.Message, reverse bool, budget int) []pb.Message {
			for len(pending) > 0 && budget > 0 {
				budget--
				index := 0
				if reverse {
					index = len(pending) - 1
				}
				m := pending[index]
				pending = append(pending[:index], pending[index+1:]...)
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

		removal := pb.ConfChangeV2{Changes: []pb.ConfChangeSingle{{Type: pb.ConfChangeRemoveNode, NodeID: 1}}}
		data, err := removal.Marshal()
		if err != nil {
			t.Fatalf("marshal removal: %v", err)
		}
		assuranceEmit(t, map[string]any{
			"event":                "schedule_setup",
			"probe_id":             probeID,
			"step_down_on_removal": stepDownOnRemoval,
			"rounds":               rounds,
			"leader_state":         r1.state.String(),
			"voters":               r1.trk.ConfState().Voters,
			"committed":            r1.raftLog.committed,
		})
		_ = r1.Step(pb.Message{From: 1, To: 1, Type: pb.MsgProp,
			Entries: []pb.Entry{{Type: pb.EntryConfChangeV2, Data: data}}})
		index := r1.raftLog.lastIndex()
		pending := pump(r1.readMessages(), false, 200)
		removalCommitted := r1.raftLog.committed >= index
		for _, id := range []uint64{1, 2, 3} {
			r := nodes[id]
			if r.raftLog.committed < index {
				continue
			}
			func() {
				defer func() { _ = recover() }()
				_ = r.applyConfChange(removal)
			}()
			r.appliedTo(r.raftLog.committed, 0)
		}

		for i := 0; i < rounds; i++ {
			order := []uint64{1, 2, 3}
			rotated := append(append([]uint64{}, order[i%3:]...), order[:i%3]...)
			reverse := i%2 == 1
			for _, id := range rotated {
				nodes[id].tick()
				pending = append(pending, nodes[id].readMessages()...)
				pending = pump(pending, reverse, 400)
			}
		}

		newLeader := uint64(0)
		for id, r := range nodes {
			if id != 1 && r.state == StateLeader {
				newLeader = id
			}
		}
		states := map[string]string{}
		for id, r := range nodes {
			states[fmt.Sprintf("%d", id)] = r.state.String()
		}
		assuranceEmit(t, map[string]any{
			"event":                "progress_window",
			"probe_id":             probeID,
			"step_down_on_removal": stepDownOnRemoval,
			"rounds":               rounds,
			"schedule":             "rotated tick order with alternating reverse delivery",
			"removal_committed":    removalCommitted,
			"new_leader_elected":   newLeader != 0,
			"new_leader_id":        newLeader,
			"states_after_window":  states,
			"last_index_after":     r1.raftLog.lastIndex(),
			"committed_after":      r1.raftLog.committed,
			"leader_in_config":     r1.trk.Progress[1] != nil,
			"undelivered_messages": len(pending),
			"follower2_elapsed":    r2.electionElapsed,
			"follower3_elapsed":    r3.electionElapsed,
		})
	}

	run("varied/stepdown-false", false, 120)
	run("varied/stepdown-true", true, 120)
}
