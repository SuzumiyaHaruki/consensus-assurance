package epaxos

import (
	"bytes"
	"github.com/imdea-software/swiftpaxos/state"
	"testing"
)

func TestAuditLocalTimeChangesSCCOrder(t *testing.T) {
	rs := make([]*Replica, 5)
	outs := make([][]*bytes.Buffer, 5)
	for i := range rs {
		rs[i], outs[i] = auditReplicaN(int32(i), 5)
	}
	// Establish the common prior write through the original fast path.
	rs[1].crtInstance[1] = 0
	rs[1].startPhase1(auditPut(10, "seed"), 1, 0, 1, nil)
	for _, q := range []int{0, 2} {
		auditDeliver(t, outs[1][q], rs[q], new(PreAccept))
		auditDeliver(t, outs[q][1], rs[1], new(PreAcceptReply))
	}
	for _, q := range []int{0, 2, 3, 4} {
		auditDeliver(t, outs[1][q], rs[q], new(Commit))
	}
	rs[0].PreferredPeerOrder = []int32{3, 4, 1, 2}
	rs[2].PreferredPeerOrder = []int32{0, 1, 3, 4}
	// B is a read; delay its PreAccept to replica 1.
	rs[2].crtInstance[2] = 0
	rs[2].startPhase1([]state.Command{{Op: state.GET, K: 10}}, 2, 0, 2, nil)
	auditDeliver(t, outs[2][0], rs[0], new(PreAccept))
	auditDeliver(t, outs[0][2], rs[2], new(PreAcceptReply))
	// Two conflicting writes in the same row depend on B.
	rs[0].crtInstance[0] = 0
	rs[0].startPhase1(auditPut(10, "A0"), 0, 0, 0, nil)
	rs[0].crtInstance[0] = 1
	rs[0].startPhase1(auditPut(10, "A1"), 0, 1, 0, nil)
	for _, q := range []int{3, 4} {
		msgs := make([]*PreAccept, 2)
		for i := range msgs {
			outs[0][q].ReadByte()
			msgs[i] = new(PreAccept)
			if e := msgs[i].Unmarshal(outs[0][q]); e != nil {
				t.Fatal(e)
			}
		}
		if q == 3 {
			rs[q].handlePreAccept(msgs[0])
			rs[q].handlePreAccept(msgs[1])
		} else {
			rs[q].handlePreAccept(msgs[1])
			rs[q].handlePreAccept(msgs[0])
		}
	}
	for _, q := range []int{3, 4} {
		for i := 0; i < 2; i++ {
			auditDeliver(t, outs[q][0], rs[0], new(PreAcceptReply))
		}
	}
	for _, q := range []int{1, 2, 3, 4} {
		for i := 0; i < 2; i++ {
			auditDeliver(t, outs[0][q], rs[q], new(Commit))
		}
	}
	// B's second voter now sees A1. This closes the cycle through both writes.
	auditDeliver(t, outs[2][1], rs[1], new(PreAccept))
	auditDeliver(t, outs[1][2], rs[2], new(PreAcceptReply))
	if rs[2].InstanceSpace[2][0].Status != ACCEPTED {
		t.Fatal("B must enter slow path")
	}
	for _, q := range []int{0, 1} {
		auditDeliver(t, outs[2][q], rs[q], new(Accept))
		auditDeliver(t, outs[q][2], rs[2], new(AcceptReply))
	}
	for _, q := range []int{0, 1, 3, 4} {
		auditDeliver(t, outs[2][q], rs[q], new(Commit))
	}
	var results []string
	for _, q := range []int{3, 4} {
		a0, a1, b := rs[q].InstanceSpace[0][0], rs[q].InstanceSpace[0][1], rs[q].InstanceSpace[2][0]
		t.Logf("replica%d A0 seq=%d deps=%v time=%d; A1 seq=%d deps=%v time=%d; B seq=%d deps=%v", q, a0.Seq, a0.Deps, a0.proposeTime, a1.Seq, a1.Deps, a1.proposeTime, b.Seq, b.Deps)
		if !rs[q].exec.executeCommand(0, 0) {
			t.Fatal("execution blocked")
		}
		get := state.Command{Op: state.GET, K: 10}
		results = append(results, string(get.Execute(rs[q].State)))
	}
	t.Logf("same committed commands/attributes: replica3 key10=%q replica4 key10=%q", results[0], results[1])
	if results[0] != results[1] {
		t.Error("SCC ordering by local arrival timestamp diverges")
	}
}
