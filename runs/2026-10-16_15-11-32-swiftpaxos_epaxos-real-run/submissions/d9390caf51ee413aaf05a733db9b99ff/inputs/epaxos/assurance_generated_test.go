package epaxos

// Probe harness for the EPaxos recovery value-adoption question.
//
// Replicas are built in-process with the package's own field/RPC initialization,
// without peer sockets or the run() loop, so that every handler invocation is
// deterministic. Inter-replica messages are the package's own marshaled RPC
// structs: each bcast goes through SendMsg into a captured byte buffer and every
// delivery decodes a fresh object from those bytes, i.e. the serialization
// boundary of the real transport is preserved. Message delivery order is FIFO
// per link; messages addressed to a replica marked crashed are dropped.

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"net"
	"sync"
	"testing"

	"github.com/imdea-software/swiftpaxos/config"
	"github.com/imdea-software/swiftpaxos/dlog"
	"github.com/imdea-software/swiftpaxos/replica"
	"github.com/imdea-software/swiftpaxos/replica/defs"
	fastrpc "github.com/imdea-software/swiftpaxos/rpc"
	"github.com/imdea-software/swiftpaxos/state"
)

// probeRowLen bounds InstanceSpace rows. The deployed constant is MAX_INSTANCE
// (10M pointers per row); the probe only uses instances 0..2.
const probeRowLen = 32

type probeNode struct {
	id   int32
	r    *Replica
	bufs []*bytes.Buffer
	dead bool
}

type probe struct {
	nodes []*probeNode
}

type wireMsg struct {
	from int32
	to   int32
	obj  fastrpc.Serializable
}

func newProbeNode(id int32, n int) *probeNode {
	base := &replica.Replica{
		Logger: dlog.New("", false),

		N:     n,
		F:     (n - 1) / 2,
		Id:    id,
		Alias: fmt.Sprintf("probe%d", id),

		PeerAddrList:       make([]string, n),
		Peers:              make([]net.Conn, n),
		PeerReaders:        make([]*bufio.Reader, n),
		PeerWriters:        make([]*bufio.Writer, n),
		ClientWriters:      make(map[int32]*bufio.Writer),
		Config:             &config.Config{},
		Alive:              make([]bool, n),
		PreferredPeerOrder: make([]int32, n),

		State:       state.InitState(),
		RPC:         fastrpc.NewTableId(defs.RPC_TABLE),
		StableStore: nil,
		Stats:       &defs.Stats{M: make(map[string]int)},
		Shutdown:    false,
		Listener:    nil,
		ProposeChan: make(chan *defs.GPropose, 1024),
		BeaconChan:  make(chan *defs.GBeacon, 1024),

		Thrifty: true,
		Exec:    false,
		LRead:   false,
		Dreply:  true,
		Beacon:  false,
		Durable: false,

		Ewma:      make([]float64, n),
		Latencies: make([]int64, n),
		Dt:        nil,
	}

	r := &Replica{Replica: base}
	r.InstanceSpace = make([][]*Instance, n)
	r.crtInstance = make([]int32, n)
	r.CommittedUpTo = make([]int32, n)
	r.ExecedUpTo = make([]int32, n)
	r.conflicts = make([]map[state.Key]*InstPair, n)
	r.maxSeqPerKey = make(map[state.Key]int32)
	r.clientMutex = new(sync.Mutex)
	r.maxRecvBallot = -1
	r.exec = &Exec{r}

	for i := 0; i < n; i++ {
		r.InstanceSpace[i] = make([]*Instance, probeRowLen)
		r.crtInstance[i] = -1
		r.CommittedUpTo[i] = -1
		r.ExecedUpTo[i] = -1
		r.conflicts[i] = make(map[state.Key]*InstPair)
		base.PreferredPeerOrder[i] = int32((int(id) + 1 + i) % n)
		r.Ewma[i] = 0.0
		r.Latencies[i] = 0
	}

	r.prepareRPC = base.RPC.Register(new(Prepare), nil)
	r.prepareReplyRPC = base.RPC.Register(new(PrepareReply), nil)
	r.preAcceptRPC = base.RPC.Register(new(PreAccept), nil)
	r.preAcceptReplyRPC = base.RPC.Register(new(PreAcceptReply), nil)
	r.acceptRPC = base.RPC.Register(new(Accept), nil)
	r.acceptReplyRPC = base.RPC.Register(new(AcceptReply), nil)
	r.commitRPC = base.RPC.Register(new(Commit), nil)
	r.tryPreAcceptRPC = base.RPC.Register(new(TryPreAccept), nil)
	r.tryPreAcceptReplyRPC = base.RPC.Register(new(TryPreAcceptReply), nil)

	bufs := make([]*bytes.Buffer, n)
	for q := 0; q < n; q++ {
		b := new(bytes.Buffer)
		bufs[q] = b
		base.PeerWriters[q] = bufio.NewWriter(b)
		if int32(q) != id {
			base.Alive[q] = true
		}
	}

	return &probeNode{id: id, r: r, bufs: bufs}
}

func newProbe(n int) *probe {
	p := &probe{}
	for i := 0; i < n; i++ {
		p.nodes = append(p.nodes, newProbeNode(int32(i), n))
	}
	return p
}

func (p *probe) node(id int32) *probeNode { return p.nodes[id] }

// drain decodes every message the node has emitted since the last drain.
func (n *probeNode) drain() []wireMsg {
	var msgs []wireMsg
	for q := int32(0); q < int32(n.r.N); q++ {
		b := n.bufs[q]
		if b == nil || b.Len() == 0 {
			continue
		}
		rd := bytes.NewReader(b.Bytes())
		for rd.Len() > 0 {
			code, err := rd.ReadByte()
			if err != nil {
				break
			}
			pair, ok := n.r.RPC.Get(code)
			if !ok {
				panic(fmt.Sprintf("probe: unknown RPC code %d", code))
			}
			obj := pair.Obj.New()
			if err := obj.Unmarshal(rd); err != nil {
				panic(fmt.Sprintf("probe: decode error: %v", err))
			}
			msgs = append(msgs, wireMsg{from: n.id, to: q, obj: obj})
		}
		b.Reset()
	}
	return msgs
}

// deliver hands one message to the addressed replica's own handler, unless the
// target is marked crashed.
func (p *probe) deliver(m wireMsg) bool {
	n := p.node(m.to)
	if n == nil || n.dead {
		return false
	}
	r := n.r
	switch t := m.obj.(type) {
	case *Prepare:
		r.handlePrepare(t)
	case *PrepareReply:
		r.handlePrepareReply(t)
	case *PreAccept:
		r.handlePreAccept(t)
	case *PreAcceptReply:
		r.handlePreAcceptReply(t)
	case *Accept:
		r.handleAccept(t)
	case *AcceptReply:
		r.handleAcceptReply(t)
	case *Commit:
		r.handleCommit(t)
	case *TryPreAccept:
		r.handleTryPreAccept(t)
	case *TryPreAcceptReply:
		r.handleTryPreAcceptReply(t)
	default:
		panic(fmt.Sprintf("probe: unroutable message %T", m.obj))
	}
	return true
}

// crash marks a replica failed at every other replica and discards whatever it
// still had queued.
func (p *probe) crash(id int32) {
	p.node(id).dead = true
	for _, n := range p.nodes {
		n.r.Alive[id] = false
	}
	p.node(id).drain()
}

// pump delivers queued messages until quiescence.
func (p *probe) pump(maxRounds int) int {
	rounds := 0
	for rounds < maxRounds {
		var msgs []wireMsg
		for _, n := range p.nodes {
			if n.dead {
				continue
			}
			msgs = append(msgs, n.drain()...)
		}
		if len(msgs) == 0 {
			return rounds
		}
		for _, m := range msgs {
			p.deliver(m)
		}
		rounds++
	}
	return rounds
}

func emit(event string, fields map[string]any) {
	fields["event"] = event
	b, err := json.Marshal(fields)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func cmdOp(cmds []state.Command) any {
	if len(cmds) == 0 {
		return nil
	}
	return int(cmds[0].Op)
}

func cmdKey(cmds []state.Command) any {
	if len(cmds) == 0 {
		return nil
	}
	return int64(cmds[0].K)
}

func (n *probeNode) state(phase string, row, idx int32) {
	inst := n.r.InstanceSpace[row][idx]
	if inst == nil {
		emit("instance_state", map[string]any{
			"replica": int(n.id), "instance_row": int(row), "instance_index": int(idx),
			"phase": phase, "present": false,
		})
		return
	}
	emit("instance_state", map[string]any{
		"replica": int(n.id), "instance_row": int(row), "instance_index": int(idx),
		"phase": phase, "present": true, "status": int(inst.Status),
		"bal": int(inst.bal), "vbal": int(inst.vbal), "seq": int(inst.Seq),
		"has_cmds": inst.Cmds != nil, "cmd_op": cmdOp(inst.Cmds), "cmd_key": cmdKey(inst.Cmds),
	})
}

func put(key int64, val string) state.Command {
	return state.Command{Op: state.PUT, K: state.Key(key), V: state.Value([]byte(val))}
}

// TestAssuranceEPaxosRecoveryValueAdoption drives a 5-replica configuration
// (F=2) through a phase-2 acceptance of command X on instance (0,0), a crash of
// the leader before any reply is consumed, and a recovery of that instance by
// replica 3, which received only the Accept message and therefore holds the
// instance (crtInstance[0] == 0) without its command.
func TestAssuranceEPaxosRecoveryValueAdoption(t *testing.T) {
	recoveryValueAdoptionScenario(t, 3)
}

// TestAssuranceEPaxosRecoveryValueAdoptionHolderControl runs the same scenario
// with the recovery driven by replica 2, which holds the accepted command, so
// that the value-loss mechanism can be separated from the crash pattern itself.
func TestAssuranceEPaxosRecoveryValueAdoptionHolderControl(t *testing.T) {
	recoveryValueAdoptionScenario(t, 2)
}

func recoveryValueAdoptionScenario(t *testing.T, recoverer int32) {
	const n = 5
	p := newProbe(n)

	// Premise: replica 1 already pre-accepted a conflicting command of its own
	// (key 1) on instance (2,0). Its auxiliary broadcast is discarded so the
	// scenario keeps only the caused local conflict state.
	b := p.node(1)
	b.r.startPhase1([]state.Command{put(1, "y")}, 2, 0, 2, nil)
	b.drain()
	emit("premise_conflicting_command", map[string]any{
		"replica": 1, "instance_row": 2, "instance_index": 0, "cmd_op": int(state.PUT), "cmd_key": 1,
	})

	// Leader (replica 0) proposes X on its own instance (0,0).
	a := p.node(0)
	a.r.startPhase1([]state.Command{put(1, "x")}, 0, 0, 0, nil)
	a.state("proposed", 0, 0)

	preAccepts := a.drain()
	recipients := []int{}
	for _, m := range preAccepts {
		if _, ok := m.obj.(*PreAccept); !ok {
			continue
		}
		recipients = append(recipients, int(m.to))
		p.deliver(m)
	}
	emit("preaccept_sent", map[string]any{"from": 0, "instance_row": 0, "instance_index": 0, "to": recipients})

	// Replica 1's reply is non-equal (it saw the conflicting command); deliver it
	// first, then crash replica 1, then deliver replica 2's equal reply, so the
	// leader's Accept broadcast runs with replica 1 already failed.
	repliesB := b.drain()
	for _, m := range repliesB {
		if _, ok := m.obj.(*PreAcceptReply); !ok {
			continue
		}
		if rp, ok := m.obj.(*PreAcceptReply); ok {
			emit("preaccept_reply", map[string]any{
				"acceptor": int(m.from), "instance_row": int(rp.Replica), "instance_index": int(rp.Instance),
				"ballot": int(rp.Ballot), "vballot": int(rp.VBallot), "status": int(rp.Status),
				"has_cmds": rp.Status == PREACCEPTED,
			})
		}
		p.deliver(m)
	}

	repliesC := p.node(2).drain()
	p.crash(1)
	for _, m := range repliesC {
		if rp, ok := m.obj.(*PreAcceptReply); ok {
			emit("preaccept_reply", map[string]any{
				"acceptor": int(m.from), "instance_row": int(rp.Replica), "instance_index": int(rp.Instance),
				"ballot": int(rp.Ballot), "vballot": int(rp.VBallot), "status": int(rp.Status),
				"has_cmds": rp.Status == PREACCEPTED,
			})
		}
		p.deliver(m)
	}
	a.state("after_preaccept_replies", 0, 0)

	accepts := a.drain()
	recipients = recipients[:0]
	for _, m := range accepts {
		if _, ok := m.obj.(*Accept); !ok {
			continue
		}
		recipients = append(recipients, int(m.to))
		p.deliver(m)
	}
	emit("accept_sent", map[string]any{"from": 0, "instance_row": 0, "instance_index": 0, "to": recipients})

	for _, id := range recipients {
		p.node(int32(id)).state("after_accept", 0, 0)
	}

	// The leader fails after broadcasting Accept and before consuming any
	// AcceptReply: no replica has committed X.
	p.node(0).state("before_crash", 0, 0)
	p.crash(0)

	// Recovery of instance (0,0) by replica 3, which holds only the accepted
	// coordinates (no command) for it.
	d := p.node(recoverer)
	d.state("before_recovery", 0, 0)
	d.r.startRecoveryForInstance(0, 0)
	selfReply := d.r.InstanceSpace[0][0].lb.prepareReplies[0]
	emit("recovery_start", map[string]any{
		"replica": int(recoverer), "instance_row": 0, "instance_index": 0,
		"tried_ballot": int(selfReply.Ballot), "self_vballot": int(selfReply.VBallot),
		"self_status": int(selfReply.Status), "self_has_command": selfReply.Command != nil,
		"self_is_owner": false, "is_leader": d.r.IsLeader,
	})

	prepares := d.drain()
	preparesOut := []int{}
	for _, m := range prepares {
		if _, ok := m.obj.(*Prepare); !ok {
			continue
		}
		if pr, ok := m.obj.(*Prepare); ok {
			preparesOut = append(preparesOut, int(m.to))
			emit("prepare_sent", map[string]any{
				"from": int(recoverer), "to": int(m.to), "instance_row": int(pr.Replica), "instance_index": int(pr.Instance),
				"ballot": int(pr.Ballot),
			})
			p.deliver(m)
		}
	}

	maxReplyVBallot := -2
	carriedCmdOp := -1
	for _, m := range preparesOut {
		peer := p.node(int32(m))
		for _, out := range peer.drain() {
			rp, ok := out.obj.(*PrepareReply)
			if !ok {
				continue
			}
			if int(rp.VBallot) > maxReplyVBallot {
				maxReplyVBallot = int(rp.VBallot)
			}
			hasCmd := rp.Command != nil && len(rp.Command) > 0
			op := -1
			if hasCmd {
				op = int(rp.Command[0].Op)
				if op > 0 {
					carriedCmdOp = op
				}
			}
			emit("prepare_reply", map[string]any{
				"from": int(out.from), "replica": int(out.from),
				"instance_row": int(rp.Replica), "instance_index": int(rp.Instance),
				"ballot": int(rp.Ballot), "vballot": int(rp.VBallot), "status": int(rp.Status),
				"has_command": hasCmd, "cmd_op": op,
			})
			p.deliver(out)
		}
	}
	emit("adoption_inputs", map[string]any{
		"replica": int(recoverer), "instance_row": 0, "instance_index": 0,
		"self_vballot": int(selfReply.VBallot),
		"max_remote_vballot_with_command": maxReplyVBallot,
		"self_ballot_above_remote_value_ballots": int(selfReply.VBallot) > maxReplyVBallot,
		"quorum_reply_command_op": carriedCmdOp,
	})

	proposals := d.drain()
	proposalRecipients := []int{}
	proposedOp := -1
	proposedKey := int64(-1)
	proposedLen := 0
	proposedBallot := -1
	for _, m := range proposals {
		pa, ok := m.obj.(*PreAccept)
		if !ok {
			continue
		}
		proposalRecipients = append(proposalRecipients, int(m.to))
		proposedBallot = int(pa.Ballot)
		proposedLen = len(pa.Command)
		if op, ok := cmdOp(pa.Command).(int); ok {
			proposedOp = op
		}
		if k, ok := cmdKey(pa.Command).(int64); ok {
			proposedKey = k
		}
		p.deliver(m)
	}
	emit("recovery_proposal", map[string]any{
		"replica": int(recoverer), "instance_row": 0, "instance_index": 0,
		"to": proposalRecipients, "ballot": proposedBallot, "cmd_len": proposedLen,
		"cmd_op": proposedOp, "cmd_key": proposedKey,
		"quorum_reply_command_op": carriedCmdOp,
	})
	d.state("after_recovery_proposal", 0, 0)

	// Let the recovered NOOP run its own pre-accept/accept/commit cycle.
	p.pump(20)

	d.state("final", 0, 0)
	p.node(2).state("final", 0, 0)
	p.node(4).state("final", 0, 0)
	p.node(1).state("final", 0, 0)
	p.node(0).state("final", 0, 0)
}

// TestAssuranceEPaxosRecoveryBallotProgress exercises the recovery authority
// path: the instance owner recovers its own instance after a higher-ballot
// Prepare touched the accepting peers, without and then with the target's own
// BeTheLeader authority.
func TestAssuranceEPaxosRecoveryBallotProgress(t *testing.T) {
	const n = 5
	p := newProbe(n)

	// Premise: replica 1 holds a conflicting command, so the owner's pre-accept
	// reply set is not equal and the owner must run an Accept phase.
	b := p.node(1)
	b.r.startPhase1([]state.Command{put(1, "y")}, 2, 0, 2, nil)
	b.drain()

	// Owner 0 proposes X on its own instance (0,0) at ballot 0.
	owner := p.node(0)
	owner.r.startPhase1([]state.Command{put(1, "x")}, 0, 0, 0, nil)
	for _, m := range owner.drain() {
		if _, ok := m.obj.(*PreAccept); ok {
			p.deliver(m)
		}
	}
	reply1 := p.node(1).drain()
	reply2 := p.node(2).drain()
	for _, m := range reply1 {
		if rp, ok := m.obj.(*PreAcceptReply); ok {
			emit("preaccept_reply", map[string]any{
				"acceptor": int(m.from), "instance_row": int(rp.Replica), "instance_index": int(rp.Instance),
				"status": int(rp.Status), "vballot": int(rp.VBallot)})
		}
		p.deliver(m)
	}
	for _, m := range reply2 {
		if rp, ok := m.obj.(*PreAcceptReply); ok {
			emit("preaccept_reply", map[string]any{
				"acceptor": int(m.from), "instance_row": int(rp.Replica), "instance_index": int(rp.Instance),
				"status": int(rp.Status), "vballot": int(rp.VBallot)})
		}
		p.deliver(m)
	}
	owner.state("after_preaccept_replies", 0, 0)

	// Owner's Accept phase at ballot 0 reaches replicas 1 and 2; its replies are
	// still in flight when the recovery below runs.
	accepted := []int{}
	for _, m := range owner.drain() {
		if _, ok := m.obj.(*Accept); ok {
			accepted = append(accepted, int(m.to))
			p.deliver(m)
		}
	}
	emit("owner_accept_sent", map[string]any{"from": 0, "instance_row": 0, "instance_index": 0, "to": accepted, "ballot": 0})
	for _, id := range accepted {
		p.node(int32(id)).state("after_owner_accept", 0, 0)
	}
	for _, id := range accepted {
		p.node(int32(id)).drain() // AcceptReply stays in flight
	}

	// Replica 2 recovers the same instance at its own ballot 7; the accepting
	// peers join that ballot. Replica 2 fails after broadcasting its Prepare.
	rec := p.node(2)
	rec.r.startRecoveryForInstance(0, 0)
	highPrepares := []int{}
	for _, m := range rec.drain() {
		if pr, ok := m.obj.(*Prepare); ok {
			highPrepares = append(highPrepares, int(m.to))
			emit("prepare_sent", map[string]any{
				"from": 2, "to": int(m.to), "instance_row": int(pr.Replica), "instance_index": int(pr.Instance), "ballot": int(pr.Ballot)})
			p.deliver(m)
		}
	}
	emit("high_ballot_recovery", map[string]any{
		"replica": 2, "instance_row": 0, "instance_index": 0, "tried_ballot": 7, "to": highPrepares})
	for _, id := range highPrepares {
		p.node(int32(id)).state("after_high_ballot_prepare", 0, 0)
		p.node(int32(id)).drain()
	}
	p.crash(2)
	owner.state("before_owner_recovery", 0, 0)

	attempt := func(round int, mode string) {
		storedBal := int32(-2)
		for q := 0; q < n; q++ {
			if int32(q) == owner.r.Id || p.node(int32(q)).dead {
				continue
			}
			st := p.node(int32(q)).r.InstanceSpace[0][0]
			if st != nil && st.bal > storedBal {
				storedBal = st.bal
			}
		}
		emit("round_start", map[string]any{
			"replica": 0, "instance_row": 0, "instance_index": 0, "round": round, "mode": mode,
			"is_leader": owner.r.IsLeader, "max_recv_ballot": int(owner.r.maxRecvBallot)})
		owner.r.startRecoveryForInstance(0, 0)
		prepareBallots := []int{}
		recipients := []int{}
		for _, m := range owner.drain() {
			if pr, ok := m.obj.(*Prepare); ok {
				prepareBallots = append(prepareBallots, int(pr.Ballot))
				recipients = append(recipients, int(m.to))
				p.deliver(m)
			}
		}
		peerBals := []int{}
		for _, id := range recipients {
			peer := p.node(int32(id))
			for _, out := range peer.drain() {
				if rp, ok := out.obj.(*PrepareReply); ok {
					peerBals = append(peerBals, int(rp.Ballot))
					emit("prepare_reply", map[string]any{
						"from": int(out.from), "replica": int(out.from), "instance_row": int(rp.Replica),
						"instance_index": int(rp.Instance), "ballot": int(rp.Ballot), "vballot": int(rp.VBallot),
						"status": int(rp.Status), "round": round})
					p.deliver(out)
				}
			}
		}
		followUp := []string{}
		dispatched := ""
		for _, m := range owner.drain() {
			switch t2 := m.obj.(type) {
			case *PreAccept:
				followUp = append(followUp, "preaccept")
				emit("recovery_proposal", map[string]any{
					"replica": 0, "instance_row": 0, "instance_index": 0, "round": round,
					"to": []int{int(m.to)}, "ballot": int(t2.Ballot), "cmd_op": cmdOp(t2.Command), "cmd_key": cmdKey(t2.Command)})
			case *Accept:
				followUp = append(followUp, "accept")
				dispatched = "accept"
			case *Commit:
				followUp = append(followUp, "commit")
				dispatched = "commit"
			}
			p.deliver(m)
		}
		inst := owner.r.InstanceSpace[0][0]
		appended := 0
		if inst.lb != nil {
			appended = len(inst.lb.prepareReplies)
		}
		maxPeerBal := -2
		for _, b := range peerBals {
			if b > maxPeerBal {
				maxPeerBal = b
			}
		}
		tried := -1
		if len(prepareBallots) > 0 {
			tried = prepareBallots[0]
		}
		emit("recovery_attempt", map[string]any{
			"replica": 0, "instance_row": 0, "instance_index": 0, "round": round,
			"is_leader": owner.r.IsLeader, "tried_ballot": tried,
			"prepare_ballots": prepareBallots, "peer_reply_ballots": peerBals,
			"max_peer_bal": maxPeerBal, "stored_bal_before_attempt": int(storedBal),
			"prepare_ballot_above_stored_bal": tried > int(storedBal),
			"appended_replies": appended, "slow_quorum": owner.r.Replica.SlowQuorumSize(),
			"subcase_dispatched": appended >= owner.r.Replica.SlowQuorumSize(),
			"follow_up": followUp, "dispatch": dispatched,
			"instance_status": int(inst.Status)})
	}

	attempt(1, "non_leader")
	attempt(2, "non_leader")

	// The target's own authority transition: the master calls BeTheLeader.
	owner.r.BeTheLeader(&defs.BeTheLeaderArgs{}, &defs.BeTheLeaderReply{})
	emit("authority_granted", map[string]any{"replica": 0, "is_leader": owner.r.IsLeader})
	attempt(3, "leader")

	p.pump(10)
	owner.state("final", 0, 0)
	p.node(1).state("final", 0, 0)
	p.node(3).state("final", 0, 0)
	p.node(4).state("final", 0, 0)
}

// TestAssuranceEPaxosRecoveryContradictsCommittedValue drives the same family of
// events as the value-adoption scenario, but lets the owner commit X before it
// fails, delivers that Commit to one live peer only, and then recovers the
// instance at a replica that holds no command.
func TestAssuranceEPaxosRecoveryContradictsCommittedValue(t *testing.T) {
	const n = 5
	p := newProbe(n)

	b := p.node(1)
	b.r.startPhase1([]state.Command{put(1, "y")}, 2, 0, 2, nil)
	b.drain()

	owner := p.node(0)
	owner.r.startPhase1([]state.Command{put(1, "x")}, 0, 0, 0, nil)
	for _, m := range owner.drain() {
		if _, ok := m.obj.(*PreAccept); ok {
			p.deliver(m)
		}
	}
	emitReply := func(peer int32) {
		for _, m := range p.node(peer).drain() {
			if rp, ok := m.obj.(*PreAcceptReply); ok {
				emit("preaccept_reply", map[string]any{
					"acceptor": int(m.from), "instance_row": int(rp.Replica), "instance_index": int(rp.Instance),
					"status": int(rp.Status), "vballot": int(rp.VBallot)})
			}
			p.deliver(m)
		}
	}
	// Replica 1's non-equal reply arrives first and replica 1 then fails, so the
	// owner's Accept phase - triggered by replica 2's reply - reaches replicas 2
	// and 3, one of which never pre-accepted the command.
	emitReply(1)
	p.crash(1)
	emitReply(2)
	owner.state("after_preaccept_replies", 0, 0)

	acceptRecipients := []int{}
	for _, m := range owner.drain() {
		if _, ok := m.obj.(*Accept); ok {
			acceptRecipients = append(acceptRecipients, int(m.to))
			p.deliver(m)
		}
	}
	emit("owner_accept_sent", map[string]any{
		"from": 0, "instance_row": 0, "instance_index": 0, "to": acceptRecipients, "ballot": 0})
	for _, id := range acceptRecipients {
		p.node(int32(id)).state("after_accept", 0, 0)
	}

	// The accept replies from both acceptors reach the owner, which commits X and
	// broadcasts Commit.
	for _, id := range acceptRecipients {
		for _, m := range p.node(int32(id)).drain() {
			p.deliver(m)
		}
	}
	owner.state("after_commit", 0, 0)

	delivered := []int{}
	for _, m := range owner.drain() {
		if ec, ok := m.obj.(*Commit); ok {
			emit("owner_commit_sent", map[string]any{
				"from": 0, "to": int(m.to), "instance_row": int(ec.Replica), "instance_index": int(ec.Instance),
				"ballot": int(ec.Ballot), "cmd_op": cmdOp(ec.Command)})
			if int(m.to) == 2 {
				delivered = append(delivered, 2)
				p.deliver(m)
			}
		}
	}
	emit("commit_delivered", map[string]any{"replica": 0, "to": delivered})
	p.node(2).state("after_commit", 0, 0)
	p.crash(0)

	rec := p.node(3)
	rec.state("before_recovery", 0, 0)
	rec.r.startRecoveryForInstance(0, 0)
	selfReply := rec.r.InstanceSpace[0][0].lb.prepareReplies[0]
	emit("recovery_start", map[string]any{
		"replica": 3, "instance_row": 0, "instance_index": 0,
		"tried_ballot": int(selfReply.Ballot), "self_vballot": int(selfReply.VBallot),
		"self_status": int(selfReply.Status), "self_has_command": selfReply.Command != nil,
		"is_leader": rec.r.IsLeader})
	recipients := []int{}
	for _, m := range rec.drain() {
		if pr, ok := m.obj.(*Prepare); ok {
			recipients = append(recipients, int(m.to))
			emit("prepare_sent", map[string]any{
				"from": 3, "to": int(m.to), "instance_row": int(pr.Replica), "instance_index": int(pr.Instance), "ballot": int(pr.Ballot)})
			p.deliver(m)
		}
	}
	carriedOp := -1
	maxVB := -2
	for _, id := range recipients {
		for _, out := range p.node(int32(id)).drain() {
			rp, ok := out.obj.(*PrepareReply)
			if !ok {
				continue
			}
			hasCmd := rp.Command != nil && len(rp.Command) > 0
			op := -1
			if hasCmd {
				op = int(rp.Command[0].Op)
				if int(rp.VBallot) > maxVB {
					maxVB = int(rp.VBallot)
					carriedOp = op
				}
			}
			emit("prepare_reply", map[string]any{
				"from": int(out.from), "replica": int(out.from), "instance_row": int(rp.Replica),
				"instance_index": int(rp.Instance), "ballot": int(rp.Ballot), "vballot": int(rp.VBallot),
				"status": int(rp.Status), "has_command": hasCmd, "cmd_op": op})
			p.deliver(out)
		}
	}
	emit("adoption_inputs", map[string]any{
		"replica": 3, "instance_row": 0, "instance_index": 0,
		"self_vballot": int(selfReply.VBallot), "highest_reply_vballot_with_command": maxVB,
		"quorum_reply_command_op": carriedOp})

	proposed := -1
	proposedTo := []int{}
	for _, m := range rec.drain() {
		pa, ok := m.obj.(*PreAccept)
		if !ok {
			continue
		}
		proposedTo = append(proposedTo, int(m.to))
		if op, ok := cmdOp(pa.Command).(int); ok {
			proposed = op
		}
		p.deliver(m)
	}
	emit("recovery_proposal", map[string]any{
		"replica": 3, "instance_row": 0, "instance_index": 0, "to": proposedTo,
		"cmd_op": proposed, "quorum_reply_command_op": carriedOp})
	rec.state("after_recovery_proposal", 0, 0)

	p.pump(20)
	rec.state("after_first_attempt", 0, 0)

	// The executor's retry: a second recovery attempt at the same instance.
	rec.r.startRecoveryForInstance(0, 0)
	secondBallots := []int{}
	secondTo := []int{}
	for _, m := range rec.drain() {
		if pr, ok := m.obj.(*Prepare); ok {
			secondBallots = append(secondBallots, int(pr.Ballot))
			secondTo = append(secondTo, int(m.to))
			p.deliver(m)
		}
	}
	secondReplies := 0
	for _, id := range secondTo {
		for _, out := range p.node(int32(id)).drain() {
			if rp, ok := out.obj.(*PrepareReply); ok {
				secondReplies++
				emit("prepare_reply", map[string]any{
					"from": int(out.from), "replica": int(out.from), "instance_row": int(rp.Replica),
					"instance_index": int(rp.Instance), "ballot": int(rp.Ballot), "vballot": int(rp.VBallot),
					"status": int(rp.Status), "has_command": rp.Command != nil && len(rp.Command) > 0})
			}
			p.deliver(out)
		}
	}
	secondFollow := []string{}
	for _, m := range rec.drain() {
		switch t2 := m.obj.(type) {
		case *PreAccept:
			secondFollow = append(secondFollow, "preaccept")
			emit("recovery_proposal", map[string]any{
				"replica": 3, "instance_row": 0, "instance_index": 0, "to": []int{int(m.to)},
				"ballot": int(t2.Ballot), "cmd_op": cmdOp(t2.Command), "round": 2})
		case *Accept:
			secondFollow = append(secondFollow, "accept")
		case *Commit:
			secondFollow = append(secondFollow, "commit")
		}
		p.deliver(m)
	}
	attempt2 := rec.r.InstanceSpace[0][0]
	if attempt2.lb != nil {
		emit("recovery_attempt", map[string]any{
			"replica": 3, "instance_row": 0, "instance_index": 0, "round": 2,
			"prepare_ballots": secondBallots, "appended_replies": len(attempt2.lb.prepareReplies),
			"replies_received": secondReplies, "follow_up": secondFollow,
			"lb_status": int(attempt2.lb.status), "instance_status": int(attempt2.Status)})
	}

	p.pump(20)
	for _, id := range []int32{3, 2, 4, 0, 1} {
		p.node(id).state("final", 0, 0)
	}
}
