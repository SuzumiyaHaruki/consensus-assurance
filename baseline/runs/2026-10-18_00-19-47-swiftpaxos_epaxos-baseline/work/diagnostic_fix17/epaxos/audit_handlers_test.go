package epaxos

import (
	"bufio"
	"bytes"
	"os"
	"sync"
	"testing"

	"github.com/imdea-software/swiftpaxos/config"
	"github.com/imdea-software/swiftpaxos/dlog"
	"github.com/imdea-software/swiftpaxos/replica"
	"github.com/imdea-software/swiftpaxos/replica/defs"
	"github.com/imdea-software/swiftpaxos/state"
)

// auditCaptureReply installs a writer for peer and returns the bytes that the
// handler sends to that peer.
func auditCaptureReply(r *Replica, peer int32) (*bytes.Buffer, *bufio.Writer) {
	buf := new(bytes.Buffer)
	w := bufio.NewWriter(buf)
	r.PeerWriters[peer] = w
	return buf, w
}

// auditReplica builds an EPaxos replica without starting the network loop, so
// handlers can be driven synchronously from a test.  All outbound RPCs are
// no-ops because PeerWriters contains nil writers.
func auditReplica(n int, id int32, slots int) *Replica {
	rr := &replica.Replica{
		Logger:             dlog.New("", false),
		M:                  sync.Mutex{},
		N:                  n,
		F:                  (n - 1) / 2,
		Id:                 id,
		PeerAddrList:       make([]string, n),
		PeerWriters:        make([]*bufio.Writer, n),
		PeerReaders:        make([]*bufio.Reader, n),
		Alive:              make([]bool, n),
		PreferredPeerOrder: make([]int32, n),
		State:              state.InitState(),
		Stats:              &defs.Stats{M: make(map[string]int)},
		ProposeChan:        make(chan *defs.GPropose, 8),
		Thrifty:            true,
		Exec:               true,
		Dreply:             true,
	}
	for i := 0; i < n; i++ {
		rr.Alive[i] = true
		rr.PreferredPeerOrder[i] = int32((int(id) + 1 + i) % n)
	}

	r := &Replica{
		Replica:            rr,
		InstanceSpace:      make([][]*Instance, n),
		crtInstance:        make([]int32, n),
		CommittedUpTo:      make([]int32, n),
		ExecedUpTo:         make([]int32, n),
		conflicts:          make([]map[state.Key]*InstPair, n),
		maxSeqPerKey:       make(map[state.Key]int32),
		clientMutex:        new(sync.Mutex),
		instancesToRecover: make(chan *instanceId, 8),
		IsLeader:           true,
		maxRecvBallot:      -1,
	}
	for i := 0; i < n; i++ {
		r.InstanceSpace[i] = make([]*Instance, slots)
		r.crtInstance[i] = -1
		r.CommittedUpTo[i] = -1
		r.ExecedUpTo[i] = -1
		r.conflicts[i] = make(map[state.Key]*InstPair)
	}
	r.exec = &Exec{r}
	return r
}

func auditDeps(n int, vals ...int32) []int32 {
	d := make([]int32, n)
	for i := range d {
		d[i] = -1
	}
	for i := 0; i < len(vals) && i < n; i++ {
		d[i] = vals[i]
	}
	return d
}

// An acceptor that receives an Accept message must record ACCEPTED.  This is
// the state that handlePrepare reports as case 2 of the recovery algorithm.
func TestInvestigationAcceptStatus(t *testing.T) {
	r := auditReplica(5, 0, 64)
	r.handleAccept(&Accept{LeaderId: 1, Replica: 1, Instance: 0, Ballot: 0,
		Seq: 4, Deps: auditDeps(5)})

	inst := r.InstanceSpace[1][0]
	if inst == nil {
		t.Fatal("instance was not created")
	}
	t.Logf("after Accept: Status=%d bal=%d vbal=%d Seq=%d Cmds=%v",
		inst.Status, inst.bal, inst.vbal, inst.Seq, inst.Cmds)
	if inst.Status != ACCEPTED {
		t.Errorf("accepted instance Status=%v, want ACCEPTED (%v)", inst.Status, ACCEPTED)
	}

	// The same state is what a subsequent Prepare reports to a recovering
	// leader.  Capture and decode that reply over the wire.
	buf, _ := auditCaptureReply(r, 1)
	r.handlePrepare(&Prepare{LeaderId: 1, Replica: 1, Instance: 0, Ballot: 0})
	raw := buf.Bytes()
	if len(raw) < 2 {
		t.Fatalf("no PrepareReply was sent (got %d bytes)", len(raw))
	}
	reply := &PrepareReply{}
	if err := reply.Unmarshal(bytes.NewReader(raw[1:])); err != nil {
		t.Fatalf("decode PrepareReply: %v", err)
	}
	t.Logf("PrepareReply for the accepted instance: Status=%d VBallot=%d Command=%v Seq=%d",
		reply.Status, reply.VBallot, reply.Command, reply.Seq)
	if reply.Status != ACCEPTED {
		t.Errorf("PrepareReply.Status=%v, want ACCEPTED", reply.Status)
	}
}

// When an acceptor already holds the command from PreAccept, there is no
// no-command ambiguity: accepting it should advance its status to ACCEPTED.
func TestAuditAcceptWithCommandMarksAccepted(t *testing.T) {
	r := auditReplica(5, 0, 64)
	cmds := []state.Command{{Op: state.PUT, K: 1, V: state.Value("x")}}
	inst := r.newInstance(1, 0, cmds, 0, 0, PREACCEPTED_EQ, 0, auditDeps(5))
	r.InstanceSpace[1][0] = inst
	r.handleAccept(&Accept{LeaderId: 0, Replica: 1, Instance: 0, Ballot: 0,
		Seq: 0, Deps: auditDeps(5)})
	t.Logf("after Accept with command present: status=%d cmds=%v", inst.Status, inst.Cmds)
	if inst.Status != ACCEPTED {
		t.Errorf("status=%d, want ACCEPTED (%d) for an acceptor that already holds the command",
			inst.Status, ACCEPTED)
	}
}

// TryPreAccept is the recovery path that pre-accepts a value at a new ballot.
// A successful responder must report that ballot as VBallot; otherwise the
// recovering leader's handleTryPreAcceptReply treats the reply as a nack.
func TestAuditTryPreAcceptRecordsVBallot(t *testing.T) {
	r := auditReplica(5, 0, 64)
	const ballot = int32(7)
	buf, _ := auditCaptureReply(r, 3)
	r.handleTryPreAccept(&TryPreAccept{LeaderId: 3, Replica: 3, Instance: 0,
		Ballot: ballot, Command: []state.Command{{Op: state.PUT, K: 1, V: state.Value("x")}},
		Seq: 0, Deps: auditDeps(5)})

	inst := r.InstanceSpace[3][0]
	if inst == nil {
		t.Fatal("instance was not created")
	}
	t.Logf("after TryPreAccept: Status=%d bal=%d vbal=%d", inst.Status, inst.bal, inst.vbal)
	if inst.Status != PREACCEPTED {
		t.Fatalf("Status=%v, want PREACCEPTED", inst.Status)
	}
	if inst.vbal != ballot {
		t.Errorf("vbal=%d, want %d; reply would carry a VBallot that does not equal the leader's lastTriedBallot", inst.vbal, ballot)
	}

	raw := buf.Bytes()
	if len(raw) < 2 {
		t.Fatalf("no TryPreAcceptReply was sent (got %d bytes)", len(raw))
	}
	reply := &TryPreAcceptReply{}
	if err := reply.Unmarshal(bytes.NewReader(raw[1:])); err != nil {
		t.Fatalf("decode TryPreAcceptReply: %v", err)
	}
	t.Logf("TryPreAcceptReply: Ballot=%d VBallot=%d Status=%d", reply.Ballot, reply.VBallot, reply.ConflictStatus)
	if reply.VBallot != ballot {
		t.Errorf("reply VBallot=%d, want %d; handleTryPreAcceptReply requires equality to count acceptance", reply.VBallot, ballot)
	}
}

// A reply with a newer ballot must count as a nack and eventually force a new
// prepare.  In handleAcceptReply the "newer ballot" branch is unreachable
// because the preceding != check returns first.
func TestAuditAcceptReplyCountsHigherBallotAsNack(t *testing.T) {
	r := auditReplica(5, 0, 64)
	inst := r.newInstance(1, 0, []state.Command{{Op: state.PUT, K: 1, V: state.Value("x")}},
		0, 0, PREACCEPTED, 0, auditDeps(5))
	inst.Status = ACCEPTED
	inst.lb = r.newLeaderBookkeeping(nil, auditDeps(5), auditDeps(5), auditDeps(5), 0, inst.Cmds, ACCEPTED, 0)
	r.InstanceSpace[1][0] = inst

	r.handleAcceptReply(&AcceptReply{Replica: 1, Instance: 0, Ballot: 1})
	t.Logf("after higher-ballot AcceptReply: nacks=%d lastTriedBallot=%d",
		inst.lb.nacks, inst.lb.lastTriedBallot)
	if inst.lb.nacks == 0 {
		t.Errorf("higher-ballot reply was silently discarded: nacks=%d, so the leader never re-prepares", inst.lb.nacks)
	}
}

// A PreAccept for instance (replica, instance) must update that instance.
// When a recovering leader (LeaderId != Replica) retries PreAccept for an
// instance already accepted without a stored command, the current code writes
// the command into the leader's row instead.
func TestAuditPreAcceptStoresCommandInAddressedInstance(t *testing.T) {
	r := auditReplica(5, 1, 64)
	// Unrelated instance in the leader's row at the same instance number.
	other := r.newInstance(3, 0, []state.Command{{Op: state.PUT, K: 99, V: state.Value("keep")}},
		0, 0, COMMITTED, 1, auditDeps(5))
	r.InstanceSpace[3][0] = other
	// Target instance: accepted metadata but no command stored locally.
	target := r.newInstance(0, 0, nil, 0, 0, ACCEPTED, 2, auditDeps(5))
	r.InstanceSpace[0][0] = target

	r.handlePreAccept(&PreAccept{LeaderId: 3, Replica: 0, Instance: 0,
		Ballot: 0, Command: []state.Command{{Op: state.PUT, K: 1, V: state.Value("new")}},
		Seq: 2, Deps: auditDeps(5)})

	if target.Cmds != nil {
		t.Logf("target now has Cmds=%v", target.Cmds)
	} else {
		t.Logf("target Cmds is still nil")
	}
	t.Logf("unrelated [3][0] Cmds=%v", other.Cmds)
	if len(other.Cmds) > 0 && other.Cmds[0].K == 1 {
		t.Errorf("PreAccept for replica 0 wrote its command into instance [leader=3][0], overwriting unrelated command %v", other.Cmds)
	}
	if target.Cmds == nil {
		t.Errorf("PreAccept for replica 0 did not store the command in the addressed instance [0][0]")
	}
}

// If the leader's row does not already contain the same instance number, the
// out-of-place store above dereferences a nil *Instance and crashes the
// replica.
func TestAuditPreAcceptOutOfPlaceStoreDoesNotPanic(t *testing.T) {
	r := auditReplica(5, 1, 64)
	target := r.newInstance(0, 0, nil, 0, 0, ACCEPTED, 2, auditDeps(5))
	r.InstanceSpace[0][0] = target
	defer func() {
		if p := recover(); p != nil {
			t.Errorf("handlePreAccept panicked because instance [leader=3][0] was nil: %v", p)
		}
	}()
	r.handlePreAccept(&PreAccept{LeaderId: 3, Replica: 0, Instance: 0,
		Ballot: 0, Command: []state.Command{{Op: state.PUT, K: 1, V: state.Value("new")}},
		Seq: 2, Deps: auditDeps(5)})
}

// The synthetic local PrepareReply that starts recovery should report the
// value ballot of the locally stored value, not the new prepare ballot.
func TestAuditRecoveryLocalReplyKeepsValueBallot(t *testing.T) {
	r := auditReplica(5, 0, 64)
	r.IsLeader = false
	inst := r.newInstance(2, 0, []state.Command{{Op: state.PUT, K: 1, V: state.Value("x")}},
		5, 2, ACCEPTED, 3, auditDeps(5))
	r.InstanceSpace[2][0] = inst
	oldBal, oldVBal := inst.bal, inst.vbal

	r.startRecoveryForInstance(2, 0)
	lb := inst.lb
	if len(lb.prepareReplies) != 1 {
		t.Fatalf("prepareReplies=%d, want 1", len(lb.prepareReplies))
	}
	reply := lb.prepareReplies[0]
	t.Logf("old bal=%d old vbal=%d new lastTriedBallot=%d local reply Ballot=%d VBallot=%d Status=%d",
		oldBal, oldVBal, lb.lastTriedBallot, reply.Ballot, reply.VBallot, reply.Status)
	if reply.VBallot == lb.lastTriedBallot {
		t.Errorf("local reply VBallot=%d equals the new prepare ballot %d; the pre-recovery value ballot 5 was overwritten",
			reply.VBallot, lb.lastTriedBallot)
	}
}

// Safety consequence of the local VBallot overwrite: the synthetic local
// PrepareReply reports the new prepare ballot as its value ballot even though
// its status is NONE and it carries no command.  That reply then masks every
// remote reply at a real (lower) value ballot, and recovery phase 1 restarts
// with NOOP instead of the value a quorum already committed.
func TestAuditRecoveryDoesNotDiscardCommittedRemoteValue(t *testing.T) {
	r := auditReplica(5, 0, 64)
	r.IsLeader = true
	r.maxRecvBallot = 9 // makeBallot => 10

	// No local copy of instance 2.0.
	r.startRecoveryForInstance(2, 0)
	inst := r.InstanceSpace[2][0]
	if inst == nil || inst.lb == nil {
		t.Fatal("recovery did not create local bookkeeping")
	}
	ballot := inst.lb.lastTriedBallot
	cmds := []state.Command{{Op: state.PUT, K: 42, V: state.Value("committed")}}
	for _, acceptor := range []int32{3, 4} {
		r.handlePrepareReply(&PrepareReply{
			AcceptorId: acceptor,
			Replica:    2,
			Instance:   0,
			Ballot:     ballot,
			VBallot:    7,
			Status:     COMMITTED,
			Command:    cmds,
			Seq:        4,
			Deps:       auditDeps(5),
		})
	}

	inst = r.InstanceSpace[2][0]
	if inst.Status == COMMITTED && len(inst.Cmds) > 0 && inst.Cmds[0].K == 42 {
		t.Logf("recovery preserved the committed command")
		return
	}
	t.Errorf("recovery discarded the committed command: Status=%v Cmds=%v (phase-1 result)", inst.Status, inst.Cmds)
}

// A local PREACCEPTED value must not win over remote COMMITTED values just
// because the synthetic local reply claims the new prepare ballot.
func TestAuditRecoveryPrefersRemoteCommittedOverLocalPreaccepted(t *testing.T) {
	r := auditReplica(5, 0, 64)
	r.IsLeader = true
	r.maxRecvBallot = 9 // makeBallot => 10
	deps := auditDeps(5)
	local := []state.Command{{Op: state.PUT, K: 1, V: state.Value("local")}}
	remote := []state.Command{{Op: state.PUT, K: 2, V: state.Value("remote")}}
	inst := r.newInstance(2, 0, local, 2, 2, PREACCEPTED, 0, deps)
	r.InstanceSpace[2][0] = inst
	r.startRecoveryForInstance(2, 0)
	ballot := inst.lb.lastTriedBallot

	for _, acceptor := range []int32{1, 3} {
		r.handlePrepareReply(&PrepareReply{
			AcceptorId: acceptor, Replica: 2, Instance: 0, Ballot: ballot,
			VBallot: 5, Status: COMMITTED, Command: remote, Seq: 1, Deps: deps})
	}
	got := r.InstanceSpace[2][0]
	if got != nil && len(got.Cmds) > 0 {
		t.Logf("recovery kept local=%v; selected key=%d", local, got.Cmds[0].K)
	}
	if got == nil || len(got.Cmds) == 0 || got.Cmds[0].K != 2 {
		t.Errorf("recovery did not prefer the remote COMMITTED value at VBallot 5 over the local PREACCEPTED value at VBallot 2: %+v", got)
	}
}

// Matrix over the local recovery state and the remote reply status.  In every
// case the remote value at VBallot=5 should win over a local value at vbal<=2.
func TestAuditRecoveryMatrix(t *testing.T) {
	type localCase struct {
		name   string
		cmds   []state.Command
		status int8
		bal    int32
		vbal   int32
	}
	locals := []localCase{
		{name: "localNone", cmds: nil, status: NONE, bal: -1, vbal: -1},
		{name: "localPreaccepted", cmds: []state.Command{{Op: state.PUT, K: 1, V: state.Value("local")}},
			status: PREACCEPTED, bal: 2, vbal: 2},
	}
	remotes := []struct {
		name   string
		status int8
	}{
		{name: "remotePreacceptedEQ", status: PREACCEPTED_EQ},
		{name: "remoteAccepted", status: ACCEPTED},
		{name: "remoteCommitted", status: COMMITTED},
	}

	for _, local := range locals {
		for _, remote := range remotes {
			local, remote := local, remote
			t.Run(local.name+"/"+remote.name, func(t *testing.T) {
				r := auditReplica(5, 0, 64)
				r.IsLeader = true
				r.maxRecvBallot = 9 // makeBallot => 10
				deps := auditDeps(5)
				remoteCmd := []state.Command{{Op: state.PUT, K: 2, V: state.Value("remote")}}
				inst := r.newInstance(2, 0, local.cmds, local.bal, local.vbal, local.status, 0, deps)
				r.InstanceSpace[2][0] = inst
				r.startRecoveryForInstance(2, 0)
				ballot := inst.lb.lastTriedBallot
				for i := int32(0); i < 2; i++ {
					r.handlePrepareReply(&PrepareReply{
						AcceptorId: i + 1, Replica: 2, Instance: 0, Ballot: ballot,
						VBallot: 5, Status: remote.status, Command: remoteCmd, Seq: 1, Deps: deps})
				}
				got := r.InstanceSpace[2][0]
				if got != nil && len(got.Cmds) > 0 {
					t.Logf("local=%s remote=%s selected key=%d", local.name, remote.name, got.Cmds[0].K)
				}
				if got == nil || len(got.Cmds) == 0 || got.Cmds[0].K != 2 {
					t.Errorf("recovery did not select the remote value at VBallot 5: %+v", got)
				}
			})
		}
	}
}

// Even without the synthetic local reply, PrepareReply.VBallot is not encoded
// on the wire.  A stale PREACCEPTED value from a later-arriving reply then
// replaces an ACCEPTED value from an earlier reply at a higher value ballot.
func TestAuditPrepareRepliesPreserveValueBallotOrdering(t *testing.T) {
	r := auditReplica(5, 0, 64)
	const ballot = int32(10)
	inst := r.newInstance(2, 0, nil, ballot, ballot, NONE, -1, auditDeps(5))
	inst.lb = r.newLeaderBookkeeping(nil, auditDeps(5), auditDeps(5), auditDeps(5), ballot, nil, NONE, -1)
	inst.lb.preparing = true
	inst.lb.leaderResponded = true
	inst.lb.ballot = -1
	r.InstanceSpace[2][0] = inst
	// The recovering leader's own NONE reply (normally appended by
	// startRecoveryForInstance); it carries no value.
	inst.lb.prepareReplies = append(inst.lb.prepareReplies, &PrepareReply{
		AcceptorId: 0, Replica: 2, Instance: 0, Ballot: ballot, VBallot: -1, Status: NONE})

	encode := func(in *PrepareReply) *PrepareReply {
		t.Helper()
		var buf bytes.Buffer
		in.Marshal(&buf)
		out := &PrepareReply{}
		if err := out.Unmarshal(bytes.NewReader(buf.Bytes())); err != nil {
			t.Fatalf("decode: %v", err)
		}
		return out
	}
	accepted := []state.Command{{Op: state.PUT, K: 1, V: state.Value("accepted")}}
	stale := []state.Command{{Op: state.PUT, K: 1, V: state.Value("stale")}}
	high := encode(&PrepareReply{AcceptorId: 1, Replica: 2, Instance: 0, Ballot: ballot,
		VBallot: 7, Status: ACCEPTED, Command: accepted, Seq: 4, Deps: auditDeps(5)})
	low := encode(&PrepareReply{AcceptorId: 3, Replica: 2, Instance: 0, Ballot: ballot,
		VBallot: 5, Status: PREACCEPTED, Command: stale, Seq: 3, Deps: auditDeps(5)})
	t.Logf("decoded VBallots: high=%d low=%d", high.VBallot, low.VBallot)

	r.handlePrepareReply(high)
	r.handlePrepareReply(low)

	got := r.InstanceSpace[2][0]
	if got != nil && len(got.Cmds) > 0 {
		t.Logf("recovery selected %v (Status=%v)", got.Cmds, got.Status)
	}
	if got == nil || len(got.Cmds) == 0 || string(got.Cmds[0].V) != "accepted" {
		t.Errorf("recovery did not keep the ACCEPTED value at VBallot 7; selected %v", got)
	}
}

// A replica can receive a Commit for an instance in its own row that it did not
// create (for example, after a restart or after another replica recovered that
// instance).  handleCommit creates a default instance with lb == nil and then
// dereferences inst.lb.clientProposals.
func TestAuditCommitForUnknownOwnInstanceDoesNotPanic(t *testing.T) {
	r := auditReplica(5, 0, 64)
	defer func() {
		if p := recover(); p != nil {
			t.Errorf("handleCommit panicked on an own-row instance with no bookkeeping: %v", p)
		}
	}()
	r.handleCommit(&Commit{LeaderId: 1, Replica: 0, Instance: 0, Ballot: 0,
		Command: state.NOOP(), Seq: 0, Deps: auditDeps(5)})
	if inst := r.InstanceSpace[0][0]; inst == nil || inst.Status != COMMITTED {
		t.Errorf("commit was not applied: %+v", inst)
	}
}

// recordInstanceMetadata is only active in durable mode (the shipped run.go
// passes durable=false).  Check the on-disk header layout so the limitation of
// that mode is explicit.
func TestAuditDurableMetadataLayout(t *testing.T) {
	f, err := os.CreateTemp(t.TempDir(), "epaxos-stable-*")
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()

	r := auditReplica(5, 0, 64)
	r.StableStore = f
	r.Durable = true
	inst := r.newInstance(0, 0, nil, 7, 3, PREACCEPTED, 11, auditDeps(5))
	r.recordInstanceMetadata(inst)
	if _, err := f.Seek(0, 0); err != nil {
		t.Fatal(err)
	}
	buf := make([]byte, 13+5*4)
	n, _ := f.Read(buf)
	t.Logf("metadata bytes (%d): % x", n, buf[:n])
	if n < 13 {
		t.Fatalf("short metadata: %d", n)
	}
	bal := int32(uint32(buf[0]) | uint32(buf[1])<<8 | uint32(buf[2])<<16 | uint32(buf[3])<<24)
	vbal := int32(uint32(buf[4]) | uint32(buf[5])<<8 | uint32(buf[6])<<16 | uint32(buf[7])<<24)
	status := int8(buf[8])
	t.Logf("decoded: bal=%d vbal=%d status=%d", bal, vbal, status)
	if bal != 7 || vbal != 3 || status != PREACCEPTED {
		t.Errorf("metadata does not preserve bal/vbal/status independently: got bal=%d vbal=%d status=%d", bal, vbal, status)
	}
}

// findPreAcceptConflicts must consider the target instance itself when it
// already holds a different PREACCEPTED value.  The loop breaks at
// i == instance before applying the normal conflict test.
func TestInvestigationSelfConflictSkip(t *testing.T) {
	r := auditReplica(5, 0, 64)
	oldCmd := []state.Command{{Op: state.PUT, K: 1, V: state.Value("old")}}
	inst := r.newInstance(0, 0, oldCmd, 0, 0, PREACCEPTED, 1, auditDeps(5))
	r.InstanceSpace[0][0] = inst
	r.crtInstance[0] = 0
	r.ExecedUpTo[0] = -1

	newCmd := []state.Command{{Op: state.PUT, K: 1, V: state.Value("new")}}
	conflict, cr, ci := r.findPreAcceptConflicts(newCmd, 0, 0, 2, auditDeps(5))
	t.Logf("findPreAcceptConflicts(different PREACCEPTED value) = %v conflict at %d.%d", conflict, cr, ci)
	if !conflict {
		t.Errorf("a different PREACCEPTED value for the target instance was not reported as a conflict")
	}
}

// updateAttributes must consider every command in a batch.  It currently
// breaks at the first command that adds a dependency for a replica, so a
// later command with a newer dependency on the same replica is lost.
func TestAuditUpdateAttributesConsidersWholeBatch(t *testing.T) {
	r := auditReplica(5, 0, 64)
	r.conflicts[1][100] = &InstPair{last: 5, lastWrite: 5}
	r.conflicts[1][200] = &InstPair{last: 9, lastWrite: 9}
	r.InstanceSpace[1][5] = r.newInstance(1, 5, nil, 0, 0, COMMITTED, 1, auditDeps(5))
	r.InstanceSpace[1][9] = r.newInstance(1, 9, nil, 0, 0, COMMITTED, 2, auditDeps(5))

	cmds := []state.Command{
		{Op: state.PUT, K: 100, V: state.Value("a")},
		{Op: state.PUT, K: 200, V: state.Value("b")},
	}
	seq, deps, _ := r.updateAttributes(cmds, 0, auditDeps(5), 0, 0)
	t.Logf("updateAttributes batch => seq=%d deps=%v", seq, deps)
	if deps[1] != 9 {
		t.Errorf("dependency on replica 1 is %d, want 9 (newest conflicting instance in the batch)", deps[1])
	}
	if seq != 3 {
		t.Errorf("seq is %d, want 3 (one beyond the newest conflicting instance's seq)", seq)
	}
}

// End-to-end version of the batch-dependency test through handlePropose:
// queue a second proposal before handling the first, so handlePropose drains
// both into one instance.
func TestAuditBatchedProposalUsesNewestDependency(t *testing.T) {
	r := auditReplica(5, 0, 64)
	r.conflicts[1][100] = &InstPair{last: 5, lastWrite: 5}
	r.conflicts[1][200] = &InstPair{last: 9, lastWrite: 9}
	r.InstanceSpace[1][5] = r.newInstance(1, 5, nil, 0, 0, COMMITTED, 1, auditDeps(5))
	r.InstanceSpace[1][9] = r.newInstance(1, 9, nil, 0, 0, COMMITTED, 2, auditDeps(5))

	first := &defs.GPropose{Propose: &defs.Propose{CommandId: 1, ClientId: 1,
		Command: state.Command{Op: state.PUT, K: 100, V: state.Value("a")}}}
	second := &defs.GPropose{Propose: &defs.Propose{CommandId: 2, ClientId: 1,
		Command: state.Command{Op: state.PUT, K: 200, V: state.Value("b")}}}
	r.ProposeChan <- second
	r.handlePropose(first)

	inst := r.InstanceSpace[0][0]
	if inst == nil {
		t.Fatal("proposal did not create instance 0.0")
	}
	t.Logf("batched instance: seq=%d deps=%v cmds=%v", inst.Seq, inst.Deps, inst.Cmds)
	if inst.Deps[1] != 9 || inst.Seq != 3 {
		t.Errorf("batched proposal has seq=%d deps[1]=%d, want seq=3 deps[1]=9", inst.Seq, inst.Deps[1])
	}
}

// replica.New evaluates defs.IP() even when no latency file is configured.
// defs.IP ignores the error from net.Dial and dereferences conn.
func TestAuditIPHelperDoesNotPanic(t *testing.T) {
	defer func() {
		if p := recover(); p != nil {
			t.Errorf("defs.IP panicked in this environment: %v", p)
		}
	}()
	t.Logf("defs.IP() = %q", defs.IP())
}

// This is the startup path used by epaxos.New.  It must not require a route to
// 8.8.8.8 when no latency file is configured.
func TestAuditReplicaConstructionDoesNotRequireExternalRoute(t *testing.T) {
	defer func() {
		if p := recover(); p != nil {
			t.Errorf("replica.New panicked during startup: %v", p)
		}
	}()
	_ = replica.New("a", 0, 1, []string{"127.0.0.1:10000"}, true, false, false,
		&config.Config{}, dlog.New("", false))
}

// A TryPreAccept that hits an ACCEPTED/COMMITTED conflict must report that
// status; the leader uses ConflictStatus >= ACCEPTED to abandon the attempt.
func TestAuditTryPreAcceptReportsConflictStatus(t *testing.T) {
	r := auditReplica(5, 0, 64)
	conflict := r.newInstance(1, 5, []state.Command{{Op: state.PUT, K: 1, V: state.Value("old")}},
		0, 0, COMMITTED, 3, auditDeps(5))
	r.InstanceSpace[1][5] = conflict
	r.crtInstance[1] = 5
	r.crtInstance[0] = 0
	buf, _ := auditCaptureReply(r, 3)
	r.handleTryPreAccept(&TryPreAccept{LeaderId: 3, Replica: 0, Instance: 0, Ballot: 7,
		Command: []state.Command{{Op: state.PUT, K: 1, V: state.Value("new")}},
		Seq:     0, Deps: auditDeps(5)})

	raw := buf.Bytes()
	if len(raw) < 2 {
		t.Fatal("no TryPreAcceptReply was sent")
	}
	reply := &TryPreAcceptReply{}
	if err := reply.Unmarshal(bytes.NewReader(raw[1:])); err != nil {
		t.Fatal(err)
	}
	t.Logf("TryPreAcceptReply: conflict=%d.%d status=%d", reply.ConflictReplica, reply.ConflictInstance, reply.ConflictStatus)
	if reply.ConflictStatus != COMMITTED {
		t.Errorf("ConflictStatus=%d, want COMMITTED (%d) for the conflicting instance", reply.ConflictStatus, COMMITTED)
	}
}

// A TryPreAccept that installs a PREACCEPTED value must also update the
// replica's conflict hash table; otherwise later proposals on the same key
// can miss the dependency even though the instance is present in InstanceSpace.
func TestAuditTryPreAcceptUpdatesConflicts(t *testing.T) {
	r := auditReplica(5, 0, 64)
	cmd := state.Command{Op: state.PUT, K: 55, V: state.Value("try")}
	r.handleTryPreAccept(&TryPreAccept{LeaderId: 3, Replica: 3, Instance: 0, Ballot: 7,
		Command: []state.Command{cmd}, Seq: 0, Deps: auditDeps(5)})
	inst := r.InstanceSpace[3][0]
	if inst == nil || inst.Status != PREACCEPTED {
		t.Fatalf("TryPreAccept did not install a preaccepted value: %+v", inst)
	}
	pair := r.conflicts[3][cmd.K]
	t.Logf("conflicts[3][%d] = %+v", cmd.K, pair)
	if pair == nil {
		t.Errorf("TryPreAccept installed a PREACCEPTED command but left the conflict table empty")
	}
}

// The same omission exists when a recovery leader learns a COMMITTED value
// from PrepareReply sub-case 1 and installs it in its Instance.
func TestAuditPrepareReplyUpdatesConflicts(t *testing.T) {
	r := auditReplica(5, 0, 64)
	deps := auditDeps(5)
	cmd := state.Command{Op: state.PUT, K: 66, V: state.Value("recovered")}
	inst := r.newInstance(2, 0, nil, 10, 10, NONE, -1, deps)
	inst.lb = r.newLeaderBookkeeping(nil, deps, deps, deps, 10, nil, NONE, -1)
	inst.lb.preparing = true
	inst.lb.ballot = -1
	inst.lb.prepareReplies = append(inst.lb.prepareReplies, &PrepareReply{
		AcceptorId: 0, Replica: 2, Instance: 0, Ballot: 10, VBallot: -1, Status: NONE})
	r.InstanceSpace[2][0] = inst
	for i := int32(0); i < 2; i++ {
		r.handlePrepareReply(&PrepareReply{AcceptorId: i + 1, Replica: 2, Instance: 0,
			Ballot: 10, VBallot: 0, Status: COMMITTED, Command: []state.Command{cmd},
			Seq: 0, Deps: deps})
	}
	t.Logf("after PrepareReply sub-case 1: instance status=%d cmds=%v conflicts=%+v",
		inst.Status, inst.Cmds, r.conflicts[2][cmd.K])
	if inst.Status != COMMITTED || len(inst.Cmds) == 0 {
		t.Fatalf("recovery did not install the committed value: %+v", inst)
	}
	if r.conflicts[2][cmd.K] == nil {
		t.Errorf("recovery installed a committed command but left the conflict table empty")
	}
}

// Consequence of F17: after recovery installs a committed value without
// updating the conflict table, a later proposal on the same key omits the
// dependency on the recovered instance.
func TestAuditPrepareReplyConflictMiss(t *testing.T) {
	r := auditReplica(5, 0, 64)
	deps := auditDeps(5)
	cmd := state.Command{Op: state.PUT, K: 66, V: state.Value("recovered")}
	inst := r.newInstance(2, 0, nil, 10, 10, NONE, -1, deps)
	inst.lb = r.newLeaderBookkeeping(nil, deps, deps, deps, 10, nil, NONE, -1)
	inst.lb.preparing = true
	inst.lb.ballot = -1
	inst.lb.prepareReplies = append(inst.lb.prepareReplies, &PrepareReply{
		AcceptorId: 0, Replica: 2, Instance: 0, Ballot: 10, VBallot: -1, Status: NONE})
	r.InstanceSpace[2][0] = inst
	for i := int32(0); i < 2; i++ {
		r.handlePrepareReply(&PrepareReply{AcceptorId: i + 1, Replica: 2, Instance: 0,
			Ballot: 10, VBallot: 0, Status: COMMITTED, Command: []state.Command{cmd},
			Seq: 0, Deps: deps})
	}
	if inst.Status != COMMITTED || len(inst.Cmds) == 0 {
		t.Fatalf("recovery did not install the committed value: %+v", inst)
	}

	r.handlePropose(&defs.GPropose{Propose: &defs.Propose{
		ClientId: 1, CommandId: 1,
		Command: state.Command{Op: state.PUT, K: 66, V: state.Value("new")},
	}, Reply: bufio.NewWriter(new(bytes.Buffer)), Mutex: new(sync.Mutex)})
	newInst := r.InstanceSpace[0][0]
	if newInst == nil {
		t.Fatal("new proposal did not create instance 0.0")
	}
	t.Logf("new proposal deps=%v (recovered instance is 2.0)", newInst.Deps)
	if newInst.Deps[2] != 0 {
		t.Errorf("new proposal deps[2]=%d, want 0; it misses the recovered committed key", newInst.Deps[2])
	}
}

// A recovery/accept round at a higher ballot must broadcast Commit at that
// ballot.  bcastCommit uses lb.ballot, which can still be the older value
// ballot; acceptors with inst.bal at the newer ballot then ignore the Commit.
func TestAuditRecoveryCommitUsesCurrentBallot(t *testing.T) {
	r := auditReplica(5, 0, 64)
	deps := auditDeps(5)
	cmds := []state.Command{{Op: state.PUT, K: 77, V: state.Value("recovered")}}
	inst := r.newInstance(2, 0, cmds, 9, 9, ACCEPTED, 0, deps)
	inst.lb = r.newLeaderBookkeeping(nil, deps, deps, deps, 9, cmds, COMMITTED, 0)
	inst.lb.ballot = 0 // value ballot from the original PreAccept
	r.InstanceSpace[2][0] = inst
	buf, _ := auditCaptureReply(r, 1)
	r.bcastCommit(2, 0)
	raw := buf.Bytes()
	if len(raw) < 2 {
		t.Fatal("bcastCommit sent no Commit")
	}
	commit := &Commit{}
	if err := commit.Unmarshal(bytes.NewReader(raw[1:])); err != nil {
		t.Fatal(err)
	}
	t.Logf("Commit.Ballot=%d (current lastTriedBallot=%d, value ballot=%d)",
		commit.Ballot, inst.lb.lastTriedBallot, inst.lb.ballot)
	if commit.Ballot != inst.lb.lastTriedBallot {
		t.Errorf("Commit.Ballot=%d, want the current/lastTried ballot %d; acceptors at that ballot ignore the Commit",
			commit.Ballot, inst.lb.lastTriedBallot)
	}
}

// A stale reply after a restart can refer to an instance this replica no
// longer has.  The reply handlers must ignore it rather than dereferencing
// inst.lb first.
func TestAuditReplyHandlersUnknownInstanceDoNotPanic(t *testing.T) {
	tests := []struct {
		name string
		call func(*Replica)
	}{
		{"PrepareReply", func(r *Replica) {
			r.handlePrepareReply(&PrepareReply{AcceptorId: 1, Replica: 2, Instance: 0,
				Ballot: 0, VBallot: 0, Status: COMMITTED})
		}},
		{"PreAcceptReply", func(r *Replica) {
			r.handlePreAcceptReply(&PreAcceptReply{Replica: 2, Instance: 0,
				Ballot: 0, VBallot: 0, Status: COMMITTED})
		}},
		{"AcceptReply", func(r *Replica) {
			r.handleAcceptReply(&AcceptReply{Replica: 2, Instance: 0, Ballot: 0})
		}},
	}
	for _, tc := range tests {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			r := auditReplica(5, 0, 64)
			defer func() {
				if p := recover(); p != nil {
					t.Errorf("%s panicked on an unknown instance: %v", tc.name, p)
				}
			}()
			tc.call(r)
		})
	}
}

// A recovery leader that collects a majority of higher-ballot prepare replies
// must move to a new ballot and retry, as handlePreAcceptReply and
// paxos.handlePrepareReply do.  Otherwise responders that have all advanced
// past the recovery ballot leave the recovery waiting forever.
func TestAuditPrepareReplyHigherBallotRetriesRecovery(t *testing.T) {
	r := auditReplica(5, 0, 64)
	r.IsLeader = true
	r.prepareRPC = 99
	deps := auditDeps(5)
	inst := r.newInstance(2, 0, nil, 5, 5, NONE, -1, deps)
	inst.lb = r.newLeaderBookkeeping(nil, deps, deps, deps, 5, nil, NONE, -1)
	inst.lb.preparing = true
	inst.lb.nacks = 2 // one more nack is a majority of N=5
	r.InstanceSpace[2][0] = inst

	bufs := make(map[int32]*bytes.Buffer)
	for peer := int32(0); peer < int32(r.N); peer++ {
		if peer == r.Id {
			continue
		}
		buf, _ := auditCaptureReply(r, peer)
		bufs[peer] = buf
	}

	r.handlePrepareReply(&PrepareReply{AcceptorId: 1, Replica: 2, Instance: 0,
		Ballot: 6, VBallot: -1, Status: NONE})

	sent := 0
	for peer, buf := range bufs {
		raw := buf.Bytes()
		if len(raw) == 0 {
			continue
		}
		sent++
		if raw[0] != r.prepareRPC {
			t.Fatalf("peer %d: RPC code %d, want Prepare code %d", peer, raw[0], r.prepareRPC)
		}
		prepare := &Prepare{}
		if err := prepare.Unmarshal(bytes.NewReader(raw[1:])); err != nil {
			t.Fatalf("peer %d: %v", peer, err)
		}
		if prepare.Ballot <= 6 {
			t.Errorf("peer %d: retried Prepare.Ballot=%d, want a ballot above the reply ballot 6",
				peer, prepare.Ballot)
		}
	}
	if sent != r.N-1 {
		t.Errorf("sent %d retried Prepares, want %d (one per live peer)", sent, r.N-1)
	}
	if inst.lb.nacks != 3 {
		t.Errorf("nacks=%d, want 3 after the higher-ballot reply", inst.lb.nacks)
	}
}

// The defer-cycle guard is supposed to restart recovery when exactly N/2
// acceptors are no longer possible and the instance was deferred by a replica
// that is still in the possible quorum.  possibleQuorum starts all-true and a
// nack clears the replying and conflicting replicas.
func TestAuditTryPreAcceptBreaksDeferCycle(t *testing.T) {
	r := auditReplica(5, 0, 64)
	r.preAcceptRPC = 99
	deps := auditDeps(5)
	inst := r.newInstance(2, 0, nil, 5, 5, NONE, -1, deps)
	inst.lb = r.newLeaderBookkeeping(nil, deps, deps, deps, 5, nil, NONE, -1)
	inst.lb.tryingToPreAccept = true
	r.InstanceSpace[2][0] = inst

	// Instance (2,0) was deferred by replica 4, which is still possible.
	updateDeferred(4, 9, 2, 0)
	defer delete(deferMap, (uint64(2)<<32)|uint64(0))

	bufs := make(map[int32]*bytes.Buffer)
	for peer := int32(0); peer < int32(r.N); peer++ {
		if peer == r.Id {
			continue
		}
		buf, _ := auditCaptureReply(r, peer)
		bufs[peer] = buf
	}

	// Two nacks (acceptor 0 and conflict replica 3) leave 2 == N/2 possible.
	r.handleTryPreAcceptReply(&TryPreAcceptReply{AcceptorId: 0, Replica: 2,
		Instance: 0, Ballot: 5, VBallot: -1, ConflictReplica: 3,
		ConflictInstance: 1, ConflictStatus: NONE})

	sent := 0
	for peer, buf := range bufs {
		raw := buf.Bytes()
		if len(raw) == 0 {
			continue
		}
		sent++
		if raw[0] != r.preAcceptRPC {
			t.Fatalf("peer %d: RPC code %d, want PreAccept code %d", peer, raw[0], r.preAcceptRPC)
		}
	}
	want := r.Replica.FastQuorumSize() - 1 // Thrifty PreAccept broadcast
	if sent != want {
		t.Errorf("sent %d restarted PreAccepts, want %d; the defer-cycle guard did not fire",
			sent, want)
	}
}

// When recovery abandons to phase 1, the fallback must propose an explicit
// NOOP.  Prepare replies decode a zero-length command list as a non-nil empty
// slice, so a nil check is not enough; len(cmds) > 0 is required.
func TestAuditRecoveryAbandonProposesNoop(t *testing.T) {
	r := auditReplica(5, 0, 64)
	r.preAcceptRPC = 99
	deps := auditDeps(5)
	inst := r.newInstance(2, 0, nil, 10, 10, PREACCEPTED, 0, deps)
	inst.lb = r.newLeaderBookkeeping(nil, deps, deps, deps, 10, nil, NONE, -1)
	inst.lb.preparing = true
	inst.lb.ballot = -1
	r.InstanceSpace[2][0] = inst

	bufs := make(map[int32]*bytes.Buffer)
	for peer := int32(0); peer < int32(r.N); peer++ {
		if peer == r.Id {
			continue
		}
		buf, _ := auditCaptureReply(r, peer)
		bufs[peer] = buf
	}

	// Three empty-status replies reach the slow quorum and select sub-case 6.
	for _, acceptor := range []int32{0, 1, 3} {
		r.handlePrepareReply(&PrepareReply{AcceptorId: acceptor, Replica: 2,
			Instance: 0, Ballot: 10, VBallot: 10, Status: NONE,
			Command: []state.Command{}, Seq: -1, Deps: deps})
	}

	sent := 0
	for peer, buf := range bufs {
		raw := buf.Bytes()
		if len(raw) == 0 {
			continue
		}
		sent++
		if raw[0] != r.preAcceptRPC {
			t.Fatalf("peer %d: RPC code %d, want PreAccept code %d", peer, raw[0], r.preAcceptRPC)
		}
		preAccept := &PreAccept{}
		if err := preAccept.Unmarshal(bytes.NewReader(raw[1:])); err != nil {
			t.Fatalf("peer %d: %v", peer, err)
		}
		if len(preAccept.Command) != 1 || preAccept.Command[0].Op != state.NONE {
			t.Errorf("peer %d: recovery phase 1 proposed %v, want one explicit NOOP",
				peer, preAccept.Command)
		}
	}
	if sent != r.Replica.FastQuorumSize()-1 {
		t.Errorf("sent %d phase-1 PreAccepts, want %d", sent, r.Replica.FastQuorumSize()-1)
	}
}

// startPhase1 computes seq from updateAttributes and stores it on the leader's
// instance, but the PreAccept broadcast reads lb.seq.  The two must match, or
// followers record and later commit a different sequence number.
func TestAuditPreAcceptBroadcastCarriesComputedSeq(t *testing.T) {
	r := auditReplica(5, 0, 64)
	r.preAcceptRPC = 99
	bufs := make(map[int32]*bytes.Buffer)
	for peer := int32(0); peer < int32(r.N); peer++ {
		if peer == r.Id {
			continue
		}
		buf, _ := auditCaptureReply(r, peer)
		bufs[peer] = buf
	}

	cmd := state.Command{Op: state.PUT, K: 1, V: state.Value("x")}
	r.startPhase1([]state.Command{cmd}, 0, 0, 0, nil)
	inst := r.InstanceSpace[0][0]
	if inst == nil {
		t.Fatal("startPhase1 did not create 0.0")
	}

	sent := 0
	for peer, buf := range bufs {
		raw := buf.Bytes()
		if len(raw) == 0 {
			continue
		}
		sent++
		if raw[0] != r.preAcceptRPC {
			t.Fatalf("peer %d: RPC code %d, want PreAccept code %d", peer, raw[0], r.preAcceptRPC)
		}
		preAccept := &PreAccept{}
		if err := preAccept.Unmarshal(bytes.NewReader(raw[1:])); err != nil {
			t.Fatalf("peer %d: %v", peer, err)
		}
		if preAccept.Seq != inst.Seq {
			t.Errorf("peer %d: PreAccept.Seq=%d, leader instance Seq=%d",
				peer, preAccept.Seq, inst.Seq)
		}
	}
	if sent != r.Replica.FastQuorumSize()-1 {
		t.Errorf("sent %d PreAccepts, want %d", sent, r.Replica.FastQuorumSize()-1)
	}
}

// Sub-case 4 is documented as "pre-accepted >= f/2, allEqual, leader did not
// reply" and is supposed to start TryPreAccept.  Its condition is identical to
// sub-case 3's, so with one pre-accepted reply (f/2 for N=5) the handler falls
// through to sub-case 5 and restarts phase 1 instead.
func TestAuditPrepareReplyPreacceptedMinorityUsesTryPreAccept(t *testing.T) {
	r := auditReplica(5, 0, 64)
	r.preAcceptRPC = 99
	r.tryPreAcceptRPC = 98
	deps := auditDeps(5)
	cmd := []state.Command{{Op: state.PUT, K: 5, V: state.Value("v")}}
	inst := r.newInstance(2, 0, nil, 10, 10, NONE, -1, deps)
	inst.lb = r.newLeaderBookkeeping(nil, deps, deps, deps, 10, nil, NONE, -1)
	inst.lb.preparing = true
	inst.lb.ballot = -1
	r.InstanceSpace[2][0] = inst

	bufs := make(map[int32]*bytes.Buffer)
	for peer := int32(0); peer < int32(r.N); peer++ {
		if peer == r.Id {
			continue
		}
		buf, _ := auditCaptureReply(r, peer)
		bufs[peer] = buf
	}

	// One pre-accepted value and two empty replies form the slow quorum.
	r.handlePrepareReply(&PrepareReply{AcceptorId: 1, Replica: 2, Instance: 0,
		Ballot: 10, VBallot: 0, Status: PREACCEPTED, Command: cmd, Seq: 0, Deps: deps})
	r.handlePrepareReply(&PrepareReply{AcceptorId: 3, Replica: 2, Instance: 0,
		Ballot: 10, VBallot: -1, Status: NONE, Seq: -1, Deps: deps})
	r.handlePrepareReply(&PrepareReply{AcceptorId: 4, Replica: 2, Instance: 0,
		Ballot: 10, VBallot: -1, Status: NONE, Seq: -1, Deps: deps})

	sentTry := 0
	for peer, buf := range bufs {
		raw := buf.Bytes()
		if len(raw) == 0 {
			continue
		}
		if raw[0] == r.tryPreAcceptRPC {
			sentTry++
			continue
		}
		t.Errorf("peer %d: got RPC code %d, want TryPreAccept code %d (phase 1 restarted instead)",
			peer, raw[0], r.tryPreAcceptRPC)
	}
	if sentTry == 0 {
		t.Errorf("no TryPreAccept was sent; recovery used sub-case 5 instead of sub-case 4")
	}
}

// Sub-case 1 learns that a value is committed.  Other replicas may still hold
// PREACCEPTED or NONE; the recoverer should propagate a Commit, otherwise they
// remain stuck until an unrelated recovery/timeout.
func TestAuditPrepareReplySubcase1PropagatesCommit(t *testing.T) {
	r := auditReplica(5, 0, 64)
	deps := auditDeps(5)
	cmd := state.Command{Op: state.PUT, K: 88, V: state.Value("known-committed")}
	inst := r.newInstance(2, 0, nil, 10, 10, NONE, -1, deps)
	inst.lb = r.newLeaderBookkeeping(nil, deps, deps, deps, 10, nil, NONE, -1)
	inst.lb.preparing = true
	inst.lb.ballot = -1
	inst.lb.prepareReplies = append(inst.lb.prepareReplies, &PrepareReply{
		AcceptorId: 0, Replica: 2, Instance: 0, Ballot: 10, VBallot: -1, Status: NONE})
	r.InstanceSpace[2][0] = inst
	bufs := make([]*bytes.Buffer, r.N)
	for i := 0; i < r.N; i++ {
		bufs[i], _ = auditCaptureReply(r, int32(i))
	}

	// PREACCEPTED first, COMMITTED last: the equal-VBallot loop keeps the
	// COMMITTED status, so sub-case 1 is selected.
	r.handlePrepareReply(&PrepareReply{AcceptorId: 1, Replica: 2, Instance: 0,
		Ballot: 10, VBallot: 0, Status: PREACCEPTED_EQ,
		Command: []state.Command{cmd}, Seq: 0, Deps: deps})
	r.handlePrepareReply(&PrepareReply{AcceptorId: 2, Replica: 2, Instance: 0,
		Ballot: 10, VBallot: 0, Status: COMMITTED,
		Command: []state.Command{cmd}, Seq: 0, Deps: deps})
	if inst.Status != COMMITTED || len(inst.Cmds) == 0 {
		t.Fatalf("sub-case 1 did not install the committed value: %+v", inst)
	}
	sent := 0
	for i := 0; i < r.N; i++ {
		if bufs[i].Len() > 0 {
			sent++
		}
	}
	t.Logf("sub-case 1 installed key=%d; messages sent to %d peers", inst.Cmds[0].K, sent)
	if sent == 0 {
		t.Errorf("sub-case 1 did not broadcast a Commit; PREACCEPTED/NONE replicas remain stuck")
	}
}

// With N=7 and f=3 crashes there are only 4 live replicas.  A fast quorum
// (size 5) is impossible, but a slow majority (size 4) is available.  The
// accept phase must start after a majority of preaccept replies.
func TestAuditSlowPathStartsWithMajority(t *testing.T) {
	r := auditReplica(7, 0, 64)
	deps := auditDeps(7)
	cdeps := auditDeps(7)
	cmds := []state.Command{{Op: state.PUT, K: 1, V: state.Value("x")}}
	inst := r.newInstance(0, 0, cmds, 0, 0, PREACCEPTED, 0, deps)
	inst.lb = r.newLeaderBookkeeping(nil, deps, cdeps, deps, 0, cmds, PREACCEPTED, 0)
	r.InstanceSpace[0][0] = inst

	for i := 0; i < 3; i++ {
		r.handlePreAcceptReply(&PreAcceptReply{Replica: 0, Instance: 0, Ballot: 0,
			VBallot: 0, Seq: 0, Deps: deps, CommittedDeps: cdeps, Status: PREACCEPTED_EQ})
	}
	t.Logf("N=7 after self+3 replies (majority=4): preAcceptOKs=%d lb.status=%d inst.status=%d",
		inst.lb.preAcceptOKs, inst.lb.status, inst.Status)
	if inst.lb.status != ACCEPTED {
		t.Errorf("accept phase did not start after a slow-quorum majority; status=%d", inst.lb.status)
	}
}

// When the leader adopts a value that was already ACCEPTED at a higher value
// ballot, its own instance must record that value ballot too.  The fast commit
// path sets inst.bal = lb.ballot but leaves inst.vbal at the original ballot.
func TestAuditFastCommitRecordsValueBallot(t *testing.T) {
	r := auditReplica(5, 0, 64)
	deps := auditDeps(5)
	cmds := []state.Command{{Op: state.PUT, K: 1, V: state.Value("x")}}
	inst := r.newInstance(0, 0, cmds, 0, 0, PREACCEPTED, 0, deps)
	inst.lb = r.newLeaderBookkeeping(nil, deps, deps, deps, 0, cmds, PREACCEPTED, 0)
	r.InstanceSpace[0][0] = inst

	for i := 0; i < 2; i++ {
		r.handlePreAcceptReply(&PreAcceptReply{Replica: 0, Instance: 0, Ballot: 0,
			VBallot: 5, Seq: 0, Deps: deps, CommittedDeps: deps, Status: PREACCEPTED_EQ})
	}
	t.Logf("after adopting a preaccepted value at vbal=5: status=%d bal=%d vbal=%d",
		inst.Status, inst.bal, inst.vbal)
	if inst.vbal != 5 {
		t.Errorf("inst.vbal=%d, want 5 (the adopted value's VBallot)", inst.vbal)
	}
}

// A reply with a higher VBallot that carries ACCEPTED status sets lb.status to
// ACCEPTED.  The early status guard then rejects every later PreAccept reply,
// so the leader can never count a quorum or start Accept.
func TestAuditHigherVBallotReplyDoesNotBlockFurtherReplies(t *testing.T) {
	r := auditReplica(5, 0, 64)
	deps := auditDeps(5)
	cmds := []state.Command{{Op: state.PUT, K: 1, V: state.Value("x")}}
	inst := r.newInstance(0, 0, cmds, 0, 0, PREACCEPTED, 0, deps)
	inst.lb = r.newLeaderBookkeeping(nil, deps, deps, deps, 0, cmds, PREACCEPTED, 0)
	r.InstanceSpace[0][0] = inst

	reply := &PreAcceptReply{Replica: 0, Instance: 0, Ballot: 0, VBallot: 5,
		Seq: 0, Deps: deps, CommittedDeps: deps, Status: ACCEPTED}
	r.handlePreAcceptReply(reply)
	t.Logf("after first reply: preAcceptOKs=%d lb.status=%d", inst.lb.preAcceptOKs, inst.lb.status)
	r.handlePreAcceptReply(reply)
	t.Logf("after second reply: preAcceptOKs=%d lb.status=%d inst.status=%d",
		inst.lb.preAcceptOKs, inst.lb.status, inst.Status)
	if inst.lb.preAcceptOKs != 2 && inst.Status == PREACCEPTED {
		t.Errorf("no progress: second reply was ignored and neither Accept nor Commit started (preAcceptOKs=%d inst.status=%d)",
			inst.lb.preAcceptOKs, inst.Status)
	}
}

// The SCC tie-breaker for same-seq/same-replica instances uses proposeTime,
// which is stamped locally and is not carried by any RPC.  Two replicas with
// the same logical committed instances can therefore execute them in opposite
// orders and end with different state.
func TestInvestigationExecOrderUsesReplicatedIdentity(t *testing.T) {
	makeReplica := func(firstTime, secondTime int64) *Replica {
		r := auditReplica(5, 0, 64)
		first := r.newInstance(0, 0, []state.Command{{Op: state.PUT, K: 1, V: state.Value("a")}},
			0, 0, COMMITTED, 0, []int32{1, -1, -1, -1, -1})
		second := r.newInstance(0, 1, []state.Command{{Op: state.PUT, K: 1, V: state.Value("b")}},
			0, 0, COMMITTED, 0, []int32{0, -1, -1, -1, -1})
		first.proposeTime = firstTime
		second.proposeTime = secondTime
		r.InstanceSpace[0][0] = first
		r.InstanceSpace[0][1] = second
		r.crtInstance[0] = 1
		return r
	}
	a := makeReplica(100, 200)
	b := makeReplica(200, 100)
	if !a.exec.executeCommand(0, 0) {
		t.Fatal("replica A could not execute 0.0")
	}
	if !b.exec.executeCommand(0, 0) {
		t.Fatal("replica B could not execute 0.0")
	}
	av, _ := a.State.Store.Get(state.Key(1))
	bv, _ := b.State.Store.Get(state.Key(1))
	t.Logf("same instances, different local proposeTime: A final=%v B final=%v", av, bv)
	if string(av.(state.Value)) != string(bv.(state.Value)) {
		t.Errorf("replicas executed the same SCC in different orders: A=%q B=%q",
			string(av.(state.Value)), string(bv.(state.Value)))
	}
}
