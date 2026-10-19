package epaxos

import (
	"bufio"
	"bytes"
	"fmt"
	"math/rand"
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
	return c.dispatch(m)
}

func (c *auditCluster) dispatch(m auditMessage) error {
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

// runShuffled delivers one randomly chosen queued message at a time.  It is a
// deterministic reordering test when seeded with a fixed RNG.
func (c *auditCluster) runShuffled(rng *rand.Rand, limit int) error {
	for n := 0; len(c.queue) > 0 && n < limit; n++ {
		i := rng.Intn(len(c.queue))
		m := c.queue[i]
		c.queue = append(c.queue[:i], c.queue[i+1:]...)
		if err := c.dispatch(m); err != nil {
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

// A fast quorum {0,1,2} chooses X, but the Commit broadcast is lost and the
// proposing leader 0 crashes.  Replica 4, which has no local copy, recovers
// from replicas 1 and 2 (which hold PREACCEPTED copies of X).  The chosen
// value must survive; the current recovery path replaces it with NOOP.
func TestAuditClusterChosenValueSurvivesLeaderCrash(t *testing.T) {
	c := newAuditCluster(5)
	c.drop = func(from, to int32, code uint8) bool { return code == auditCommitRPC }
	c.propose(0, 1, state.Command{Op: state.PUT, K: 7, V: state.Value("chosen")})
	if err := c.run(10000); err != nil {
		t.Fatal(err)
	}
	if inst := c.instance(0, 0, 0); inst == nil || inst.Status != COMMITTED || len(inst.Cmds) == 0 || inst.Cmds[0].K != 7 {
		t.Fatalf("leader did not fast-commit the chosen value: %+v", inst)
	}
	for _, i := range []int{1, 2} {
		if inst := c.instance(i, 0, 0); inst == nil || inst.Status != PREACCEPTED_EQ {
			t.Fatalf("replica %d is not holding the preaccepted chosen value: %+v", i, inst)
		}
	}
	for _, i := range []int{3, 4} {
		if inst := c.instance(i, 0, 0); inst != nil {
			t.Fatalf("replica %d unexpectedly has instance 0.0: %+v", i, inst)
		}
	}

	// Crash replica 0 and partition it; its Commit broadcast was already lost.
	for _, r := range c.reps {
		r.Alive[0] = false
	}
	c.drop = func(from, to int32, code uint8) bool { return from == 0 || to == 0 }
	c.reps[4].crtInstance[0] = 0
	c.reps[4].startRecoveryForInstance(0, 0)
	if err := c.run(10000); err != nil {
		t.Fatal(err)
	}

	for i := 0; i < 5; i++ {
		inst := c.instance(i, 0, 0)
		if inst == nil {
			t.Logf("replica %d: no instance", i)
			continue
		}
		t.Logf("replica %d: status=%d cmds=%v", i, inst.Status, inst.Cmds)
	}
	for _, i := range []int{1, 2, 4} {
		inst := c.instance(i, 0, 0)
		if inst == nil || inst.Status != COMMITTED || len(inst.Cmds) == 0 || inst.Cmds[0].K != 7 {
			t.Errorf("chosen value did not survive recovery at replica %d: %+v", i, inst)
		}
	}
}

// Control: reordering messages in the all-alive normal path should not change
// the committed instances or the final state.
func TestAuditClusterShuffledNormalPath(t *testing.T) {
	c := newAuditCluster(5)
	c.propose(0, 1, state.Command{Op: state.PUT, K: 7, V: state.Value("a")})
	c.propose(1, 2, state.Command{Op: state.PUT, K: 7, V: state.Value("b")})
	c.propose(2, 3, state.Command{Op: state.PUT, K: 8, V: state.Value("c")})
	rng := rand.New(rand.NewSource(1))
	if err := c.runShuffled(rng, 100000); err != nil {
		t.Fatal(err)
	}
	for row := int32(0); row < 3; row++ {
		for i := 0; i < 5; i++ {
			inst := c.instance(i, row, 0)
			if inst == nil || inst.Status != COMMITTED {
				t.Fatalf("replica %d instance %d.0 not committed: %+v", i, row, inst)
			}
		}
	}
	for i := 0; i < 5; i++ {
		for row := int32(0); row < 3; row++ {
			if ok := c.reps[i].exec.executeCommand(row, 0); !ok {
				t.Fatalf("replica %d could not execute %d.0", i, row)
			}
		}
	}
	first := ""
	for i := 0; i < 5; i++ {
		v7, _ := c.reps[i].State.Store.Get(state.Key(7))
		v8, _ := c.reps[i].State.Store.Get(state.Key(8))
		s := fmt.Sprintf("%v/%v", v7, v8)
		if i == 0 {
			first = s
		} else if s != first {
			t.Errorf("replica %d state %q differs from replica 0 %q", i, s, first)
		}
	}
	t.Logf("shuffled normal path converged: key7/key8=%q", first)
}

func TestAuditClusterShuffledSeeds(t *testing.T) {
	for seed := int64(1); seed <= 20; seed++ {
		seed := seed
		t.Run(fmt.Sprintf("seed%d", seed), func(t *testing.T) {
			c := newAuditCluster(5)
			c.propose(0, 1, state.Command{Op: state.PUT, K: 7, V: state.Value("a")})
			c.propose(1, 2, state.Command{Op: state.PUT, K: 7, V: state.Value("b")})
			c.propose(2, 3, state.Command{Op: state.PUT, K: 8, V: state.Value("c")})
			if err := c.runShuffled(rand.New(rand.NewSource(seed)), 100000); err != nil {
				t.Fatal(err)
			}
			for row := int32(0); row < 3; row++ {
				for i := 0; i < 5; i++ {
					if inst := c.instance(i, row, 0); inst == nil || inst.Status != COMMITTED {
						t.Fatalf("seed %d: replica %d instance %d.0 not committed: %+v", seed, i, row, inst)
					}
				}
			}
			for i := 0; i < 5; i++ {
				for row := int32(0); row < 3; row++ {
					if ok := c.reps[i].exec.executeCommand(row, 0); !ok {
						t.Fatalf("seed %d: replica %d could not execute %d.0", seed, i, row)
					}
				}
			}
			first := ""
			for i := 0; i < 5; i++ {
				v7, _ := c.reps[i].State.Store.Get(state.Key(7))
				v8, _ := c.reps[i].State.Store.Get(state.Key(8))
				s := fmt.Sprintf("%v/%v", v7, v8)
				if i == 0 {
					first = s
				} else if s != first {
					t.Errorf("seed %d: replica %d state %q differs from replica 0 %q", seed, i, s, first)
				}
			}
		})
	}
}

// A value chosen through the slow Accept path should be preserved just like a
// fast-chosen value when the proposing leader crashes before its Commit is
// delivered.
func TestAuditClusterSlowPathChosenValueSurvivesLeaderCrash(t *testing.T) {
	c := newAuditCluster(5)
	// Seed a conflicting committed instance on replica 1 so its PreAccept
	// reply has a different dependency vector and the leader takes the slow
	// Accept path.
	pivot := c.reps[1].newInstance(1, 5,
		[]state.Command{{Op: state.PUT, K: 7, V: state.Value("prior")}},
		0, 0, COMMITTED, 0, auditDeps(5))
	c.reps[1].InstanceSpace[1][5] = pivot
	c.reps[1].crtInstance[1] = 5
	c.reps[1].conflicts[1][7] = &InstPair{last: 5, lastWrite: 5}

	c.drop = func(from, to int32, code uint8) bool { return code == auditCommitRPC }
	c.propose(0, 1, state.Command{Op: state.PUT, K: 7, V: state.Value("chosen")})
	if err := c.run(10000); err != nil {
		t.Fatal(err)
	}
	leader := c.instance(0, 0, 0)
	if leader == nil || leader.Status != COMMITTED || len(leader.Cmds) == 0 || string(leader.Cmds[0].V) != "chosen" {
		t.Fatalf("leader did not commit the slow-path value: %+v", leader)
	}
	for _, i := range []int{1, 2} {
		inst := c.instance(i, 0, 0)
		if inst == nil || inst.Status < PREACCEPTED || len(inst.Cmds) == 0 || string(inst.Cmds[0].V) != "chosen" {
			t.Fatalf("replica %d is not holding the accepted slow-path value: %+v", i, inst)
		}
		t.Logf("before crash: replica %d status=%d cmds=%v", i, inst.Status, inst.Cmds)
	}

	// Crash the leader and partition it; its Commit broadcast was lost.
	for _, r := range c.reps {
		r.Alive[0] = false
	}
	c.drop = func(from, to int32, code uint8) bool { return from == 0 || to == 0 }
	c.reps[4].crtInstance[0] = 0
	c.reps[4].startRecoveryForInstance(0, 0)
	if err := c.run(10000); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 5; i++ {
		inst := c.instance(i, 0, 0)
		if inst == nil {
			t.Logf("replica %d: no instance", i)
			continue
		}
		t.Logf("replica %d: status=%d cmds=%v", i, inst.Status, inst.Cmds)
	}
	for _, i := range []int{1, 2, 4} {
		inst := c.instance(i, 0, 0)
		if inst == nil || inst.Status != COMMITTED || len(inst.Cmds) == 0 || string(inst.Cmds[0].V) != "chosen" {
			t.Errorf("slow-path chosen value did not survive recovery at replica %d: %+v", i, inst)
		}
	}
}

// Broader normal-path campaign: random 1-3 proposals on distinct replicas,
// random keys/values, and random message delivery.  Any divergence is a new
// normal-path counterexample; otherwise this extends the control coverage.
func TestAuditClusterRandomNormalCampaign(t *testing.T) {
	rng := rand.New(rand.NewSource(12345))
	for iter := 0; iter < 50; iter++ {
		c := newAuditCluster(5)
		m := 1 + rng.Intn(3)
		ops := make([]struct {
			rep int
			cmd state.Command
		}, m)
		for j := 0; j < m; j++ {
			key := int64(7 + rng.Intn(3))
			value := fmt.Sprintf("v%d-%d", iter, j)
			ops[j].rep = j
			ops[j].cmd = state.Command{Op: state.PUT, K: state.Key(key), V: state.Value(value)}
			c.propose(j, int32(iter*10+j), ops[j].cmd)
		}
		if err := c.runShuffled(rng, 100000); err != nil {
			t.Fatalf("iter %d: %v", iter, err)
		}
		for j, op := range ops {
			for i := 0; i < 5; i++ {
				inst := c.instance(i, int32(op.rep), 0)
				if inst == nil || inst.Status != COMMITTED || len(inst.Cmds) != 1 ||
					inst.Cmds[0].K != op.cmd.K || string(inst.Cmds[0].V) != string(op.cmd.V) {
					t.Fatalf("iter %d op %d: replica %d instance %d.0 mismatch: %+v", iter, j, i, op.rep, inst)
				}
			}
		}
		for i := 0; i < 5; i++ {
			for row := int32(0); row < int32(m); row++ {
				if ok := c.reps[i].exec.executeCommand(row, 0); !ok {
					t.Fatalf("iter %d: replica %d could not execute %d.0", iter, i, row)
				}
			}
		}
		want := ""
		for i := 0; i < 5; i++ {
			stateStr := ""
			for key := int64(7); key <= 9; key++ {
				v, present := c.reps[i].State.Store.Get(state.Key(key))
				stateStr += fmt.Sprintf("%d:%v:%v;", key, v, present)
			}
			if i == 0 {
				want = stateStr
			} else if stateStr != want {
				t.Fatalf("iter %d: state mismatch replica %d=%q replica 0=%q ops=%v", iter, i, stateStr, want, ops)
			}
		}
	}
}

// Same F1 path, but the old leader is partitioned rather than crashed.  After
// the live replicas recover to NOOP, healing the partition and re-broadcasting
// the Commit leaves the old leader with the chosen value and the rest with
// NOOP: all replicas are alive, but they disagree.
func TestAuditClusterPartitionedLeaderKeepsChosenValue(t *testing.T) {
	c := newAuditCluster(5)
	c.drop = func(from, to int32, code uint8) bool { return code == auditCommitRPC }
	c.propose(0, 1, state.Command{Op: state.PUT, K: 7, V: state.Value("chosen")})
	if err := c.run(10000); err != nil {
		t.Fatal(err)
	}
	if inst := c.instance(0, 0, 0); inst == nil || inst.Status != COMMITTED || len(inst.Cmds) == 0 || inst.Cmds[0].K != 7 {
		t.Fatalf("leader did not fast-commit the chosen value: %+v", inst)
	}

	for _, r := range c.reps {
		r.Alive[0] = false
	}
	c.drop = func(from, to int32, code uint8) bool { return from == 0 || to == 0 }
	c.reps[4].crtInstance[0] = 0
	c.reps[4].startRecoveryForInstance(0, 0)
	if err := c.run(10000); err != nil {
		t.Fatal(err)
	}
	if inst := c.instance(4, 0, 0); inst == nil || inst.Status != COMMITTED || len(inst.Cmds) == 0 || inst.Cmds[0].Op != state.NONE {
		t.Fatalf("live replicas did not recover to NOOP: %+v", inst)
	}

	// Heal the partition and re-broadcast the recovery Commit to the old
	// leader.  Its instance is already COMMITTED with the chosen value.
	for _, r := range c.reps {
		r.Alive[0] = true
	}
	c.drop = nil
	c.reps[4].bcastCommit(0, 0)
	if err := c.run(10000); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 5; i++ {
		inst := c.instance(i, 0, 0)
		if inst == nil {
			t.Logf("replica %d: no instance", i)
			continue
		}
		t.Logf("replica %d: status=%d cmds=%v", i, inst.Status, inst.Cmds)
	}
	for i := 0; i < 5; i++ {
		inst := c.instance(i, 0, 0)
		if inst == nil || inst.Status != COMMITTED || len(inst.Cmds) == 0 || inst.Cmds[0].K != 7 {
			t.Errorf("replica %d does not hold the chosen PUT after healing: %+v", i, inst)
		}
	}
	for i := 0; i < 5; i++ {
		if ok := c.reps[i].exec.executeCommand(0, 0); !ok {
			t.Logf("replica %d could not execute 0.0", i)
		}
	}
	for i := 0; i < 5; i++ {
		v, present := c.reps[i].State.Store.Get(state.Key(7))
		t.Logf("replica %d state: key7=%v present=%v", i, v, present)
	}
}

// Which replica initiates recovery after the fast-chosen leader crashes?  A
// recoverer that already holds the value (1 or 2) may preserve it; one that
// has no local value (3 or 4) falls into the F1 NOOP path.
func TestAuditClusterRecovererMatrix(t *testing.T) {
	for _, recoverer := range []int{1, 2, 3, 4} {
		recoverer := recoverer
		t.Run(fmt.Sprintf("recoverer%d", recoverer), func(t *testing.T) {
			c := newAuditCluster(5)
			c.drop = func(from, to int32, code uint8) bool { return code == auditCommitRPC }
			c.propose(0, 1, state.Command{Op: state.PUT, K: 7, V: state.Value("chosen")})
			if err := c.run(10000); err != nil {
				t.Fatal(err)
			}
			if inst := c.instance(0, 0, 0); inst == nil || inst.Status != COMMITTED || len(inst.Cmds) == 0 || inst.Cmds[0].K != 7 {
				t.Fatalf("leader did not fast-commit the chosen value: %+v", inst)
			}

			for _, r := range c.reps {
				r.Alive[0] = false
			}
			c.drop = func(from, to int32, code uint8) bool { return from == 0 || to == 0 }
			c.reps[recoverer].crtInstance[0] = 0
			c.reps[recoverer].startRecoveryForInstance(0, 0)
			if err := c.run(10000); err != nil {
				t.Fatal(err)
			}
			for i := 0; i < 5; i++ {
				inst := c.instance(i, 0, 0)
				if inst == nil {
					t.Logf("recoverer=%d replica %d: no instance", recoverer, i)
					continue
				}
				t.Logf("recoverer=%d replica %d: status=%d cmds=%v", recoverer, i, inst.Status, inst.Cmds)
			}
			for i := 1; i < 5; i++ {
				inst := c.instance(i, 0, 0)
				if inst == nil || inst.Status != COMMITTED || len(inst.Cmds) == 0 || inst.Cmds[0].K != 7 {
					t.Errorf("recoverer=%d: replica %d does not hold the chosen value: %+v", recoverer, i, inst)
				}
			}
		})
	}
}
