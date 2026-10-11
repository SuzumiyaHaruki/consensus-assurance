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
// plays the embedding application: after election it advances the applied
// index as an application does when it has applied everything committed, and
// it drives the messages the raft instances produce to each other so that a
// proposal can be observed before and after it is committed.

func assuranceEmit(t *testing.T, event map[string]any) {
	t.Helper()
	raw, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(raw))
}

// assuranceClusterWithConfig elects node 1 as leader of {1,2,3}. The optional
// configFunc mirrors the captured Config, so the DisableConfChangeValidation
// control runs through the real constructor instead of a state injection.
func assuranceClusterWithConfig(t *testing.T, configFunc func(*Config)) (leader, follower2, follower3 *raft) {
	t.Helper()
	nt := newNetworkWithConfig(configFunc, nil, nil, nil)
	nt.send(pb.Message{From: 1, To: 1, Type: pb.MsgHup})
	r1 := nt.peers[1].(*raft)
	if r1.state != StateLeader {
		t.Fatalf("node 1 is %v, want %v", r1.state, StateLeader)
	}
	// Application duty: the harness applies everything committed before it
	// starts proposing, exactly as an application advances the applied index.
	r1.appliedTo(r1.raftLog.committed, 0)
	for _, r := range []*raft{r1, nt.peers[2].(*raft), nt.peers[3].(*raft)} {
		r.readMessages()
	}
	return r1, nt.peers[2].(*raft), nt.peers[3].(*raft)
}

// assurancePump delivers every message to the node it addresses and returns
// when the budget is exhausted or the queue is empty.
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

// assuranceCommitAndApply drives the cluster until the leader committed the
// proposed index, then runs the application's type-based apply loop for that
// entry: a conf-change entry is passed to ApplyConfChange, anything else is
// applied as an ordinary entry.
func assuranceCommitAndApply(t *testing.T, leader *raft, nodes map[uint64]*raft, pending []pb.Message, index uint64, cc pb.ConfChangeV2) (committed, confStateChanged, applyPanicked bool, applyError string, voters []uint64) {
	t.Helper()
	pending = assurancePump(t, nodes, pending, 200)
	_ = pending
	committed = leader.raftLog.committed >= index
	ents, err := leader.raftLog.slice(index, index+1, noLimit)
	if err != nil {
		t.Fatalf("slice proposed entry %d: %v", index, err)
	}
	before := leader.trk.ConfState()
	if len(ents) == 1 && (ents[0].Type == pb.EntryConfChange || ents[0].Type == pb.EntryConfChangeV2) {
		func() {
			defer func() {
				if v := recover(); v != nil {
					applyPanicked = true
					applyError = fmt.Sprint(v)
				}
			}()
			_ = leader.applyConfChange(cc)
		}()
	}
	after := leader.trk.ConfState()
	confStateChanged = fmt.Sprint(before) != fmt.Sprint(after)
	voters = after.Voters
	return committed, confStateChanged, applyPanicked, applyError, voters
}

func TestAssuranceConfChangeProposalResult(t *testing.T) {
	emptyCC := pb.ConfChangeV2{}
	addNode := func(id uint64) pb.ConfChangeV2 {
		return pb.ConfChangeV2{Changes: []pb.ConfChangeSingle{{Type: pb.ConfChangeAddNode, NodeID: id}}}
	}

	propose := func(probeID, scenario string, validationEnabled bool, cc pb.ConfChangeV2, proposeSecond bool, secondCC pb.ConfChangeV2) {
		leader, f2, f3 := assuranceClusterWithConfig(t, func(c *Config) {
			c.DisableConfChangeValidation = !validationEnabled
		})
		nodes := map[uint64]*raft{1: leader, 2: f2, 3: f3}
		data, err := cc.Marshal()
		if err != nil {
			t.Fatalf("marshal conf change: %v", err)
		}
		assuranceEmit(t, map[string]any{
			"event":              "conf_change_step",
			"proposal_id":        probeID,
			"scenario":           scenario,
			"validation_enabled": validationEnabled,
			"leader":             "1",
			"term":               leader.Term,
			"leader_state":       leader.state.String(),
			"committed_before":   leader.raftLog.committed,
			"applied_before":     leader.raftLog.applied,
			"pending_conf_index": leader.pendingConfIndex,
			"voters_before":      leader.trk.ConfState().Voters,
		})
		firstType := pb.EntryConfChangeV2
		stepErr := leader.Step(pb.Message{From: 1, To: 1, Type: pb.MsgProp,
			Entries: []pb.Entry{{Type: firstType, Data: data}}})
		firstIndex := leader.raftLog.lastIndex()
		firstEnts, err := leader.raftLog.slice(firstIndex, firstIndex+1, noLimit)
		if err != nil || len(firstEnts) != 1 {
			t.Fatalf("slice appended entry %d: %v (%d entries)", firstIndex, err, len(firstEnts))
		}
		firstEntry := firstEnts[0]
		firstErr, firstErrText := stepErr != nil, fmt.Sprint(stepErr)
		firstMsgs := leader.readMessages()
		pendingAfterFirst := leader.pendingConfIndex

		secondEntryType, secondErr, secondErrText := pb.EntryType(0), false, ""
		secondIndex := uint64(0)
		pendingAfterSecond := pendingAfterFirst
		var secondMsgs []pb.Message
		if proposeSecond {
			secondData, err := secondCC.Marshal()
			if err != nil {
				t.Fatalf("marshal second conf change: %v", err)
			}
			secondErrValue := leader.Step(pb.Message{From: 1, To: 1, Type: pb.MsgProp,
				Entries: []pb.Entry{{Type: pb.EntryConfChangeV2, Data: secondData}}})
			secondErr, secondErrText = secondErrValue != nil, fmt.Sprint(secondErrValue)
			secondIndex = leader.raftLog.lastIndex()
			secondEnts, err := leader.raftLog.slice(secondIndex, secondIndex+1, noLimit)
			if err != nil || len(secondEnts) != 1 {
				t.Fatalf("slice second entry %d: %v", secondIndex, err)
			}
			secondEntryType = secondEnts[0].Type
			pendingAfterSecond = leader.pendingConfIndex
			secondMsgs = leader.readMessages()
		}

		committed, confStateChanged, applyPanicked, applyError, voters :=
			assuranceCommitAndApply(t, leader, nodes, append(firstMsgs, secondMsgs...), firstIndex, cc)

		classification := func(errReported bool, entryType pb.EntryType) string {
			if errReported {
				return "rejected"
			}
			if entryType == pb.EntryConfChange || entryType == pb.EntryConfChangeV2 {
				return "admitted"
			}
			return "silently_replaced"
		}
		event := map[string]any{
			"event":                    "conf_change_proposal",
			"proposal_id":              probeID,
			"scenario":                 scenario,
			"validation_enabled":       validationEnabled,
			"error_reported":           firstErr,
			"error_text":               firstErrText,
			"entry_type":               firstEntry.Type.String(),
			"entry_data_len":           len(firstEntry.Data),
			"proposed_index":           firstIndex,
			"pending_conf_index_after": pendingAfterFirst,
			"pending_conf_index_set":   pendingAfterFirst == firstIndex,
			"outcome_class":            classification(firstErr, firstEntry.Type),
			"committed":                committed,
			"applied_conf_state_changed": confStateChanged,
			"apply_panicked":           applyPanicked,
			"apply_error":              applyError,
			"conf_state_voters_after":  voters,
			"leader_state":             leader.state.String(),
		}
		if proposeSecond {
			event["second_error_reported"] = secondErr
			event["second_error_text"] = secondErrText
			event["second_entry_type"] = secondEntryType.String()
			event["second_outcome_class"] = classification(secondErr, secondEntryType)
			event["second_proposed_index"] = secondIndex
			event["second_pending_conf_index"] = pendingAfterSecond
		}
		assuranceEmit(t, event)
		if probeID == "valid/add-node-4" && (!committed || !confStateChanged) {
			t.Fatalf("control: committed=%v confStateChanged=%v, want true/true", committed, confStateChanged)
		}
	}

	// P1: a conf change that fails propose-time validation in a simple config.
	propose("invalid/empty-change", "empty_change_non_joint", true, emptyCC, false, emptyCC)
	// P2: positive control, a valid single-node addition.
	propose("valid/add-node-4", "valid_add_node", true, addNode(4), false, emptyCC)
	// P3: a valid proposal is accepted, then a second one arrives while the
	// first is still unapplied.
	propose("pending/second-change", "second_change_while_pending", true, addNode(4), true, addNode(5))
	// P4: control with the documented validation bypass.
	propose("disabled/empty-change", "validation_disabled", false, emptyCC, false, emptyCC)
}
