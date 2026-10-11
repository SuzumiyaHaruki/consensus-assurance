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
// MsgReadIndexResp messages of three shapes into a real follower and reports
// whether each shape was accepted, so that the read-index response path's
// validation can be compared with the request path's lack of it.

func assuranceEmit(t *testing.T, event map[string]any) {
	t.Helper()
	raw, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(raw))
}

func TestAssuranceReadIndexRespValidation(t *testing.T) {
	r1 := newTestRaft(1, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r2 := newTestRaft(2, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r3 := newTestRaft(3, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	nt := newNetwork(r1, r2, r3)
	nt.send(pb.Message{From: 1, To: 1, Type: pb.MsgHup})
	if r1.state != StateLeader {
		t.Fatalf("node 1 is %v, want %v", r1.state, StateLeader)
	}
	r1.readMessages()
	r2.readMessages()
	r3.readMessages()

	probe := func(probeID, scenario string, entries []pb.Entry) {
		assuranceEmit(t, map[string]any{
			"event":        "read_index_resp_setup",
			"probe_id":     probeID,
			"scenario":     scenario,
			"node":         "2",
			"node_state":   r2.state.String(),
			"term":         r2.Term,
			"lead":         r2.lead,
			"entries_sent": len(entries),
			"read_index":   7,
		})
		before := len(r2.readStates)
		panicked, recovered := false, ""
		func() {
			defer func() {
				if v := recover(); v != nil {
					panicked = true
					recovered = fmt.Sprint(v)
				}
			}()
			_ = r2.Step(pb.Message{From: 1, To: 2, Type: pb.MsgReadIndexResp,
				Term: r2.Term, Index: 7, Entries: entries})
		}()
		r2.readMessages()
		added := len(r2.readStates) - before
		requestCtx := ""
		if added > 0 {
			requestCtx = string(r2.readStates[len(r2.readStates)-1].RequestCtx)
		}
		assuranceEmit(t, map[string]any{
			"event":              "read_index_resp_outcome",
			"probe_id":           probeID,
			"scenario":           scenario,
			"entries_sent":       len(entries),
			"panicked":           panicked,
			"recovered":          recovered,
			"read_states_added":  added,
			"read_state_index":   readStateIndex(r2),
			"read_state_request_ctx": requestCtx,
			"node_state":         r2.state.String(),
			"term":               r2.Term,
		})
	}

	// A response with no entries carries no request context to match.
	probe("resp/zero-entries", "response_zero_entries", nil)
	// A response with two entries is malformed for this message type.
	probe("resp/two-entries", "response_two_entries", []pb.Entry{{Data: []byte("a")}, {Data: []byte("b")}})
	// The well-formed response carries exactly one entry.
	probe("resp/one-entry", "response_one_entry", []pb.Entry{{Data: []byte("assurance-rctx")}})

	if r2.readStates[len(r2.readStates)-1].RequestCtx == nil {
		t.Fatalf("harness: the accepted response did not carry its request context")
	}
}

func readStateIndex(r *raft) uint64 {
	if len(r.readStates) == 0 {
		return 0
	}
	return r.readStates[len(r.readStates)-1].Index
}
