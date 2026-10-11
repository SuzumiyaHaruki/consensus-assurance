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

// Generated audit harness. It never changes production logic. The harness also
// plays the embedding application: it drives messages between the real state
// machines, applies committed entries with the documented type-based loop, and
// ticks election/heartbeat timers so that progress can be observed. This
// revision adds an external-trigger phase to the removed-leader probe.

func assuranceEmit(t *testing.T, event map[string]any) {
	t.Helper()
	raw, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(raw))
}

func assuranceClusterWithConfig(t *testing.T, configFunc func(*Config)) (leader, follower2, follower3 *raft) {
	t.Helper()
	nt := newNetworkWithConfig(configFunc, nil, nil, nil)
	nt.send(pb.Message{From: 1, To: 1, Type: pb.MsgHup})
	r1 := nt.peers[1].(*raft)
	if r1.state != StateLeader {
		t.Fatalf("node 1 is %v, want %v", r1.state, StateLeader)
	}
	r1.appliedTo(r1.raftLog.committed, 0)
	for _, r := range []*raft{r1, nt.peers[2].(*raft), nt.peers[3].(*raft)} {
		r.readMessages()
	}
	return r1, nt.peers[2].(*raft), nt.peers[3].(*raft)
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

func assuranceStates(nodes map[uint64]*raft) map[string]string {
	out := map[string]string{}
	for id, r := range nodes {
		out[fmt.Sprintf("%d", id)] = r.state.String()
	}
	return out
}

func assuranceOtherLeader(nodes map[uint64]*raft) (uint64, *raft, bool) {
	for id, r := range nodes {
		if id != 1 && r.state == StateLeader {
			return id, r, true
		}
	}
	return 0, nil, false
}

func TestAssuranceRemovedLeaderProgress(t *testing.T) {
	run := func(probeID string, stepDownOnRemoval bool, ticks, postTicks int) {
		leader, f2, f3 := assuranceClusterWithConfig(t, func(c *Config) {
			c.StepDownOnRemoval = stepDownOnRemoval
		})
		nodes := map[uint64]*raft{1: leader, 2: f2, 3: f3}

		removal := pb.ConfChangeV2{Changes: []pb.ConfChangeSingle{{Type: pb.ConfChangeRemoveNode, NodeID: 1}}}
		data, err := removal.Marshal()
		if err != nil {
			t.Fatalf("marshal removal: %v", err)
		}
		propErr := leader.Step(pb.Message{From: 1, To: 1, Type: pb.MsgProp,
			Entries: []pb.Entry{{Type: pb.EntryConfChangeV2, Data: data}}})
		index := leader.raftLog.lastIndex()
		assurancePump(t, nodes, leader.readMessages(), 200)
		committed := leader.raftLog.committed >= index

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
		assuranceEmit(t, map[string]any{
			"event":                   "removal_applied",
			"probe_id":                probeID,
			"step_down_on_removal":    stepDownOnRemoval,
			"proposal_error":          fmt.Sprint(propErr),
			"proposed_index":          index,
			"removal_committed":       committed,
			"leader_state":            leader.state.String(),
			"leader_in_configuration": leader.trk.Progress[1] != nil,
			"voters_after_removal":    leader.trk.ConfState().Voters,
			"states_after_removal":    assuranceStates(nodes),
		})

		lastBefore := leader.raftLog.lastIndex()
		leaderProposeErr := leader.Step(pb.Message{From: 1, To: 1, Type: pb.MsgProp,
			Entries: []pb.Entry{{Data: []byte("assurance-write-1")}}})
		leader.readMessages()
		followerProposeErr := f2.Step(pb.Message{From: 2, To: 2, Type: pb.MsgProp,
			Entries: []pb.Entry{{Data: []byte("assurance-write-2")}}})
		forwarded := f2.readMessages()
		forwardedType, forwardedTo := pb.MsgProp, uint64(0)
		if len(forwarded) > 0 {
			forwardedType, forwardedTo = forwarded[0].Type, forwarded[0].To
			_ = leader.Step(forwarded[0])
		}
		leader.readMessages()

		assuranceEmit(t, map[string]any{
			"event":                   "progress_setup",
			"probe_id":                probeID,
			"step_down_on_removal":    stepDownOnRemoval,
			"ticks":                   ticks,
			"leader_state":            leader.state.String(),
			"leader_in_configuration": leader.trk.Progress[1] != nil,
			"voters":                  leader.trk.ConfState().Voters,
			"last_index":              leader.raftLog.lastIndex(),
			"committed":               leader.raftLog.committed,
		})
		pending := []pb.Message{}
		for i := 0; i < ticks; i++ {
			for _, id := range []uint64{1, 2, 3} {
				nodes[id].tick()
				pending = append(pending, nodes[id].readMessages()...)
				pending = assurancePump(t, nodes, pending, 400)
			}
		}
		_, _, elected := assuranceOtherLeader(nodes)
		assuranceEmit(t, map[string]any{
			"event":                      "progress_window",
			"probe_id":                   probeID,
			"step_down_on_removal":       stepDownOnRemoval,
			"ticks":                      ticks,
			"leader_propose_error":       fmt.Sprint(leaderProposeErr),
			"follower_propose_error":     fmt.Sprint(followerProposeErr),
			"follower_forwarded_type":    forwardedType.String(),
			"follower_forwarded_to":      forwardedTo,
			"last_index_before":          lastBefore,
			"last_index_after":           leader.raftLog.lastIndex(),
			"committed_after":            leader.raftLog.committed,
			"states_after_window":        assuranceStates(nodes),
			"new_leader_elected":         elected,
			"follower2_election_elapsed": f2.electionElapsed,
			"follower3_election_elapsed": f3.electionElapsed,
			"undelivered_messages":       len(pending),
		})

		if stepDownOnRemoval {
			return
		}

		// Read path while the ineligible leader is still leading.
		readCtx := []byte("assurance-removed-leader-read")
		_ = f2.Step(pb.Message{From: 2, To: 2, Type: pb.MsgReadIndex, Entries: []pb.Entry{{Data: readCtx}}})
		fwd := f2.readMessages()
		if len(fwd) != 1 {
			t.Fatalf("read index was not forwarded: %+v", fwd)
		}
		_ = leader.Step(fwd[0])
		acks := []pb.Message{}
		for _, m := range leader.readMessages() {
			target, ok := nodes[m.To]
			if !ok {
				t.Fatalf("heartbeat to unknown node %d", m.To)
			}
			_ = target.Step(m)
			acks = append(acks, target.readMessages()...)
		}
		readAnswers := 0
		if len(acks) > 0 {
			_ = leader.Step(acks[0])
			for _, out := range leader.readMessages() {
				if out.Type == pb.MsgReadIndexResp {
					readAnswers++
				}
			}
		}
		assuranceEmit(t, map[string]any{
			"event":                    "removed_leader_read",
			"probe_id":                 probeID,
			"scenario":                 "removed_leader_read",
			"acks_from_current_voters": 1,
			"read_answers":             readAnswers,
			"leader_state":             leader.state.String(),
			"voters":                   leader.trk.ConfState().Voters,
		})
		quorumAnswers := readAnswers
		for _, a := range acks[1:] {
			_ = leader.Step(a)
			for _, out := range leader.readMessages() {
				if out.Type == pb.MsgReadIndexResp {
					quorumAnswers++
				}
			}
		}
		assuranceEmit(t, map[string]any{
			"event":                    "removed_leader_read",
			"probe_id":                 probeID,
			"scenario":                 "removed_leader_read",
			"acks_from_current_voters": len(acks),
			"read_answers":             quorumAnswers,
			"leader_state":             leader.state.String(),
			"voters":                   leader.trk.ConfState().Voters,
		})

		// External-trigger phase: an eligible voter campaigns explicitly (the
		// MsgHup path a forced election or operator action uses), and the
		// harness then proposes on whichever eligible node takes leadership.
		assuranceEmit(t, map[string]any{
			"event":        "trigger_setup",
			"probe_id":     probeID,
			"scenario":     "external_campaign",
			"states":       assuranceStates(nodes),
			"voters":       f2.trk.ConfState().Voters,
			"leader_state": leader.state.String(),
			"committed":    leader.raftLog.committed,
		})
		_ = f2.Step(pb.Message{From: 2, Type: pb.MsgHup})
		pending = append(pending, f2.readMessages()...)
		pending = assurancePump(t, nodes, pending, 400)
		for i := 0; i < postTicks; i++ {
			for _, id := range []uint64{1, 2, 3} {
				nodes[id].tick()
				pending = append(pending, nodes[id].readMessages()...)
				pending = assurancePump(t, nodes, pending, 400)
			}
		}
		newID, newLeader, electedAfterTrigger := assuranceOtherLeader(nodes)
		proposalCommitted := false
		lastIndexBeforeProposal := uint64(0)
		if electedAfterTrigger {
			lastIndexBeforeProposal = newLeader.raftLog.lastIndex()
			_ = newLeader.Step(pb.Message{From: newID, To: newID, Type: pb.MsgProp,
				Entries: []pb.Entry{{Data: []byte("assurance-post-trigger-write")}}})
			pending = append(pending, newLeader.readMessages()...)
			pending = assurancePump(t, nodes, pending, 400)
			proposalCommitted = newLeader.raftLog.committed > lastIndexBeforeProposal
		}
		assuranceEmit(t, map[string]any{
			"event":                     "post_trigger_progress",
			"probe_id":                  probeID,
			"scenario":                  "external_campaign",
			"post_ticks":                postTicks,
			"new_leader_id":             newID,
			"new_leader_elected":        electedAfterTrigger,
			"proposal_committed":        proposalCommitted,
			"last_index_before_proposal": lastIndexBeforeProposal,
			"states_after_trigger":      assuranceStates(nodes),
			"undelivered_messages":      len(pending),
		})
	}

	run("stepdown-false", false, 80, 40)
	run("stepdown-true", true, 80, 40)
}
