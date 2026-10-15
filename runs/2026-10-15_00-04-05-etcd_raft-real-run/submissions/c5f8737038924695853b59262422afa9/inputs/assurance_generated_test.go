package raft_test

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"go.etcd.io/raft/v3"
	"go.etcd.io/raft/v3/tracker"
	pb "go.etcd.io/raft/v3/raftpb"
)

// emitCAEvent prints one CA_EVENT JSON line for the controller's parser.
func emitCAEvent(t *testing.T, ev map[string]any) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func errStringCA(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

// deliverReady hands out the outstanding work and completes it through the
// documented Ready/Advance contract, so outbound messages can be observed
// without reaching into unexported state.
// caStorages lets the delivery helper act as a correct application: the Ready
// contract requires HardState and Entries to reach stable storage before
// messages are sent, and a node that skips that cannot read its own entries
// back (they leave the unstable log without ever entering storage).
var caStorages = map[*raft.RawNode]*raft.MemoryStorage{}

func deliverReady(rn *raft.RawNode) raft.Ready {
	rd := rn.Ready()
	if ms := caStorages[rn]; ms != nil {
		if !raft.IsEmptyHardState(rd.HardState) {
			_ = ms.SetHardState(rd.HardState)
		}
		if len(rd.Entries) > 0 {
			_ = ms.Append(rd.Entries)
		}
		if !raft.IsEmptySnap(rd.Snapshot) {
			_ = ms.ApplySnapshot(rd.Snapshot)
		}
	}
	rn.Advance(rd)
	return rd
}

func leadOf(rn *raft.RawNode) uint64 { return rn.BasicStatus().SoftState.Lead }

func stateOf(rn *raft.RawNode) string { return rn.BasicStatus().SoftState.RaftState.String() }

func findMsgs(rd raft.Ready, typ pb.MessageType, to uint64) []*pb.Message {
	var out []*pb.Message
	for _, m := range rd.Messages {
		if m.GetType() == typ && m.GetTo() == to {
			out = append(out, m)
		}
	}
	return out
}

// caNewNode builds one real RawNode whose storage starts from the same snapshot
// on all nodes: voters {1,2,3} with a shared log prefix at index=10, term=1.
func caNewNode(t *testing.T, id uint64) *raft.RawNode {
	t.Helper()
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
		ID:              id,
		ElectionTick:    10,
		HeartbeatTick:   1,
		Storage:         ms,
		MaxSizePerMsg:   1 << 20,
		MaxInflightMsgs: 256,
		CheckQuorum:     true,
		PreVote:         true,
	})
	if err != nil {
		t.Fatalf("new raw node %d: %v", id, err)
	}
	caStorages[rn] = ms
	return rn
}

// caElectNode1 runs a real election for node 1 and replicates its term-2 entry,
// feeding every produced message through the receiver's public Step method.
func caElectNode1(t *testing.T, leader, node2, node3 *raft.RawNode) {
	t.Helper()
	if err := leader.Campaign(); err != nil {
		t.Fatalf("campaign: %v", err)
	}
	for _, m := range deliverReady(leader).Messages {
		switch m.GetTo() {
		case 2:
			if err := node2.Step(m); err != nil {
				t.Fatalf("step vote request on 2: %v", err)
			}
		case 3:
			if err := node3.Step(m); err != nil {
				t.Fatalf("step vote request on 3: %v", err)
			}
		}
	}
	for _, rn := range []*raft.RawNode{node2, node3} {
		for _, m := range deliverReady(rn).Messages {
			if err := leader.Step(m); err != nil {
				t.Fatalf("step vote response on 1: %v", err)
			}
		}
	}
	for _, m := range deliverReady(leader).Messages {
		switch m.GetTo() {
		case 2:
			if err := node2.Step(m); err != nil {
				t.Fatalf("step append on 2: %v", err)
			}
		case 3:
			if err := node3.Step(m); err != nil {
				t.Fatalf("step append on 3: %v", err)
			}
		}
	}
	for _, rn := range []*raft.RawNode{node2, node3} {
		for _, m := range deliverReady(rn).Messages {
			if err := leader.Step(m); err != nil {
				t.Fatalf("step append response on 1: %v", err)
			}
		}
	}
	deliverReady(leader)
}

// TestAssuranceInboundForgetLeader measures, on one follower, what a peer-form
// MsgForgetLeader delivered through RawNode.Step does to the live leader
// context and to the support given to an up-to-date candidate's pre-vote, and
// how the next real leader heartbeat closes that window.
func TestAssuranceInboundForgetLeader(t *testing.T) {
	leader, follower, other := caNewNode(t, 1), caNewNode(t, 2), caNewNode(t, 3)
	caElectNode1(t, leader, follower, other)

	// A real heartbeat tick: node 2 receives it exactly once, establishing its
	// leader context and election-timer lease; node 3 receives the same
	// heartbeat so that it too holds a live leader context.
	leader.Tick()
	tick := deliverReady(leader)
	hbs2 := findMsgs(tick, pb.MsgHeartbeat, 2)
	hbs3 := findMsgs(tick, pb.MsgHeartbeat, 3)
	if len(hbs2) != 1 || len(hbs3) != 1 {
		t.Fatalf("expected one heartbeat per follower, got %d/%d", len(hbs2), len(hbs3))
	}
	if err := other.Step(hbs3[0]); err != nil {
		t.Fatalf("step heartbeat on 3: %v", err)
	}
	if err := follower.Step(hbs2[0]); err != nil {
		t.Fatalf("step heartbeat on 2: %v", err)
	}
	emitCAEvent(t, map[string]any{
		"event": "heartbeat_delivered", "to": 2, "sender": 1,
		"term": hbs2[0].GetTerm(), "lead_after": leadOf(follower),
	})
	emitCAEvent(t, map[string]any{
		"event": "heartbeat_delivered_node3", "to": 3, "sender": 1,
		"term": hbs3[0].GetTerm(), "lead_after": leadOf(other),
	})

	// The intended producer of "forget the leader": the local API on a follower
	// that still considers the leader live.
	otherBefore := leadOf(other)
	otherErr := other.ForgetLeader()
	emitCAEvent(t, map[string]any{
		"event": "local_forget_leader_api", "to": 3, "lead_before": otherBefore,
		"lead_after": leadOf(other), "step_error": errStringCA(otherErr),
	})

	// Control: a message type that is classified local, arriving from a peer
	// through the same inbound path, is rejected and changes nothing.
	localErr := follower.Step(&pb.Message{
		Type: pb.MsgCheckQuorum.Enum(), From: new(uint64(3)), To: new(uint64(2)),
	})
	emitCAEvent(t, map[string]any{
		"event": "inbound_local_msg", "to": 2, "sender": 3, "type": "MsgCheckQuorum",
		"step_error": errStringCA(localErr), "lead_after": leadOf(follower),
	})

	// A real candidate (node 3) produces a real MsgPreVote request, delivered to
	// follower 2 verbatim.
	if err := other.Campaign(); err != nil {
		t.Fatalf("campaign 3: %v", err)
	}
	preVotes := findMsgs(deliverReady(other), pb.MsgPreVote, 2)
	if len(preVotes) != 1 {
		t.Fatalf("expected one pre-vote request for node 2, got %d", len(preVotes))
	}
	pv := preVotes[0]

	// Control: with the leader context intact the pre-vote is ignored (no
	// response message at all).
	if err := follower.Step(pv); err != nil {
		t.Fatalf("step pre-vote on 2 (under lease): %v", err)
	}
	rd := deliverReady(follower)
	emitCAEvent(t, map[string]any{
		"event": "prevote_outcome", "to": 2, "candidate": 3, "phase": "under_lease",
		"candidate_term": pv.GetTerm(), "lead": leadOf(follower),
		"responded":       len(findMsgs(rd, pb.MsgPreVoteResp, 3)) > 0,
		"granted":         len(findMsgs(rd, pb.MsgPreVoteResp, 3)) > 0 && !findMsgs(rd, pb.MsgPreVoteResp, 3)[0].GetReject(),
		"forget_accepted": false,
	})

	// The forged inbound message: the type only the local ForgetLeader API
	// produces, in the wire form a peer would produce (From=3, To=2, no term).
	forgedErr := follower.Step(&pb.Message{
		Type: pb.MsgForgetLeader.Enum(), From: new(uint64(3)), To: new(uint64(2)),
	})
	emitCAEvent(t, map[string]any{
		"event": "inbound_forget_leader", "to": 2, "sender": 3, "transport": "RawNode.Step",
		"accepted": forgedErr == nil, "step_error": errStringCA(forgedErr), "lead_after": leadOf(follower),
	})

	// The identical pre-vote request is delivered again after the forgery.
	if err := follower.Step(pv); err != nil {
		t.Fatalf("step pre-vote on 2 (after forget): %v", err)
	}
	rd2 := deliverReady(follower)
	resp2 := findMsgs(rd2, pb.MsgPreVoteResp, 3)
	emitCAEvent(t, map[string]any{
		"event": "prevote_outcome", "to": 2, "candidate": 3, "phase": "after_forget",
		"candidate_term": pv.GetTerm(), "lead": leadOf(follower),
		"responded":       len(resp2) > 0,
		"granted":         len(resp2) > 0 && !resp2[0].GetReject(),
		"forget_accepted": forgedErr == nil,
	})

	// The leader's next heartbeat is produced by one further logical tick and
	// delivered to follower 2: this is the repair path that closes the window.
	leader.Tick()
	restore := deliverReady(leader)
	rhbs2 := findMsgs(restore, pb.MsgHeartbeat, 2)
	if len(rhbs2) != 1 {
		t.Fatalf("expected one restore heartbeat, got %d", len(rhbs2))
	}
	if err := follower.Step(rhbs2[0]); err != nil {
		t.Fatalf("step restore heartbeat on 2: %v", err)
	}
	emitCAEvent(t, map[string]any{
		"event": "restore_heartbeat_delivered", "to": 2, "sender": 1,
		"term": rhbs2[0].GetTerm(), "leader_ticks_elapsed": 1, "heartbeat_timeout_ticks": 1,
		"lead_after": leadOf(follower),
	})
	if err := follower.Step(pv); err != nil {
		t.Fatalf("step pre-vote on 2 (after restore): %v", err)
	}
	rd3 := deliverReady(follower)
	emitCAEvent(t, map[string]any{
		"event": "prevote_outcome", "to": 2, "candidate": 3, "phase": "after_restore",
		"candidate_term": pv.GetTerm(), "lead": leadOf(follower),
		"responded":       len(findMsgs(rd3, pb.MsgPreVoteResp, 3)) > 0,
		"granted":         len(findMsgs(rd3, pb.MsgPreVoteResp, 3)) > 0 && !findMsgs(rd3, pb.MsgPreVoteResp, 3)[0].GetReject(),
		"forget_accepted": false,
	})
}

// TestAssuranceForgedForgetQuorumElection runs the same forgery against a
// quorum-relevant follower and then lets a real candidate campaign, to see
// whether an up-to-date candidate can become leader at a higher term while the
// incumbent leader is still serving.
func TestAssuranceForgedForgetQuorumElection(t *testing.T) {
	leader, follower, candidate := caNewNode(t, 1), caNewNode(t, 2), caNewNode(t, 3)
	caElectNode1(t, leader, follower, candidate)

	// Node 2 (the quorum-relevant voter) hears from the live leader.
	leader.Tick()
	tick := deliverReady(leader)
	hbs2 := findMsgs(tick, pb.MsgHeartbeat, 2)
	hbs3 := findMsgs(tick, pb.MsgHeartbeat, 3)
	if len(hbs2) != 1 || len(hbs3) != 1 {
		t.Fatalf("expected one heartbeat per follower, got %d/%d", len(hbs2), len(hbs3))
	}
	if err := candidate.Step(hbs3[0]); err != nil {
		t.Fatalf("step heartbeat on 3: %v", err)
	}
	if err := follower.Step(hbs2[0]); err != nil {
		t.Fatalf("step heartbeat on 2: %v", err)
	}
	emitCAEvent(t, map[string]any{
		"event": "q_heartbeat_delivered", "node": 2, "to": 2, "sender": 1,
		"term": hbs2[0].GetTerm(), "lead_after": leadOf(follower),
	})

	// Real campaign by node 3; its request is delivered to the leased follower
	// first (control), and to the incumbent leader as well.
	if err := candidate.Campaign(); err != nil {
		t.Fatalf("campaign 3: %v", err)
	}
	camp := deliverReady(candidate)
	pv2 := findMsgs(camp, pb.MsgPreVote, 2)
	pv1 := findMsgs(camp, pb.MsgPreVote, 1)
	if len(pv2) != 1 || len(pv1) != 1 {
		t.Fatalf("expected pre-vote requests for 1 and 2, got %d/%d", len(pv1), len(pv2))
	}
	if err := follower.Step(pv2[0]); err != nil {
		t.Fatalf("step pre-vote on 2 (under lease): %v", err)
	}
	rdCtrl := deliverReady(follower)
	emitCAEvent(t, map[string]any{
		"event": "q_prevote_outcome", "node": 2, "to": 2, "candidate": 3, "phase": "under_lease",
		"candidate_term": pv2[0].GetTerm(), "lead": leadOf(follower),
		"responded":       len(findMsgs(rdCtrl, pb.MsgPreVoteResp, 3)) > 0,
		"granted":         len(findMsgs(rdCtrl, pb.MsgPreVoteResp, 3)) > 0 && !findMsgs(rdCtrl, pb.MsgPreVoteResp, 3)[0].GetReject(),
		"forget_accepted": false,
	})
	emitCAEvent(t, map[string]any{
		"event": "q_prevote_request", "node": 3, "leader": 3, "to": 2, "term": pv2[0].GetTerm(), "log_index": 11,
	})
	if err := leader.Step(pv1[0]); err != nil {
		t.Fatalf("step pre-vote on incumbent: %v", err)
	}
	emitCAEvent(t, map[string]any{
		"event": "q_prevote_at_incumbent", "node": 1, "to": 1, "candidate": 3,
		"term": pv1[0].GetTerm(), "responded": len(findMsgs(deliverReady(leader), pb.MsgPreVoteResp, 3)) > 0,
	})

	// The forged message reaches the quorum-relevant follower.
	forgedErr := follower.Step(&pb.Message{
		Type: pb.MsgForgetLeader.Enum(), From: new(uint64(3)), To: new(uint64(2)),
	})
	emitCAEvent(t, map[string]any{
		"event": "q_inbound_forget_leader", "node": 2, "to": 2, "sender": 3,
		"transport": "RawNode.Step", "accepted": forgedErr == nil,
		"step_error": errStringCA(forgedErr), "lead_after": leadOf(follower),
	})

	// The identical request is re-delivered, and its grant is fed back to the
	// candidate, which then campaigns for real.
	if err := follower.Step(pv2[0]); err != nil {
		t.Fatalf("step pre-vote on 2 (after forget): %v", err)
	}
	rdGrant := deliverReady(follower)
	grants := findMsgs(rdGrant, pb.MsgPreVoteResp, 3)
	emitCAEvent(t, map[string]any{
		"event": "q_prevote_outcome", "node": 2, "to": 2, "candidate": 3, "phase": "after_forget",
		"candidate_term": pv2[0].GetTerm(), "lead": leadOf(follower),
		"responded":       len(grants) > 0,
		"granted":         len(grants) > 0 && !grants[0].GetReject(),
		"forget_accepted": forgedErr == nil,
	})
	if len(grants) > 0 {
		if err := candidate.Step(grants[0]); err != nil {
			t.Fatalf("step pre-vote response on 3: %v", err)
		}
	}
	votes := deliverReady(candidate)
	vote2 := findMsgs(votes, pb.MsgVote, 2)
	vote1 := findMsgs(votes, pb.MsgVote, 1)
	if len(vote2) != 1 || len(vote1) != 1 {
		t.Fatalf("expected vote requests for 1 and 2, got %d/%d", len(vote1), len(vote2))
	}
	if err := follower.Step(vote2[0]); err != nil {
		t.Fatalf("step vote request on 2: %v", err)
	}
	rdVote := deliverReady(follower)
	voteResps := findMsgs(rdVote, pb.MsgVoteResp, 3)
	emitCAEvent(t, map[string]any{
		"event": "q_vote_outcome", "node": 2, "to": 2, "candidate": 3, "term": vote2[0].GetTerm(),
		"responded": len(voteResps) > 0,
		"granted":   len(voteResps) > 0 && !voteResps[0].GetReject(),
	})
	if len(voteResps) > 0 {
		if err := candidate.Step(voteResps[0]); err != nil {
			t.Fatalf("step vote response on 3: %v", err)
		}
	}
	// The incumbent leader also receives the vote request.
	if err := leader.Step(vote1[0]); err != nil {
		t.Fatalf("step vote request on incumbent: %v", err)
	}
	emitCAEvent(t, map[string]any{
		"event": "q_vote_at_incumbent", "node": 1, "to": 1, "candidate": 3, "term": vote1[0].GetTerm(),
		"responded": len(findMsgs(deliverReady(leader), pb.MsgVoteResp, 3)) > 0,
	})
	deliverReady(candidate)

	emitCAEvent(t, map[string]any{
		"event": "q_leadership_state", "node": 3, "state": stateOf(candidate),
		"term": candidate.BasicStatus().GetTerm(),
	})
	emitCAEvent(t, map[string]any{
		"event": "q_leadership_state", "node": 1, "state": stateOf(leader),
		"term": leader.BasicStatus().GetTerm(),
	})
}

// TestAssuranceForgedForgetAftermath repeats the forged election and then lets
// the new leader's append reach the deposed incumbent, to see whether the
// authority transfer completes cleanly and whether the entry committed under the
// incumbent survives in the new leader's log.
func TestAssuranceForgedForgetAftermath(t *testing.T) {
	leader, follower, candidate := caNewNode(t, 1), caNewNode(t, 2), caNewNode(t, 3)
	caElectNode1(t, leader, follower, candidate)

	leader.Tick()
	tick := deliverReady(leader)
	hbs2 := findMsgs(tick, pb.MsgHeartbeat, 2)
	hbs3 := findMsgs(tick, pb.MsgHeartbeat, 3)
	if len(hbs2) != 1 || len(hbs3) != 1 {
		t.Fatalf("expected one heartbeat per follower, got %d/%d", len(hbs2), len(hbs3))
	}
	if err := candidate.Step(hbs3[0]); err != nil {
		t.Fatalf("step heartbeat on 3: %v", err)
	}
	if err := follower.Step(hbs2[0]); err != nil {
		t.Fatalf("step heartbeat on 2: %v", err)
	}
	emitCAEvent(t, map[string]any{
		"event": "a_heartbeat_delivered", "node": 2, "to": 2, "sender": 1,
		"term": hbs2[0].GetTerm(), "lead_after": leadOf(follower),
	})

	commitBefore := candidate.BasicStatus().GetCommit()
	if err := candidate.Campaign(); err != nil {
		t.Fatalf("campaign 3: %v", err)
	}
	camp := deliverReady(candidate)
	pv2 := findMsgs(camp, pb.MsgPreVote, 2)
	if len(pv2) != 1 {
		t.Fatalf("expected one pre-vote request for node 2, got %d", len(pv2))
	}
	if err := follower.Step(pv2[0]); err != nil {
		t.Fatalf("step pre-vote on 2 (under lease): %v", err)
	}
	rdCtrl := deliverReady(follower)
	emitCAEvent(t, map[string]any{
		"event": "a_prevote_outcome", "node": 2, "to": 2, "candidate": 3, "phase": "under_lease",
		"candidate_term": pv2[0].GetTerm(), "lead": leadOf(follower),
		"responded":       len(findMsgs(rdCtrl, pb.MsgPreVoteResp, 3)) > 0,
		"granted":         len(findMsgs(rdCtrl, pb.MsgPreVoteResp, 3)) > 0 && !findMsgs(rdCtrl, pb.MsgPreVoteResp, 3)[0].GetReject(),
		"forget_accepted": false,
	})
	emitCAEvent(t, map[string]any{
		"event": "a_prevote_request", "node": 3, "leader": 3, "to": 2, "term": pv2[0].GetTerm(), "log_index": 11,
	})
	forgedErr := follower.Step(&pb.Message{
		Type: pb.MsgForgetLeader.Enum(), From: new(uint64(3)), To: new(uint64(2)),
	})
	emitCAEvent(t, map[string]any{
		"event": "a_inbound_forget_leader", "node": 2, "to": 2, "sender": 3,
		"transport": "RawNode.Step", "accepted": forgedErr == nil,
		"step_error": errStringCA(forgedErr), "lead_after": leadOf(follower),
	})
	if err := follower.Step(pv2[0]); err != nil {
		t.Fatalf("step pre-vote on 2 (after forget): %v", err)
	}
	rdGrant := deliverReady(follower)
	grants := findMsgs(rdGrant, pb.MsgPreVoteResp, 3)
	emitCAEvent(t, map[string]any{
		"event": "a_prevote_outcome", "node": 2, "to": 2, "candidate": 3, "phase": "after_forget",
		"candidate_term": pv2[0].GetTerm(), "lead": leadOf(follower),
		"responded":       len(grants) > 0,
		"granted":         len(grants) > 0 && !grants[0].GetReject(),
		"forget_accepted": forgedErr == nil,
	})
	if len(grants) > 0 {
		if err := candidate.Step(grants[0]); err != nil {
			t.Fatalf("step pre-vote response on 3: %v", err)
		}
	}
	votes := deliverReady(candidate)
	vote2 := findMsgs(votes, pb.MsgVote, 2)
	if len(vote2) != 1 {
		t.Fatalf("expected one vote request for node 2, got %d", len(vote2))
	}
	if err := follower.Step(vote2[0]); err != nil {
		t.Fatalf("step vote request on 2: %v", err)
	}
	rdVote := deliverReady(follower)
	voteResps := findMsgs(rdVote, pb.MsgVoteResp, 3)
	emitCAEvent(t, map[string]any{
		"event": "a_vote_outcome", "node": 2, "to": 2, "candidate": 3, "term": vote2[0].GetTerm(),
		"responded": len(voteResps) > 0,
		"granted":   len(voteResps) > 0 && !voteResps[0].GetReject(),
	})
	if len(voteResps) > 0 {
		if err := candidate.Step(voteResps[0]); err != nil {
			t.Fatalf("step vote response on 3: %v", err)
		}
	}
	newLeaderWork := deliverReady(candidate)
	emitCAEvent(t, map[string]any{
		"event": "a_leadership_state", "node": 3, "state": stateOf(candidate),
		"term": candidate.BasicStatus().GetTerm(),
	})

	// The new leader's first append to the deposed incumbent: the previous entry
	// must be the one the incumbent itself committed at (index=11, term=2), and
	// the new leader's own term-3 entry follows it.
	appends := findMsgs(newLeaderWork, pb.MsgApp, 1)
	if len(appends) != 1 {
		t.Fatalf("expected one append for the incumbent, got %d", len(appends))
	}
	app := appends[0]
	if err := leader.Step(app); err != nil {
		t.Fatalf("step new leader append on incumbent: %v", err)
	}
	rdInc := deliverReady(leader)
	resps := findMsgs(rdInc, pb.MsgAppResp, 3)
	rejected := false
	respIndex := uint64(0)
	if len(resps) > 0 {
		rejected = resps[0].GetReject()
		respIndex = resps[0].GetIndex()
	}
	emitCAEvent(t, map[string]any{
		"event": "c_append_to_incumbent", "node": 1, "leader": 3,
		"incumbent_commit_before": leader.BasicStatus().GetCommit(),
		"incumbent_committed_term": leader.BasicStatus().GetTerm(),
		"prev_index": app.GetIndex(), "prev_term": app.GetLogTerm(),
		"entry_index": app.GetEntries()[len(app.GetEntries())-1].GetIndex(),
		"entry_term":  app.GetEntries()[len(app.GetEntries())-1].GetTerm(),
		"rejected":    rejected, "resp_index": respIndex,
		"state_after": stateOf(leader), "term_after": leader.BasicStatus().GetTerm(), "lead_after": leadOf(leader),
	})
	if len(resps) > 0 {
		if err := candidate.Step(resps[0]); err != nil {
			t.Fatalf("step incumbent append response on 3: %v", err)
		}
	}
	deliverReady(candidate)
	emitCAEvent(t, map[string]any{
		"event": "c_commit_progress", "node": 3, "commit_before": commitBefore,
		"commit_after": candidate.BasicStatus().GetCommit(), "state": stateOf(candidate),
	})
}

// TestAssuranceForgedForgetPersistence repeats the forgery once per heartbeat
// round, so the repair path and the re-opening of the window can be observed
// over several rounds instead of once.
func TestAssuranceForgedForgetPersistence(t *testing.T) {
	leader, follower, other := caNewNode(t, 1), caNewNode(t, 2), caNewNode(t, 3)
	caElectNode1(t, leader, follower, other)

	leader.Tick()
	tick := deliverReady(leader)
	hbs2 := findMsgs(tick, pb.MsgHeartbeat, 2)
	hbs3 := findMsgs(tick, pb.MsgHeartbeat, 3)
	if len(hbs2) != 1 || len(hbs3) != 1 {
		t.Fatalf("expected one heartbeat per follower, got %d/%d", len(hbs2), len(hbs3))
	}
	if err := other.Step(hbs3[0]); err != nil {
		t.Fatalf("step heartbeat on 3: %v", err)
	}
	if err := follower.Step(hbs2[0]); err != nil {
		t.Fatalf("step heartbeat on 2: %v", err)
	}
	emitCAEvent(t, map[string]any{
		"event": "p_heartbeat_delivered", "round": 0, "node": 2, "to": 2, "sender": 1,
		"lead_after": leadOf(follower), "forged_next": false,
	})
	if err := other.Campaign(); err != nil {
		t.Fatalf("campaign 3: %v", err)
	}
	preVotes := findMsgs(deliverReady(other), pb.MsgPreVote, 2)
	if len(preVotes) != 1 {
		t.Fatalf("expected one pre-vote request for node 2, got %d", len(preVotes))
	}
	pv := preVotes[0]

	// Round 0 control: no forged message is delivered.
	if err := follower.Step(pv); err != nil {
		t.Fatalf("step pre-vote on 2 (control): %v", err)
	}
	rd0 := deliverReady(follower)
	emitCAEvent(t, map[string]any{
		"event": "p_prevote_outcome", "round": 0, "node": 2, "to": 2, "forged": false,
		"forget_accepted": false, "lead": leadOf(follower),
		"responded": len(findMsgs(rd0, pb.MsgPreVoteResp, 3)) > 0,
		"granted":   len(findMsgs(rd0, pb.MsgPreVoteResp, 3)) > 0 && !findMsgs(rd0, pb.MsgPreVoteResp, 3)[0].GetReject(),
	})

	// Rounds 1..3: repair by heartbeat, then the same forgery, then the same
	// pre-vote request retried by the candidate.
	for round := 1; round <= 3; round++ {
		leader.Tick()
		tick := deliverReady(leader)
		hb := findMsgs(tick, pb.MsgHeartbeat, 2)
		if len(hb) != 1 {
			t.Fatalf("round %d: expected one heartbeat for node 2, got %d", round, len(hb))
		}
		before := leadOf(follower)
		if err := follower.Step(hb[0]); err != nil {
			t.Fatalf("round %d: step heartbeat on 2: %v", round, err)
		}
		emitCAEvent(t, map[string]any{
			"event": "p_heartbeat_restore", "round": round, "node": 2, "to": 2, "sender": 1,
			"lead_before": before, "lead_after": leadOf(follower), "ticks_since_previous": 1,
		})
		forgedErr := follower.Step(&pb.Message{
			Type: pb.MsgForgetLeader.Enum(), From: new(uint64(3)), To: new(uint64(2)),
		})
		emitCAEvent(t, map[string]any{
			"event": "p_inbound_forget", "round": round, "node": 2, "to": 2, "sender": 3,
			"accepted": forgedErr == nil, "lead_before": 1, "lead_after": leadOf(follower),
		})
		if err := follower.Step(pv); err != nil {
			t.Fatalf("round %d: step pre-vote on 2: %v", round, err)
		}
		rd := deliverReady(follower)
		resps := findMsgs(rd, pb.MsgPreVoteResp, 3)
		emitCAEvent(t, map[string]any{
			"event": "p_prevote_outcome", "round": round, "node": 2, "to": 2, "forged": true,
			"forget_accepted": forgedErr == nil, "lead": leadOf(follower),
			"responded": len(resps) > 0,
			"granted":   len(resps) > 0 && !resps[0].GetReject(),
		})
	}
	emitCAEvent(t, map[string]any{
		"event": "p_leader_state", "node": 1, "state": stateOf(leader),
		"term": leader.BasicStatus().GetTerm(),
	})
}

// TestAssuranceForgedForgetNodeAPI checks the same inbound path through the
// public Node interface (the one applications use: Node.Step for peer messages,
// Node.ForgetLeader for the local operation), rather than RawNode.
func TestAssuranceForgedForgetNodeAPI(t *testing.T) {
	// A real leader and a real voter, so the heartbeat and the votes come from
	// real producers. Node 1 needs only its own vote plus node 3's.
	leader, voter3 := caNewNode(t, 1), caNewNode(t, 3)
	if err := leader.Campaign(); err != nil {
		t.Fatalf("campaign: %v", err)
	}
	for _, m := range deliverReady(leader).Messages {
		if m.GetTo() == 3 {
			if err := voter3.Step(m); err != nil {
				t.Fatalf("step vote request on 3: %v", err)
			}
		}
	}
	for _, m := range deliverReady(voter3).Messages {
		if err := leader.Step(m); err != nil {
			t.Fatalf("step vote response on 1: %v", err)
		}
	}
	// Real votes: deliver the resulting MsgVote requests to node 3 and its
	// response back, then replicate the leader's first entry the same way.
	for _, m := range deliverReady(leader).Messages {
		if m.GetTo() == 3 {
			if err := voter3.Step(m); err != nil {
				t.Fatalf("step vote request on 3: %v", err)
			}
		}
	}
	for _, m := range deliverReady(voter3).Messages {
		if err := leader.Step(m); err != nil {
			t.Fatalf("step real vote response on 1: %v", err)
		}
	}
	for _, m := range deliverReady(leader).Messages {
		if m.GetTo() == 3 {
			if err := voter3.Step(m); err != nil {
				t.Fatalf("step append on 3: %v", err)
			}
		}
	}
	for _, m := range deliverReady(voter3).Messages {
		if err := leader.Step(m); err != nil {
			t.Fatalf("step append response on 1: %v", err)
		}
	}
	deliverReady(leader)

	// The node under test is a real Node (goroutine + channels) started from the
	// same storage snapshot with id 2.
	ms := raft.NewMemoryStorage()
	if err := ms.ApplySnapshot(&pb.Snapshot{Metadata: &pb.SnapshotMetadata{
		Index:     new(uint64(10)),
		Term:      new(uint64(1)),
		ConfState: &pb.ConfState{Voters: []uint64{1, 2, 3}},
	}}); err != nil {
		t.Fatalf("apply snapshot: %v", err)
	}
	if err := ms.SetHardState(&pb.HardState{Term: new(uint64(1)), Commit: new(uint64(10))}); err != nil {
		t.Fatalf("set hard state: %v", err)
	}
	node := raft.RestartNode(&raft.Config{
		ID: 2, ElectionTick: 10, HeartbeatTick: 1, Storage: ms,
		MaxSizePerMsg: 1 << 20, MaxInflightMsgs: 256, CheckQuorum: true, PreVote: true,
	})
	defer node.Stop()
	go func() {
		for range node.Ready() {
			node.Advance()
		}
	}()
	ctx := context.Background()

	// waitLead polls the node's reported view until it matches, so the
	// observation is synchronized with the run loop rather than with wall time.
	waitLead := func(want uint64) (uint64, int) {
		for i := 0; i < 2000; i++ {
			if got := node.Status().SoftState.Lead; got == want {
				return got, i
			}
			time.Sleep(time.Millisecond)
		}
		return node.Status().SoftState.Lead, 2000
	}

	leader.Tick()
	hbs := findMsgs(deliverReady(leader), pb.MsgHeartbeat, 2)
	if len(hbs) != 1 {
		t.Fatalf("expected one heartbeat for node 2, got %d", len(hbs))
	}
	if err := node.Step(ctx, hbs[0]); err != nil {
		t.Fatalf("step heartbeat through Node.Step: %v", err)
	}
	got, polls := waitLead(1)
	emitCAEvent(t, map[string]any{
		"event": "n_heartbeat_via_node", "node": 2, "lead": got, "polls": polls,
	})

	// Control: a genuinely local type from a peer is ignored by Node.Step.
	localErr := node.Step(ctx, &pb.Message{Type: pb.MsgCheckQuorum.Enum(), From: new(uint64(3)), To: new(uint64(2))})
	emitCAEvent(t, map[string]any{
		"event": "n_inbound_local_msg", "node": 2, "sender": 3,
		"step_error": errStringCA(localErr), "lead": node.Status().SoftState.Lead,
	})

	// The forged message in peer wire form, through the documented Node path.
	forgedErr := node.Step(ctx, &pb.Message{Type: pb.MsgForgetLeader.Enum(), From: new(uint64(3)), To: new(uint64(2))})
	got, polls = waitLead(0)
	emitCAEvent(t, map[string]any{
		"event": "n_inbound_forget", "node": 2, "sender": 3,
		"step_error": errStringCA(forgedErr), "lead_after": got, "polls": polls,
	})

	// The intended local operation on the same Node, after re-hearing the leader.
	leader.Tick()
	hbs2 := findMsgs(deliverReady(leader), pb.MsgHeartbeat, 2)
	if len(hbs2) != 1 {
		t.Fatalf("expected a second heartbeat for node 2, got %d", len(hbs2))
	}
	if err := node.Step(ctx, hbs2[0]); err != nil {
		t.Fatalf("step second heartbeat: %v", err)
	}
	got, polls = waitLead(1)
	before := got
	apiErr := node.ForgetLeader(ctx)
	got, polls = waitLead(0)
	emitCAEvent(t, map[string]any{
		"event": "n_local_forget_api", "node": 2, "lead_before": before, "lead_after": got,
		"step_error": errStringCA(apiErr), "polls": polls,
	})
}

// TestAssuranceIncumbentSelfStepDown measures the bound the account states from
// source: a leader that stops hearing from a quorum ends its own leadership on
// its own clock, because tickHeartbeat runs the CheckQuorum rule once per
// election timeout.
func TestAssuranceIncumbentSelfStepDown(t *testing.T) {
	leader, follower, candidate := caNewNode(t, 1), caNewNode(t, 2), caNewNode(t, 3)
	caElectNode1(t, leader, follower, candidate)
	emitCAEvent(t, map[string]any{
		"event": "s_leader_before", "node": 1, "ticks": 0,
		"state": stateOf(leader), "term": leader.BasicStatus().GetTerm(),
	})
	// No message is delivered to or from the leader from here on: it hears
	// nothing from voter 2 and voter 3 while its own clock keeps running.
	for ticks := 1; ticks <= 20; ticks++ {
		leader.Tick()
		deliverReady(leader)
		if ticks == 10 || ticks == 20 {
			emitCAEvent(t, map[string]any{
				"event": "s_leader_state", "node": 1, "ticks": ticks,
				"state": stateOf(leader), "term": leader.BasicStatus().GetTerm(),
							})
		}
	}
}

// TestAssuranceQueuedReadIndex measures the completion half of the pending
// read-index behaviour: a request accepted while the leader has no commit in
// its own term is not answered, and is answered once that commit happens.
func TestAssuranceQueuedReadIndex(t *testing.T) {
	leader, voter3 := caNewNode(t, 1), caNewNode(t, 3)
	if err := leader.Campaign(); err != nil {
		t.Fatalf("campaign: %v", err)
	}
	for _, m := range deliverReady(leader).Messages {
		if m.GetTo() == 3 {
			if err := voter3.Step(m); err != nil {
				t.Fatalf("step pre-vote request on 3: %v", err)
			}
		}
	}
	for _, m := range deliverReady(voter3).Messages {
		if err := leader.Step(m); err != nil {
			t.Fatalf("step pre-vote response on 1: %v", err)
		}
	}
	// Real votes: deliver the MsgVote to node 3 so the election completes, but
	// withhold the append acknowledgement that would commit in this term.
	for _, m := range deliverReady(leader).Messages {
		if m.GetTo() == 3 {
			if err := voter3.Step(m); err != nil {
				t.Fatalf("step vote request on 3: %v", err)
			}
		}
	}
	var voteResp *pb.Message
	for _, m := range deliverReady(voter3).Messages {
		if m.GetType() == pb.MsgVoteResp {
			voteResp = m
		}
	}
	if voteResp == nil {
		t.Fatal("expected a vote response from node 3")
	}
	if err := leader.Step(voteResp); err != nil {
		t.Fatalf("step vote response on 1: %v", err)
	}
	// The leader is elected but has committed nothing in its term: its appends
	// are outstanding and not acknowledged.
	appendWork := deliverReady(leader)
	emitCAEvent(t, map[string]any{
		"event": "r_elected", "node": 1, "state": stateOf(leader),
		"term": leader.BasicStatus().GetTerm(), "commit": leader.BasicStatus().GetCommit(),
		"appends_outstanding": len(findMsgs(appendWork, pb.MsgApp, 3)),
	})
	ctx := []byte("assurance-read-1")
	leader.ReadIndex(ctx)
	queued := deliverReady(leader)
	emitCAEvent(t, map[string]any{
		"event": "r_readindex_queued", "node": 1, "state": stateOf(leader),
		"term": leader.BasicStatus().GetTerm(), "commit": leader.BasicStatus().GetCommit(),
		"read_states": len(queued.ReadStates), "appends_outstanding": len(findMsgs(appendWork, pb.MsgApp, 3)),
	})
	// Node 3 acknowledges the term-2 entry, so the leader commits in its term
	// and the queued request can be released.
	var ack *pb.Message
	for _, m := range appendWork.Messages {
		if m.GetType() == pb.MsgApp && m.GetTo() == 3 {
			if err := voter3.Step(m); err != nil {
				t.Fatalf("step append on 3: %v", err)
			}
		}
	}
	for _, m := range deliverReady(voter3).Messages {
		if m.GetType() == pb.MsgAppResp {
			ack = m
		}
	}
	if ack == nil {
		t.Fatal("expected an append response from node 3")
	}
	if err := leader.Step(ack); err != nil {
		t.Fatalf("step append response on 1: %v", err)
	}
	prog := map[string]any{}
	leader.WithProgress(func(id uint64, typ raft.ProgressType, pr tracker.Progress) {
		prog[fmt.Sprintf("%d", id)] = map[string]any{"match": pr.Match, "next": pr.Next}
	})
	emitCAEvent(t, map[string]any{
		"event": "r_progress_after_ack", "node": 1, "commit": leader.BasicStatus().GetCommit(),
		"state": stateOf(leader), "progress": prog,
	})
	releaseWork := deliverReady(leader)
	for _, m := range findMsgs(releaseWork, pb.MsgHeartbeat, 3) {
		if err := voter3.Step(m); err != nil {
			t.Fatalf("step release heartbeat on 3: %v", err)
		}
	}
	for _, m := range deliverReady(voter3).Messages {
		if m.GetType() == pb.MsgHeartbeatResp {
			if err := leader.Step(m); err != nil {
				t.Fatalf("step release heartbeat response on 1: %v", err)
			}
		}
	}
	released := deliverReady(leader)
	index := uint64(0)
	gotCtx := ""
	for _, rs := range released.ReadStates {
		index = rs.Index
		gotCtx = string(rs.RequestCtx)
	}
	emitCAEvent(t, map[string]any{
		"event": "r_readindex_released", "node": 1, "commit": leader.BasicStatus().GetCommit(),
		"read_states": len(released.ReadStates), "read_index": index, "read_ctx": gotCtx,
		"ctx_matches": gotCtx == string(ctx),
	})
}

// TestAssuranceReadIndexAcrossLeadershipLoss asks what happens to a read request
// that was queued by a leader which then loses leadership before committing.
func TestAssuranceReadIndexAcrossLeadershipLoss(t *testing.T) {
	leader, voter3 := caNewNode(t, 1), caNewNode(t, 3)
	if err := leader.Campaign(); err != nil {
		t.Fatalf("campaign: %v", err)
	}
	for _, m := range deliverReady(leader).Messages {
		if m.GetTo() == 3 {
			if err := voter3.Step(m); err != nil {
				t.Fatalf("step pre-vote on 3: %v", err)
			}
		}
	}
	for _, m := range deliverReady(voter3).Messages {
		if err := leader.Step(m); err != nil {
			t.Fatalf("step pre-vote response on 1: %v", err)
		}
	}
	for _, m := range deliverReady(leader).Messages {
		if m.GetTo() == 3 {
			if err := voter3.Step(m); err != nil {
				t.Fatalf("step vote request on 3: %v", err)
			}
		}
	}
	for _, m := range deliverReady(voter3).Messages {
		if err := leader.Step(m); err != nil {
			t.Fatalf("step vote response on 1: %v", err)
		}
	}
	deliverReady(leader)
	leader.ReadIndex([]byte("assurance-stale-read"))
	queued := deliverReady(leader)
	emitCAEvent(t, map[string]any{
		"event": "q_queued", "node": 1, "state": stateOf(leader), "term": leader.BasicStatus().GetTerm(),
		"commit": leader.BasicStatus().GetCommit(), "read_states": len(queued.ReadStates),
	})
	// Nothing from a quorum arrives, so the leader's own quorum check ends its
	// leadership; the queued request is now owed by a follower.
	for i := 0; i < 10; i++ {
		leader.Tick()
		deliverReady(leader)
	}
	demoted := deliverReady(leader)
	emitCAEvent(t, map[string]any{
		"event": "q_demoted", "node": 1, "state": stateOf(leader), "term": leader.BasicStatus().GetTerm(),
		"lead": leadOf(leader), "read_states": len(demoted.ReadStates),
	})
	// It leads again, and this time it also replicates to the follower so that a
	// commit in the new term happens and the stale request can be released.
	if err := leader.Campaign(); err != nil {
		t.Fatalf("second campaign: %v", err)
	}
	for _, m := range deliverReady(leader).Messages {
		if m.GetTo() == 3 {
			if err := voter3.Step(m); err != nil {
				t.Fatalf("step second pre-vote on 3: %v", err)
			}
		}
	}
	for _, m := range deliverReady(voter3).Messages {
		if err := leader.Step(m); err != nil {
			t.Fatalf("step second pre-vote response on 1: %v", err)
		}
	}
	for _, m := range deliverReady(leader).Messages {
		if m.GetTo() == 3 {
			if err := voter3.Step(m); err != nil {
				t.Fatalf("step second vote request on 3: %v", err)
			}
		}
	}
	for _, m := range deliverReady(voter3).Messages {
		if err := leader.Step(m); err != nil {
			t.Fatalf("step second vote response on 1: %v", err)
		}
	}
	relead := deliverReady(leader)
	emitCAEvent(t, map[string]any{
		"event": "q_relead", "node": 1, "state": stateOf(leader), "term": leader.BasicStatus().GetTerm(),
		"commit": leader.BasicStatus().GetCommit(), "read_states": len(relead.ReadStates),
	})
	var collected []*pb.Message
	collected = append(collected, relead.Messages...)
	work := relead.Messages
	for i := 0; i < 3; i++ {
		var next *pb.Message
		for _, m := range work {
			if m.GetType() == pb.MsgApp && m.GetTo() == 3 {
				next = m
			}
		}
		if next == nil {
			break
		}
		if err := voter3.Step(next); err != nil {
			t.Fatalf("step append on 3: %v", err)
		}
		for _, m := range deliverReady(voter3).Messages {
			if m.GetType() == pb.MsgAppResp {
				if err := leader.Step(m); err != nil {
					t.Fatalf("step append response on 1: %v", err)
				}
			}
		}
		work = deliverReady(leader).Messages
		collected = append(collected, work...)
	}
	// The release heartbeats were emitted with the last drained Ready, whose
	// messages are still in work; deliver those rather than draining again.
	release := raft.Ready{Messages: collected}
	for _, m := range findMsgs(release, pb.MsgHeartbeat, 3) {
		if err := voter3.Step(m); err != nil {
			t.Fatalf("step release heartbeat on 3: %v", err)
		}
	}
	for _, m := range deliverReady(voter3).Messages {
		if m.GetType() == pb.MsgHeartbeatResp {
			if err := leader.Step(m); err != nil {
				t.Fatalf("step release heartbeat response on 1: %v", err)
			}
		}
	}
	final := deliverReady(leader)
	index := uint64(0)
	gotCtx := ""
	for _, rs := range final.ReadStates {
		index = rs.Index
		gotCtx = string(rs.RequestCtx)
	}
	emitCAEvent(t, map[string]any{
		"event": "q_released_stale", "node": 1, "commit": leader.BasicStatus().GetCommit(),
		"read_states": len(final.ReadStates), "read_index": index, "read_ctx": gotCtx,
		"ctx_matches": gotCtx == "assurance-stale-read",
	})
}

// TestAssuranceTermZeroNetworkMessage measures the contrast behind the main
// finding: a network-type message with no term field reaches the same follower
// path a legal one does, where the only missing piece is an illegal field.
func TestAssuranceTermZeroNetworkMessage(t *testing.T) {
	leader, follower, other := caNewNode(t, 1), caNewNode(t, 2), caNewNode(t, 3)
	caElectNode1(t, leader, follower, other)
	emitCAEvent(t, map[string]any{
		"event": "t_setup", "node": 2, "state": stateOf(follower),
		"term": follower.BasicStatus().GetTerm(), "lead_before": leadOf(follower),
	})
	leader.Tick()
	tick := deliverReady(leader)
	hbs := findMsgs(tick, pb.MsgHeartbeat, 2)
	if len(hbs) != 1 {
		t.Fatalf("expected one heartbeat for node 2, got %d", len(hbs))
	}
	if err := follower.Step(hbs[0]); err != nil {
		t.Fatalf("step real heartbeat on 2: %v", err)
	}
	emitCAEvent(t, map[string]any{
		"event": "t_control_heartbeat", "node": 2, "sender": 1, "term": hbs[0].GetTerm(),
		"lead_before": 0, "lead_after": leadOf(follower),
	})
	// The same message type from a different peer, with no term field at all.
	termZero := &pb.Message{
		Type: pb.MsgHeartbeat.Enum(), From: new(uint64(3)), To: new(uint64(2)),
		Commit: new(uint64(10)), Context: nil,
	}
	err := follower.Step(termZero)
	emitCAEvent(t, map[string]any{
		"event": "t_term0_heartbeat", "node": 2, "sender": 3, "term": termZero.GetTerm(),
		"step_error": errStringCA(err), "lead_before": 1, "lead_after": leadOf(follower),
	})
}

// TestAssuranceForgetLeaderLegalTerm asks the boundary question that decides how
// much the main finding depends on the unset term field. Every receipt so far
// delivered the peer-form MsgForgetLeader with no term at all, and Step skips
// its whole term switch only for a zero term, so a reader could reasonably ask
// whether the accepted message is really the already-refuted term-zero path in
// disguise. This probe delivers the same type in a well-formed wire form - a
// real voter as sender and the follower's own current term - and measures the
// same three things: no error, the leader context, and the up-to-date
// candidate's pre-vote that the lease was withholding before.
func TestAssuranceForgetLeaderLegalTerm(t *testing.T) {
	leader, follower, candidate := caNewNode(t, 1), caNewNode(t, 2), caNewNode(t, 3)
	caElectNode1(t, leader, follower, candidate)

	// A real heartbeat tick: follower 2 hears from the leader, so its leader
	// context and its election-timer lease are live.
	leader.Tick()
	hbs := findMsgs(deliverReady(leader), pb.MsgHeartbeat, 2)
	if len(hbs) != 1 {
		t.Fatalf("expected one heartbeat for node 2, got %d", len(hbs))
	}
	emitCAEvent(t, map[string]any{
		"event": "u_setup", "node": 2, "lead_before": leadOf(follower),
		"leader_term": hbs[0].GetTerm(),
	})
	if err := follower.Step(hbs[0]); err != nil {
		t.Fatalf("step heartbeat on 2: %v", err)
	}
	emitCAEvent(t, map[string]any{
		"event": "u_control_heartbeat", "node": 2, "sender": 1, "term": hbs[0].GetTerm(),
		"lead_after": leadOf(follower),
	})

	// A real candidate produces a real MsgPreVote request; delivered under the
	// live lease it must produce no response at all.
	if err := candidate.Campaign(); err != nil {
		t.Fatalf("campaign 3: %v", err)
	}
	pv := findMsgs(deliverReady(candidate), pb.MsgPreVote, 2)
	if len(pv) != 1 {
		t.Fatalf("expected one pre-vote request for node 2, got %d", len(pv))
	}
	if err := follower.Step(pv[0]); err != nil {
		t.Fatalf("step pre-vote on 2 (under lease): %v", err)
	}
	rdLease := deliverReady(follower)
	respLease := findMsgs(rdLease, pb.MsgPreVoteResp, 3)
	emitCAEvent(t, map[string]any{
		"event": "u_prevote_under_lease", "node": 2, "candidate": 3, "phase": "under_lease",
		"candidate_term": pv[0].GetTerm(), "lead": leadOf(follower),
		"responded": len(respLease) > 0,
		"granted":   len(respLease) > 0 && !respLease[0].GetReject(),
	})

	// The wire form a peer could construct without leaving any field illegal:
	// From is the real voter 3, To is the follower, and Term is the follower's
	// own current term, which is what a peer that already knows this term sends.
	localTerm := follower.BasicStatus().HardState.GetTerm()
	if localTerm != 2 {
		t.Fatalf("expected the follower to be at term 2 after the real election, got %d", localTerm)
	}
	forged := &pb.Message{
		Type: pb.MsgForgetLeader.Enum(), From: new(uint64(3)), To: new(uint64(2)),
		Term: new(localTerm),
	}
	leadBefore := leadOf(follower)
	forgedErr := follower.Step(forged)
	emitCAEvent(t, map[string]any{
		"event": "u_legal_term_forget", "node": 2, "sender": 3, "term": forged.GetTerm(),
		"transport": "RawNode.Step", "accepted": forgedErr == nil, "step_error": errStringCA(forgedErr),
		"lead_before": leadBefore, "lead_after": leadOf(follower),
	})

	// The identical pre-vote request, delivered again after the accepted message.
	if err := follower.Step(pv[0]); err != nil {
		t.Fatalf("step pre-vote on 2 (after legal-term forget): %v", err)
	}
	rdAfter := deliverReady(follower)
	respAfter := findMsgs(rdAfter, pb.MsgPreVoteResp, 3)
	emitCAEvent(t, map[string]any{
		"event": "u_prevote_after_legal_term", "node": 2, "candidate": 3, "phase": "after_legal_term_forget",
		"candidate_term": pv[0].GetTerm(), "lead": leadOf(follower),
		"responded": len(respAfter) > 0,
		"granted":   len(respAfter) > 0 && !respAfter[0].GetReject(),
	})
}
