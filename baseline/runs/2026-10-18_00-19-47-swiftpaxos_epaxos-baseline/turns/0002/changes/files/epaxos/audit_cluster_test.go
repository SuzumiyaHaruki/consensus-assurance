package epaxos

import (
	"bufio"
	"bytes"
	"fmt"
	"sync"
	"testing"

	"github.com/imdea-software/swiftpaxos/replica/defs"
	"github.com/imdea-software/swiftpaxos/state"
)

const (
	auditPrepareRPC = uint8(defs.RPC_TABLE) + iota
	auditPrepareReplyRPC
	auditPreAcceptRPC
	auditPreAcceptReplyRPC
	auditAcceptRPC
	auditAcceptReplyRPC
	auditCommitRPC
	auditTryPreAcceptRPC
	auditTryPreAcceptReplyRPC
)

type auditMessage struct {
	from int32
	to   int32
	code uint8
	data []byte
}

type auditRouterWriter struct {
	c    *auditCluster
	from int32
	to   int32
}

func (w *auditRouterWriter) Write(p []byte) (int, error) {
	data := append([]byte(nil), p...)
	w.c.queue = append(w.c.queue, auditMessage{from: w.from, to: w.to, code: data[0], data: data[1:]})
	return len(p), nil
}

type auditCluster struct {
	reps  []*Replica
	queue []auditMessage
	drop  func(from, to int32, code uint8) bool
}

func newAuditCluster(n int) *auditCluster {
	c := &auditCluster{}
	for i := 0; i < n; i++ {
		r := auditReplica(n, int32(i), 128)
		r.prepareRPC = auditPrepareRPC
		r.prepareReplyRPC = auditPrepareReplyRPC
		r.preAcceptRPC = auditPreAcceptRPC
		r.preAcceptReplyRPC = auditPreAcceptReplyRPC
		r.acceptRPC = auditAcceptRPC
		r.acceptReplyRPC = auditAcceptReplyRPC
		r.commitRPC = auditCommitRPC
		r.tryPreAcceptRPC = auditTryPreAcceptRPC
		r.tryPreAcceptReplyRPC = auditTryPreAcceptReplyRPC
		c.reps = append(c.reps, r)
	}
	for i := 0; i < n; i++ {
		for j := 0; j < n; j++ {
			w := &auditRouterWriter{c: c, from: int32(i), to: int32(j)}
			c.reps[i].PeerWriters[j] = bufio.NewWriterSize(w, 1<<20)
		}
	}
	// One replica is the configured recovery leader, as the master would set.
	c.reps[0].IsLeader = true
	return c
}

func (c *auditCluster) dispatchOne() error {
	if len(c.queue) == 0 {
		return nil
	}
	m := c.queue[0]
	c.queue = c.queue[1:]
	if c.drop != nil && c.drop(m.from, m.to, m.code) {
		return nil
	}
	if int(m.to) < 0 || int(m.to) >= len(c.reps) {
		return fmt.Errorf("message to invalid replica %d", m.to)
	}
	dst := c.reps[m.to]
	rd := bytes.NewReader(m.data)
	switch m.code {
	case auditPrepareRPC:
		msg := &Prepare{}
		if err := msg.Unmarshal(rd); err != nil {
			return err
		}
		dst.handlePrepare(msg)
	case auditPrepareReplyRPC:
		msg := &PrepareReply{}
		if err := msg.Unmarshal(rd); err != nil {
			return err
		}
		dst.handlePrepareReply(msg)
	case auditPreAcceptRPC:
		msg := &PreAccept{}
		if err := msg.Unmarshal(rd); err != nil {
			return err
		}
		dst.handlePreAccept(msg)
	case auditPreAcceptReplyRPC:
		msg := &PreAcceptReply{}
		if err := msg.Unmarshal(rd); err != nil {
			return err
		}
		dst.handlePreAcceptReply(msg)
	case auditAcceptRPC:
		msg := &Accept{}
		if err := msg.Unmarshal(rd); err != nil {
			return err
		}
		dst.handleAccept(msg)
	case auditAcceptReplyRPC:
		msg := &AcceptReply{}
		if err := msg.Unmarshal(rd); err != nil {
			return err
		}
		dst.handleAcceptReply(msg)
	case auditCommitRPC:
		msg := &Commit{}
		if err := msg.Unmarshal(rd); err != nil {
			return err
		}
		dst.handleCommit(msg)
	case auditTryPreAcceptRPC:
		msg := &TryPreAccept{}
		if err := msg.Unmarshal(rd); err != nil {
			return err
		}
		dst.handleTryPreAccept(msg)
	case auditTryPreAcceptReplyRPC:
		msg := &TryPreAcceptReply{}
		if err := msg.Unmarshal(rd); err != nil {
			return err
		}
		dst.handleTryPreAcceptReply(msg)
	default:
		return fmt.Errorf("unknown RPC code %d", m.code)
	}
	return nil
}

func (c *auditCluster) run(limit int) error {
	for n := 0; len(c.queue) > 0 && n < limit; n++ {
		if err := c.dispatchOne(); err != nil {
			return err
		}
	}
	if len(c.queue) > 0 {
		return fmt.Errorf("message queue did not drain (%d left)", len(c.queue))
	}
	return nil
}

func (c *auditCluster) propose(from int, commandID int32, cmd state.Command) {
	reply := bufio.NewWriter(new(bytes.Buffer))
	c.reps[from].handlePropose(&defs.GPropose{
		Propose: &defs.Propose{ClientId: 1, CommandId: commandID, Command: cmd},
		Reply:   reply,
		Mutex:   new(sync.Mutex),
	})
}

func (c *auditCluster) instance(rep int, row, idx int32) *Instance {
	return c.reps[rep].InstanceSpace[row][idx]
}

// Happy path: one proposal should be fast-committed and executed on all five
// replicas when no messages are dropped.
func TestAuditClusterHappyPath(t *testing.T) {
	c := newAuditCluster(5)
	c.propose(0, 1, state.Command{Op: state.PUT, K: 7, V: state.Value("value")})
	if err := c.run(10000); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 5; i++ {
		inst := c.instance(i, 0, 0)
		if inst == nil {
			t.Fatalf("replica %d has no instance 0.0", i)
		}
		if inst.Status != COMMITTED {
			t.Errorf("replica %d status=%d, want COMMITTED", i, inst.Status)
		}
		if len(inst.Cmds) != 1 || inst.Cmds[0].K != 7 {
			t.Errorf("replica %d Cmds=%v", i, inst.Cmds)
		}
		if ok := c.reps[i].exec.executeCommand(0, 0); !ok {
			t.Errorf("replica %d could not execute 0.0", i)
		}
		v, present := c.reps[i].State.Store.Get(state.Key(7))
		if !present || string(v.(state.Value)) != "value" {
			t.Errorf("replica %d state value=%v present=%v", i, v, present)
		}
	}
}

// A replica that missed the commit starts recovery for the instance.  The
// first Prepare reply is the committed value, but the local synthetic reply
// masks it (F1); phase 1 then starts with NOOP.  The first PreAccept reply
// from a committed replica is adopted, which makes the status guard ignore
// every later reply (F14), so recovery does not complete.
func TestAuditClusterRecoveryStalls(t *testing.T) {
	c := newAuditCluster(5)
	// Partition replica 4 for the initial proposal and commit.
	c.drop = func(from, to int32, code uint8) bool { return from == 4 || to == 4 }
	c.propose(0, 1, state.Command{Op: state.PUT, K: 7, V: state.Value("value")})
	if err := c.run(10000); err != nil {
		t.Fatal(err)
	}
	if c.instance(4, 0, 0) != nil {
		t.Fatal("replica 4 unexpectedly learned instance 0.0 while partitioned")
	}
	for i := 0; i < 4; i++ {
		if inst := c.instance(i, 0, 0); inst == nil || inst.Status != COMMITTED {
			t.Fatalf("replica %d did not commit the initial value: %+v", i, inst)
		}
	}

	c.drop = nil
	// Simulate the replica learning that instance 0.0 exists (for example from
	// a later protocol message); executeCommands would then time out and call
	// startRecoveryForInstance.
	c.reps[4].crtInstance[0] = 0
	c.reps[4].startRecoveryForInstance(0, 0)
	if err := c.run(10000); err != nil {
		t.Fatal(err)
	}

	got := c.instance(4, 0, 0)
	if got != nil {
		t.Logf("replica 4 after recovery: status=%d bal=%d vbal=%d cmds=%v",
			got.Status, got.bal, got.vbal, got.Cmds)
		if got.lb != nil {
			t.Logf("replica 4 bookkeeping: status=%d ballot=%d lastTried=%d preAcceptOKs=%d",
				got.lb.status, got.lb.ballot, got.lb.lastTriedBallot, got.lb.preAcceptOKs)
		}
	}
	if got != nil && got.Status == COMMITTED && len(got.Cmds) == 1 && got.Cmds[0].K == 7 {
		t.Logf("recovery did complete with the original value")
		return
	}
	t.Errorf("recovery for partitioned replica did not complete with the committed value: %+v", got)
}

// N=7 with three crashed replicas leaves four live replicas (a slow majority).
// The fast quorum of five is impossible, and the current slow-path threshold
// still asks for four PreAccept replies from peers, so the proposal never
// reaches Accept.
func TestAuditClusterN7FailureStalls(t *testing.T) {
	c := newAuditCluster(7)
	for _, r := range c.reps {
		for _, failed := range []int{4, 5, 6} {
			r.Alive[failed] = false
		}
	}
	c.drop = func(from, to int32, code uint8) bool {
		if from == 4 || from == 5 || from == 6 || to == 4 || to == 5 || to == 6 {
			return true
		}
		return false
	}
	c.propose(0, 1, state.Command{Op: state.PUT, K: 7, V: state.Value("value")})
	if err := c.run(10000); err != nil {
		t.Fatal(err)
	}
	inst := c.instance(0, 0, 0)
	if inst == nil {
		t.Fatal("leader did not create instance 0.0")
	}
	t.Logf("N=7, three failed replicas: leader instance status=%d preAcceptOKs=%d",
		inst.Status, inst.lb.preAcceptOKs)
	if inst.Status != COMMITTED {
		t.Errorf("proposal did not commit with a live slow majority; status=%d", inst.Status)
	}
}

// Control: two concurrent conflicting proposals should still commit and
// execute in the same order on every replica.
func TestAuditClusterConflictPath(t *testing.T) {
	c := newAuditCluster(5)
	c.propose(0, 1, state.Command{Op: state.PUT, K: 7, V: state.Value("a")})
	c.propose(1, 2, state.Command{Op: state.PUT, K: 7, V: state.Value("b")})
	if err := c.run(10000); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 5; i++ {
		for row := int32(0); row < 2; row++ {
			inst := c.instance(i, row, 0)
			if inst == nil || inst.Status != COMMITTED {
				t.Fatalf("replica %d instance %d.0 not committed: %+v", i, row, inst)
			}
		}
	}
	for i := 0; i < 5; i++ {
		for row := int32(0); row < 2; row++ {
			if ok := c.reps[i].exec.executeCommand(row, 0); !ok {
				t.Fatalf("replica %d could not execute %d.0", i, row)
			}
		}
	}
	var first, last string
	for i := 0; i < 5; i++ {
		v, present := c.reps[i].State.Store.Get(state.Key(7))
		if !present {
			t.Fatalf("replica %d lost key 7", i)
		}
		s := string(v.(state.Value))
		if i == 0 {
			first = s
		}
		last = s
	}
	if first != last {
		t.Errorf("replicas diverged: first=%q last=%q", first, last)
	}
	t.Logf("conflicting proposals executed; final value=%q", first)
}
