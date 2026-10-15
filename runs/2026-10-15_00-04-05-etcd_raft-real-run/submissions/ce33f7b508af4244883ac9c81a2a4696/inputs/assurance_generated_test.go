package raft_test

import (
	"encoding/json"
	"fmt"
	"testing"

	"go.etcd.io/raft/v3"
	pb "go.etcd.io/raft/v3/raftpb"
)

// TestAssuranceInboundForgetLeader probes whether a message of a type that only
// the local ForgetLeader API produces can reach the follower state machine when
// it arrives through the documented inbound path (RawNode.Step), and whether the
// resulting loss of the leader context changes how the same follower answers a
// candidate's pre-vote request while the leader is still alive.
func TestAssuranceInboundForgetLeader(t *testing.T) {
	emit := func(ev map[string]any) {
		b, err := json.Marshal(ev)
		if err != nil {
			t.Fatalf("marshal event: %v", err)
		}
		fmt.Println("CA_EVENT " + string(b))
	}
	errString := func(err error) string {
		if err == nil {
			return ""
		}
		return err.Error()
	}
	drain := func(rn *raft.RawNode) raft.Ready {
		rd := rn.Ready()
		rn.Advance(rd)
		return rd
	}
	lead := func(rn *raft.RawNode) uint64 { return rn.BasicStatus().SoftState.Lead }
	find := func(rd raft.Ready, typ pb.MessageType, to uint64) []*pb.Message {
		var out []*pb.Message
		for _, m := range rd.Messages {
			if m.GetType() == typ && m.GetTo() == to {
				out = append(out, m)
			}
		}
		return out
	}
	// All three voters share the same log prefix (index=10, term=1), so a
	// campaign by node 3 is log-up-to-date with respect to node 2: the only
	// reason for node 2 to withhold support is the lease it holds after hearing
	// from the live leader 1.
	newNode := func(id uint64) *raft.RawNode {
		ms := raft.NewMemoryStorage()
		snap := &pb.Snapshot{Metadata: &pb.SnapshotMetadata{
			Index:     new(uint64(10)),
			Term:      new(uint64(1)),
			ConfState: &pb.ConfState{Voters: []uint64{1, 2, 3}},
		}}
		if err := ms.ApplySnapshot(snap); err != nil {
			t.Fatalf("apply snapshot: %v", err)
		}
		if err := ms.SetHardState(&pb.HardState{Term: new(uint64(1)), Commit: new(uint64(10))}); err != nil {
			t.Fatalf("set hard state: %v", err)
		}
		rn, err := raft.NewRawNode(&raft.Config{
			ID:            id,
			ElectionTick:  10,
			HeartbeatTick: 1,
			Storage:       ms,
			MaxSizePerMsg: 1 << 20,
			MaxInflightMsgs: 256,
			CheckQuorum:   true,
			PreVote:       true,
		})
		if err != nil {
			t.Fatalf("new raw node %d: %v", id, err)
		}
		return rn
	}

	leader, follower, other := newNode(1), newNode(2), newNode(3)

	// Produce a real election: node 1 campaigns, voters 2 and 3 answer, and the
	// resulting messages travel through the documented inbound path.
	if err := leader.Campaign(); err != nil {
		t.Fatalf("campaign: %v", err)
	}
	for _, m := range drain(leader).Messages {
		switch m.GetTo() {
		case 2:
			if err := follower.Step(m); err != nil {
				t.Fatalf("step vote request on 2: %v", err)
			}
		case 3:
			if err := other.Step(m); err != nil {
				t.Fatalf("step vote request on 3: %v", err)
			}
		}
	}
	for _, rn := range []*raft.RawNode{follower, other} {
		for _, m := range drain(rn).Messages {
			if err := leader.Step(m); err != nil {
				t.Fatalf("step vote response on 1: %v", err)
			}
		}
	}
	// Replicate node 1's term-2 entry and feed the acknowledgements back, so the
	// leader is established from the followers' point of view.
	for _, m := range drain(leader).Messages {
		switch m.GetTo() {
		case 2:
			if err := follower.Step(m); err != nil {
				t.Fatalf("step append on 2: %v", err)
			}
		case 3:
			if err := other.Step(m); err != nil {
				t.Fatalf("step append on 3: %v", err)
			}
		}
	}
	for _, rn := range []*raft.RawNode{follower, other} {
		for _, m := range drain(rn).Messages {
			if err := leader.Step(m); err != nil {
				t.Fatalf("step append response on 1: %v", err)
			}
		}
	}
	drain(leader)

	// One heartbeat tick makes the live leader 1 produce a real heartbeat, which
	// is delivered to follower 2 exactly once. This establishes 2's leader
	// context (lead=1) and its election-timeout lease.
	leader.Tick()
	tick := drain(leader)
	heartbeats := find(tick, pb.MsgHeartbeat, 2)
	if len(heartbeats) != 1 {
		t.Fatalf("expected one heartbeat for node 2, got %d", len(heartbeats))
	}
	// Node 3 hears the same heartbeat, but its delivery is not part of the
	// comparison below; it only gives node 3 a live leader context of its own.
	for _, m := range find(tick, pb.MsgHeartbeat, 3) {
		if err := other.Step(m); err != nil {
			t.Fatalf("step heartbeat on 3: %v", err)
		}
	}
	hb := heartbeats[0]
	if err := follower.Step(hb); err != nil {
		t.Fatalf("step heartbeat on 2: %v", err)
	}
	emit(map[string]any{
		"event": "heartbeat_delivered", "to": 2, "sender": 1,
		"term": hb.GetTerm(), "commit": hb.GetCommit(), "lead_after": lead(follower),
	})

	// The intended producer of "forget the leader" is the local API, applied to
	// a follower that considers the leader live.
	otherBefore := lead(other)
	otherErr := other.ForgetLeader()
	emit(map[string]any{
		"event": "local_forget_leader_api", "node": 3, "lead_before": otherBefore,
		"lead_after": lead(other), "step_error": errString(otherErr),
	})

	// Control: a message type that is classified local, arriving from a peer
	// through the same inbound path, is rejected and changes nothing.
	localErr := follower.Step(&pb.Message{
		Type: pb.MsgCheckQuorum.Enum(), From: new(uint64(3)), To: new(uint64(2)),
	})
	emit(map[string]any{
		"event": "inbound_local_msg", "to": 2, "sender": 3, "type": "MsgCheckQuorum",
		"step_error": errString(localErr), "lead_after": lead(follower),
	})

	// A real candidate (node 3) produces a real MsgPreVote request, which is
	// delivered to follower 2 verbatim.
	if err := other.Campaign(); err != nil {
		t.Fatalf("campaign 3: %v", err)
	}
	preVotes := find(drain(other), pb.MsgPreVote, 2)
	if len(preVotes) == 0 {
		t.Fatal("expected a pre-vote request for node 2")
	}
	pv := preVotes[0]

	// Control: with the leader context intact, the pre-vote is ignored (the
	// lease protection), so no response message is produced.
	if err := follower.Step(pv); err != nil {
		t.Fatalf("step pre-vote on 2 (under lease): %v", err)
	}
	rd := drain(follower)
	emit(map[string]any{
		"event": "prevote_outcome", "to": 2, "candidate": 3, "phase": "under_lease",
		"candidate_term": pv.GetTerm(), "lead": lead(follower),
		"responded":   len(find(rd, pb.MsgPreVoteResp, 3)) > 0,
		"granted":     len(find(rd, pb.MsgPreVoteResp, 3)) > 0 && !find(rd, pb.MsgPreVoteResp, 3)[0].GetReject(),
		"forget_accepted": false,
	})

	// The forged inbound message: a peer (node 3) sends the message type that
	// only the local ForgetLeader API produces, in the wire form a peer would
	// produce (no term field, sender 3, receiver 2).
	forgedErr := follower.Step(&pb.Message{
		Type: pb.MsgForgetLeader.Enum(), From: new(uint64(3)), To: new(uint64(2)),
	})
	emit(map[string]any{
		"event": "inbound_forget_leader", "to": 2, "sender": 3, "transport": "RawNode.Step",
		"accepted": forgedErr == nil, "step_error": errString(forgedErr), "lead_after": lead(follower),
	})

	// The same pre-vote request is delivered again after the inbound message.
	if err := follower.Step(pv); err != nil {
		t.Fatalf("step pre-vote on 2 (after forget): %v", err)
	}
	rd2 := drain(follower)
	resp2 := find(rd2, pb.MsgPreVoteResp, 3)
	emit(map[string]any{
		"event": "prevote_outcome", "to": 2, "candidate": 3, "phase": "after_forget",
		"candidate_term": pv.GetTerm(), "lead": lead(follower),
		"responded":       len(resp2) > 0,
		"granted":         len(resp2) > 0 && !resp2[0].GetReject(),
		"forget_accepted": forgedErr == nil,
	})

}
