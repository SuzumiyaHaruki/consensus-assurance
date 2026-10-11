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

// Generated audit harness. It never changes production logic. It feeds
// proposals carrying conf-change entries through the real proposal path,
// directly into the leader and through a follower's forwarding hop, and
// recovers any panic so that the outcome can be reported verbatim.

func assuranceEmit(t *testing.T, event map[string]any) {
	t.Helper()
	raw, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(raw))
}

type assuranceStepOutcome struct {
	panicked  bool
	recovered string
	msgs      []pb.Message
}

func assuranceStepRecover(r *raft, m pb.Message) (res assuranceStepOutcome) {
	defer func() {
		if v := recover(); v != nil {
			res.panicked = true
			res.recovered = fmt.Sprint(v)
		}
	}()
	_ = r.Step(m)
	res.msgs = r.readMessages()
	return res
}

func TestAssuranceMalformedConfChangeProposal(t *testing.T) {
	cluster := func() (leader, follower *raft) {
		r1 := newTestRaft(1, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
		r2 := newTestRaft(2, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
		r3 := newTestRaft(3, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
		nt := newNetwork(r1, r2, r3)
		nt.send(pb.Message{From: 1, To: 1, Type: pb.MsgHup})
		if r1.state != StateLeader {
			t.Fatalf("node 1 is %v, want %v", r1.state, StateLeader)
		}
		r1.appliedTo(r1.raftLog.committed, 0)
		for _, r := range []*raft{r1, r2, r3} {
			r.readMessages()
		}
		return r1, r2
	}

	probe := func(probeID, scenario string, payload []byte, viaFollower bool) {
		leader, follower := cluster()
		lastBefore := leader.raftLog.lastIndex()
		assuranceEmit(t, map[string]any{
			"event":        "conf_proposal_setup",
			"probe_id":     probeID,
			"scenario":     scenario,
			"via_follower": viaFollower,
			"data_len":     len(payload),
			"leader":       "1",
			"term":         leader.Term,
			"leader_state": leader.state.String(),
			"committed":    leader.raftLog.committed,
			"applied":      leader.raftLog.applied,
		})

		followerPanicked, followerRecovered, followerMsgs := false, "", []pb.Message{}
		forwardedTo := uint64(0)
		target := leader
		if viaFollower {
			res := assuranceStepRecover(follower, pb.Message{From: 2, To: 2, Type: pb.MsgProp,
				Entries: []pb.Entry{{Type: pb.EntryConfChangeV2, Data: payload}}})
			followerPanicked, followerRecovered, followerMsgs = res.panicked, res.recovered, res.msgs
			if len(res.msgs) > 0 {
				forwardedTo = res.msgs[0].To
				res = assuranceStepRecover(leader, res.msgs[0])
			}
			assuranceEmit(t, map[string]any{
				"event":              "conf_proposal_outcome",
				"probe_id":           probeID,
				"scenario":           scenario,
				"via_follower":       true,
				"follower_panicked":  followerPanicked,
				"follower_recovered": followerRecovered,
				"follower_messages":  len(followerMsgs),
				"forwarded_to":       forwardedTo,
				"leader_panicked":    res.panicked,
				"recovered":          res.recovered,
				"last_index_before":  lastBefore,
				"last_index_after":   leader.raftLog.lastIndex(),
				"leader_state":       leader.state.String(),
			})
			if followerPanicked || len(followerMsgs) != 1 {
				t.Fatalf("harness: forwarding hop panicked=%v messages=%d", followerPanicked, len(followerMsgs))
			}
			return
		}

		res := assuranceStepRecover(target, pb.Message{From: 1, To: 1, Type: pb.MsgProp,
			Entries: []pb.Entry{{Type: pb.EntryConfChangeV2, Data: payload}}})
		assuranceEmit(t, map[string]any{
			"event":             "conf_proposal_outcome",
			"probe_id":          probeID,
			"scenario":          scenario,
			"via_follower":      false,
			"follower_panicked": false,
			"follower_messages": 0,
			"forwarded_to":      0,
			"leader_panicked":   res.panicked,
			"recovered":         res.recovered,
			"last_index_before": lastBefore,
			"last_index_after":  leader.raftLog.lastIndex(),
			"leader_state":      leader.state.String(),
		})
	}

	// A proposal whose conf-change payload cannot be unmarshalled, delivered
	// directly to the leader.
	probe("malformed/direct", "malformed_direct", []byte{0xff, 0xff, 0xff, 0xff}, false)
	// The same shape relayed by a follower that forwards proposals.
	probe("malformed/via-follower", "malformed_via_follower", []byte{0xff, 0xff, 0xff, 0xff}, true)
	// Control: a well-formed conf change of the same entry type.
	validCC := pb.ConfChangeV2{Changes: []pb.ConfChangeSingle{{Type: pb.ConfChangeAddNode, NodeID: 4}}}
	valid, err := validCC.Marshal()
	if err != nil {
		t.Fatalf("marshal valid conf change: %v", err)
	}
	probe("valid/direct", "valid_direct", valid, false)
}
