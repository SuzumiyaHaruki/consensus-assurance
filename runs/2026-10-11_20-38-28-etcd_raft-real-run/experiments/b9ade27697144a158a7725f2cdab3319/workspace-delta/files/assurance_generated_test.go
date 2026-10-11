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

// Generated audit harness. It never changes production logic. It proposes a
// configuration change through the real MsgProp path, commits it, and then
// applies it through the documented application path, recovering any panic the
// application would otherwise propagate.

func assuranceEmit(t *testing.T, event map[string]any) {
	t.Helper()
	raw, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(raw))
}

func TestAssuranceConfChangeApplyPanic(t *testing.T) {
	probe := func(probeID, scenario string, voters []uint64, cc pb.ConfChangeV2) {
		storage := newTestMemoryStorage(withPeers(voters...))
		r := newTestRaft(1, 10, 1, storage)
		r.becomeCandidate()
		r.becomeLeader()
		r.appliedTo(r.raftLog.committed, 0)
		r.readMessages()

		data, err := cc.Marshal()
		if err != nil {
			t.Fatalf("marshal conf change: %v", err)
		}
		assuranceEmit(t, map[string]any{
			"event":              "conf_change_setup",
			"probe_id":           probeID,
			"scenario":           scenario,
			"voters_before":      r.trk.ConfState().Voters,
			"pending_conf_index": r.pendingConfIndex,
			"applied":            r.raftLog.applied,
			"committed":          r.raftLog.committed,
			"node_state":         r.state.String(),
			"term":               r.Term,
		})

		stepErr := r.Step(pb.Message{From: 1, To: 1, Type: pb.MsgProp,
			Entries: []pb.Entry{{Type: pb.EntryConfChangeV2, Data: data}}})
		index := r.raftLog.lastIndex()
		// Single-voter cluster: the leader's own acknowledgment is the quorum,
		// so the entry becomes committed once it is appended and the self-ack
		// is processed.
		r.readMessages()
		committed := r.raftLog.committed >= index

		panicked, recovered := false, ""
		func() {
			defer func() {
				if v := recover(); v != nil {
					panicked = true
					recovered = fmt.Sprint(v)
				}
			}()
			_ = r.applyConfChange(cc)
		}()
		assuranceEmit(t, map[string]any{
			"event":          "conf_change_apply",
			"probe_id":       probeID,
			"scenario":       scenario,
			"proposal_error": fmt.Sprint(stepErr),
			"proposed_index": index,
			"committed":      committed,
			"panicked":       panicked,
			"recovered":      recovered,
			"voters_after":   r.trk.ConfState().Voters,
			"node_state":     r.state.String(),
			"term":           r.Term,
		})
		if !committed {
			t.Fatalf("probe %s: the proposed conf change did not commit (index %d, committed %d)",
				probeID, index, r.raftLog.committed)
		}
	}

	probe("remove-last-voter", "remove_last_voter", []uint64{1}, pb.ConfChangeV2{
		Changes: []pb.ConfChangeSingle{{Type: pb.ConfChangeRemoveNode, NodeID: 1}},
	})
	probe("add-voter-control", "add_voter_control", []uint64{1}, pb.ConfChangeV2{
		Changes: []pb.ConfChangeSingle{{Type: pb.ConfChangeAddNode, NodeID: 2}},
	})
}
