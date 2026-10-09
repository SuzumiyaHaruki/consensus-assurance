package epaxos

import (
	"bufio"
	"bytes"
	"encoding/binary"
	"testing"

	"github.com/imdea-software/swiftpaxos/dlog"
	"github.com/imdea-software/swiftpaxos/replica"
	"github.com/imdea-software/swiftpaxos/replica/defs"
	"github.com/imdea-software/swiftpaxos/state"
)

// Small, synchronous replicas avoid constructor goroutines and large allocation.
// Protocol handlers, serialization, dependency tracking, and execution are original.
func auditReplica(id int32) (*Replica, []*bytes.Buffer) {
	b := &replica.Replica{N: 3, F: 1, Id: id, Thrifty: true, Dreply: true, Logger: dlog.New("", false), State: state.InitState(), Stats: &defs.Stats{M: make(map[string]int)}, Alive: []bool{true, true, true}, PeerWriters: make([]*bufio.Writer, 3)}
	r := &Replica{Replica: b, InstanceSpace: make([][]*Instance, 3), crtInstance: []int32{-1, -1, -1}, CommittedUpTo: []int32{-1, -1, -1}, ExecedUpTo: []int32{-1, -1, -1}, conflicts: make([]map[state.Key]*InstPair, 3), maxSeqPerKey: make(map[state.Key]int32), maxRecvBallot: -1}
	out := make([]*bytes.Buffer, 3)
	for q := 0; q < 3; q++ {
		r.InstanceSpace[q] = make([]*Instance, 16)
		r.conflicts[q] = make(map[state.Key]*InstPair)
		out[q] = new(bytes.Buffer)
		b.PeerWriters[q] = bufio.NewWriter(out[q])
		if int32(q) != id {
			b.PreferredPeerOrder = append(b.PreferredPeerOrder, int32(q))
		}
	}
	r.exec = &Exec{r}
	return r, out
}
func auditPut(k state.Key, v string) []state.Command {
	return []state.Command{{Op: state.PUT, K: k, V: state.Value(v)}}
}
func auditReadPrepare(t *testing.T, b *bytes.Buffer) *PrepareReply {
	t.Helper()
	if _, e := b.ReadByte(); e != nil {
		t.Fatal(e)
	}
	p := new(PrepareReply)
	if e := p.Unmarshal(b); e != nil {
		t.Fatal(e)
	}
	return p
}

func TestAuditAcceptDoesNotRecordAccepted(t *testing.T) {
	for _, preaccepted := range []bool{false, true} {
		t.Run(map[bool]string{false: "empty", true: "preaccepted"}[preaccepted], func(t *testing.T) {
			r, out := auditReplica(1)
			if preaccepted {
				r.handlePreAccept(&PreAccept{LeaderId: 0, Replica: 0, Instance: 0, Ballot: 0, Command: auditPut(10, "x"), Seq: 0, Deps: []int32{-1, -1, -1}})
				out[0].Reset()
			}
			r.handleAccept(&Accept{LeaderId: 0, Replica: 0, Instance: 0, Ballot: 0, Seq: 7, Deps: []int32{-1, -1, -1}})
			out[0].Reset()
			r.handlePrepare(&Prepare{LeaderId: 2, Replica: 0, Instance: 0, Ballot: 5})
			p := auditReadPrepare(t, out[2])
			t.Logf("after successful Accept, Prepare reports status=%d (ACCEPTED=%d), seq=%d vbal=%d", p.Status, ACCEPTED, p.Seq, p.VBallot)
			if p.Status != ACCEPTED {
				t.Errorf("acknowledged Accept was not retained as ACCEPTED")
			}
		})
	}
}

func TestAuditRecoveryDiscardsCommittedValue(t *testing.T) {
	r, _ := auditReplica(1)
	other, out := auditReplica(2)
	// Establish the original commit through real initial-ballot handlers.
	leader, leaderOut := auditReplica(0)
	leader.PreferredPeerOrder = []int32{2, 1}
	leader.startPhase1(auditPut(10, "chosen"), 0, 0, 0, nil)
	leaderOut[2].ReadByte()
	initialPA := new(PreAccept)
	if e := initialPA.Unmarshal(leaderOut[2]); e != nil {
		t.Fatal(e)
	}
	other.handlePreAccept(initialPA)
	out[0].ReadByte()
	initialReply := new(PreAcceptReply)
	if e := initialReply.Unmarshal(out[0]); e != nil {
		t.Fatal(e)
	}
	leader.handlePreAcceptReply(initialReply)
	leaderOut[2].ReadByte()
	initialCommit := new(Commit)
	if e := initialCommit.Unmarshal(leaderOut[2]); e != nil {
		t.Fatal(e)
	}
	other.handleCommit(initialCommit)
	if leader.InstanceSpace[0][0].Status != COMMITTED || other.InstanceSpace[0][0].Status != COMMITTED {
		t.Fatal("initial commit failed")
	}
	// The commit queued for replica 1 remains undelivered. No further leader steps.

	// Replica 0 crashes; replica 1 missed its command. Replica 2 retained commit.
	r.startRecoveryForInstance(0, 0)
	ballot := r.InstanceSpace[0][0].lb.lastTriedBallot
	other.handlePrepare(&Prepare{LeaderId: 1, Replica: 0, Instance: 0, Ballot: ballot})
	p := auditReadPrepare(t, out[1])
	t.Logf("peer reports committed value: status=%d vbal=%d cmds=%v", p.Status, p.VBallot, p.Command)
	r.handlePrepareReply(p)
	inst := r.InstanceSpace[0][0]
	t.Logf("after prepare quorum: status=%d cmds=%v", inst.Status, inst.Cmds)
	// Drive the new phase 1 and phase 2 through the remaining live peer.
	lb := inst.lb
	other.handlePreAccept(&PreAccept{LeaderId: 1, Replica: 0, Instance: 0, Ballot: lb.lastTriedBallot, Command: lb.cmds, Seq: lb.seq, Deps: append([]int32(nil), lb.deps...)})
	out[1].ReadByte()
	pa := new(PreAcceptReply)
	if e := pa.Unmarshal(out[1]); e != nil {
		t.Fatal(e)
	}
	r.handlePreAcceptReply(pa)
	lb = r.InstanceSpace[0][0].lb
	other.handleAccept(&Accept{LeaderId: 1, Replica: 0, Instance: 0, Ballot: lb.lastTriedBallot, Seq: lb.seq, Deps: append([]int32(nil), lb.deps...)})
	out[1].ReadByte()
	ar := new(AcceptReply)
	if e := ar.Unmarshal(out[1]); e != nil {
		t.Fatal(e)
	}
	r.handleAcceptReply(ar)
	inst = r.InstanceSpace[0][0]
	t.Logf("final replica1 status=%d cmds=%v; replica2 status=%d cmds=%v", inst.Status, inst.Cmds, other.InstanceSpace[0][0].Status, other.InstanceSpace[0][0].Cmds)
	if inst.Status == COMMITTED && inst.Cmds[0].Op == state.NONE {
		t.Error("recovery committed NOOP for a slot already committed as PUT")
	}
}

func TestAuditBatchDependencySkipsLaterCommand(t *testing.T) {
	r, _ := auditReplica(0)
	for i, k := range []state.Key{10, 20} {
		r.InstanceSpace[1][i] = r.newInstance(1, int32(i), auditPut(k, "old"), 1, 1, COMMITTED, int32(i), []int32{-1, -1, -1})
		r.updateConflicts(r.InstanceSpace[1][i].Cmds, 1, int32(i), int32(i))
	}
	batch := append(auditPut(10, "new"), auditPut(20, "new")...)
	seq, deps, _ := r.updateAttributes(batch, 0, []int32{-1, -1, -1}, 0, 0)
	t.Logf("batch conflicts with row1 instances 0 and 1; resulting seq=%d deps=%v", seq, deps)
	// The same committed log yields different final state under two delivery/execution orders.
	var values []string
	for _, priorFirst := range []bool{false, true} {
		x, _ := auditReplica(0)
		for i, k := range []state.Key{10, 20} {
			x.InstanceSpace[1][i] = x.newInstance(1, int32(i), auditPut(k, "old"), 1, 1, COMMITTED, int32(i), []int32{-1, -1, -1})
		}
		x.InstanceSpace[0][0] = x.newInstance(0, 0, batch, 0, 0, COMMITTED, seq, append([]int32(nil), deps...))
		if priorFirst {
			if !x.exec.executeCommand(1, 1) {
				t.Fatal("prior execution blocked")
			}
		}
		if !x.exec.executeCommand(0, 0) {
			t.Fatal("batch execution blocked")
		}
		if !x.exec.executeCommand(1, 1) {
			t.Fatal("prior execution blocked")
		}
		get := state.Command{Op: state.GET, K: 20}
		values = append(values, string(get.Execute(x.State)))
	}
	t.Logf("same committed log, batch-first final key20=%q; prior-first final key20=%q", values[0], values[1])
	// Control: reverse the batch order; the first conflict is now the maximum.
	_, reverseDeps, _ := r.updateAttributes([]state.Command{batch[1], batch[0]}, 0, []int32{-1, -1, -1}, 0, 0)
	if reverseDeps[1] != 1 {
		t.Fatal("control failed")
	}
	if deps[1] != 1 || values[0] != values[1] {
		t.Error("dependency on later conflicting command missing; execution can diverge")
	}
}

func TestAuditScanDependencyMissing(t *testing.T) {
	for _, scanFirst := range []bool{false, true} {
		t.Run(map[bool]string{false: "put_then_scan", true: "scan_then_put"}[scanFirst], func(t *testing.T) {
			r, _ := auditReplica(0)
			v := make([]byte, 8)
			binary.LittleEndian.PutUint64(v, 10)
			scan := []state.Command{{Op: state.SCAN, K: 10, V: v}}
			put := auditPut(15, "x")
			prior, next := put, scan
			if scanFirst {
				prior, next = scan, put
			}
			if !state.ConflictBatch(prior, next) {
				t.Fatal("bad test: commands must conflict")
			}
			r.InstanceSpace[1][0] = r.newInstance(1, 0, prior, 1, 1, COMMITTED, 0, []int32{-1, -1, -1})
			r.updateConflicts(prior, 1, 0, 0)
			_, deps, _ := r.updateAttributes(next, 0, []int32{-1, -1, -1}, 0, 0)
			t.Logf("state.ConflictBatch=true but deps=%v", deps)
			if deps[1] != 0 {
				t.Error("range conflict omitted from dependencies")
			}
		})
	}
}
