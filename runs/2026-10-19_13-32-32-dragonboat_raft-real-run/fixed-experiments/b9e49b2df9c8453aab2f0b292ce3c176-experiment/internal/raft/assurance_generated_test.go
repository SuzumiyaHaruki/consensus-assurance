package raft

import (
	"fmt"
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

func TestAssuranceReadIndexDiscardedOnStepDown(t *testing.T) {
	r := newTestRaft(1, []uint64{1, 2, 3}, 10, 1, NewTestLogDB())
	r.becomeCandidate()
	r.becomeLeader()
	r.remotes[2].match = r.log.lastIndex()
	committed := r.tryCommit()
	atTerm := r.hasCommittedEntryAtCurrentTerm()
	r.Handle(pb.Message{From: 1, To: 1, Type: pb.ReadIndex, Hint: 4242, HintHigh: 77})
	registered := r.readIndex.hasPendingRequest()
	fmt.Printf("CA_EVENT {\"event\":\"registered\",\"node\":1,\"committed\":%t,\"at_term\":%t,\"registered\":%t}\n", committed, atTerm, registered)
	r.Handle(pb.Message{From: 1, To: 1, Type: pb.CheckQuorum})
	stillLeader := r.isLeader()
	dropped := len(r.droppedReadIndexes)
	pending := r.readIndex.hasPendingRequest()
	fmt.Printf("CA_EVENT {\"event\":\"step_down\",\"node\":1,\"still_leader\":%t,\"dropped\":%d,\"pending\":%t}\n", stillLeader, dropped, pending)
	before := len(r.readyToRead)
	r.Handle(pb.Message{From: 2, To: 1, Term: r.term, Type: pb.HeartbeatResp, Hint: 4242, HintHigh: 77})
	added := len(r.readyToRead) - before
	fmt.Printf("CA_EVENT {\"event\":\"stale_resp\",\"node\":1,\"ready_added\":%d}\n", added)
	if stillLeader {
		t.Fatalf("leader did not step down")
	}
	if dropped != 0 {
		t.Fatalf("step down reported dropped read contexts: %d", dropped)
	}
	if pending {
		t.Fatalf("read context survived step down")
	}
	if added != 0 {
		t.Fatalf("stale response added ready to read entries: %d", added)
	}
}
