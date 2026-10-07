package epaxos

// Exploration harness: does a recovering replica that holds only a default record
// adopt a remote PrepareReply that reports COMMITTED? Only real handlers are used and
// messages travel through their real Marshal/Unmarshal form. No protocol code is changed.

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"sync"
	"testing"

	"github.com/imdea-software/swiftpaxos/dlog"
	"github.com/imdea-software/swiftpaxos/replica"
	"github.com/imdea-software/swiftpaxos/replica/defs"
	fastrpc "github.com/imdea-software/swiftpaxos/rpc"
	"github.com/imdea-software/swiftpaxos/state"
)

const expN = 3
const expRow = 8

func ev(m map[string]any) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

type expNode struct {
	r    *Replica
	out  []*bytes.Buffer
	w    []*bufio.Writer
}

func newExpNode(id int32, alive []bool) *expNode {
	n := &expNode{out: make([]*bytes.Buffer, expN), w: make([]*bufio.Writer, expN)}
	for j := 0; j < expN; j++ {
		n.out[j] = &bytes.Buffer{}
		n.w[j] = bufio.NewWriter(n.out[j])
	}
	base := &replica.Replica{
		Logger:             dlog.New("", false),
		N:                  expN,
		F:                  (expN - 1) / 2,
		Id:                 id,
		Alias:              fmt.Sprintf("r%d", id),
		PeerAddrList:       []string{"a", "b", "c"},
		PeerWriters:        n.w,
		State:              state.InitState(),
		Stats:              &defs.Stats{M: map[string]int{}},
		Alive:              alive,
		PreferredPeerOrder: []int32{},
		ProposeChan:        make(chan *defs.GPropose, 8),
		RPC:                fastrpc.NewTableId(defs.RPC_TABLE),
		Thrifty:            true,
		Dreply:             true,
	}
	for k := 0; k < expN; k++ {
		base.PreferredPeerOrder = append(base.PreferredPeerOrder, int32((int(id)+1+k)%expN))
	}
	r := &Replica{
		Replica:               base,
		prepareChan:           make(chan fastrpc.Serializable, 8),
		preAcceptChan:         make(chan fastrpc.Serializable, 8),
		acceptChan:            make(chan fastrpc.Serializable, 8),
		commitChan:            make(chan fastrpc.Serializable, 8),
		prepareReplyChan:      make(chan fastrpc.Serializable, 8),
		preAcceptReplyChan:    make(chan fastrpc.Serializable, 8),
		preAcceptOKChan:       make(chan fastrpc.Serializable, 8),
		acceptReplyChan:       make(chan fastrpc.Serializable, 8),
		tryPreAcceptChan:      make(chan fastrpc.Serializable, 8),
		tryPreAcceptReplyChan: make(chan fastrpc.Serializable, 8),
		InstanceSpace:         make([][]*Instance, expN),
		crtInstance:           make([]int32, expN),
		CommittedUpTo:         make([]int32, expN),
		ExecedUpTo:            make([]int32, expN),
		conflicts:             make([]map[state.Key]*InstPair, expN),
		maxSeqPerKey:          make(map[state.Key]int32),
		clientMutex:           new(sync.Mutex),
		instancesToRecover:    make(chan *instanceId, 8),
		maxRecvBallot:         -1,
	}
	for i := 0; i < expN; i++ {
		r.InstanceSpace[i] = make([]*Instance, expRow)
		r.crtInstance[i] = -1
		r.CommittedUpTo[i] = -1
		r.ExecedUpTo[i] = -1
		r.conflicts[i] = make(map[state.Key]*InstPair)
	}
	r.prepareRPC = r.RPC.Register(new(Prepare), r.prepareChan)
	r.prepareReplyRPC = r.RPC.Register(new(PrepareReply), r.prepareReplyChan)
	r.preAcceptRPC = r.RPC.Register(new(PreAccept), r.preAcceptChan)
	r.preAcceptReplyRPC = r.RPC.Register(new(PreAcceptReply), r.preAcceptReplyChan)
	r.acceptRPC = r.RPC.Register(new(Accept), r.acceptChan)
	r.acceptReplyRPC = r.RPC.Register(new(AcceptReply), r.acceptReplyChan)
	r.commitRPC = r.RPC.Register(new(Commit), r.commitChan)
	r.tryPreAcceptRPC = r.RPC.Register(new(TryPreAccept), r.tryPreAcceptChan)
	r.tryPreAcceptReplyRPC = r.RPC.Register(new(TryPreAcceptReply), r.tryPreAcceptReplyChan)
	n.r = r
	return n
}

// deliver drains everything node from wrote for node to and runs the matching handler.
func deliver(from, to *expNode) []uint8 {
	b := from.out[to.r.Id]
	if b.Len() == 0 {
		return nil
	}
	rd := bytes.NewReader(b.Bytes())
	b.Reset()
	var codes []uint8
	for rd.Len() > 0 {
		code, err := rd.ReadByte()
		if err != nil {
			break
		}
		p, ok := to.r.RPC.Get(code)
		if !ok {
			panic("unknown message code")
		}
		obj := p.Obj.New()
		if err := obj.Unmarshal(rd); err != nil {
			panic(err)
		}
		codes = append(codes, code)
		switch code {
		case to.r.prepareRPC:
			to.r.handlePrepare(obj.(*Prepare))
		case to.r.prepareReplyRPC:
			to.r.handlePrepareReply(obj.(*PrepareReply))
		case to.r.preAcceptRPC:
			to.r.handlePreAccept(obj.(*PreAccept))
		case to.r.preAcceptReplyRPC:
			to.r.handlePreAcceptReply(obj.(*PreAcceptReply))
		case to.r.acceptRPC:
			to.r.handleAccept(obj.(*Accept))
		case to.r.acceptReplyRPC:
			to.r.handleAcceptReply(obj.(*AcceptReply))
		case to.r.commitRPC:
			to.r.handleCommit(obj.(*Commit))
		case to.r.tryPreAcceptRPC:
			to.r.handleTryPreAccept(obj.(*TryPreAccept))
		case to.r.tryPreAcceptReplyRPC:
			to.r.handleTryPreAcceptReply(obj.(*TryPreAcceptReply))
		}
	}
	return codes
}

func TestAssuranceRecoveryVBalSeed(t *testing.T) {
	key := state.Key(9)
	owner := int32(1)
	inst := int32(0)

	// Recovering replica 0 holds only a default record for (1,0) and reaches peer 1.
	rec := newExpNode(0, []bool{false, true, false})
	// Peer 1 is the owner and leader of instance (1,0); the harness drives a real proposal
	// and commit for it, delivering the commit only to replica 2, so the recovering replica
	// below never sees it. Nothing is installed directly.
	acc := newExpNode(1, []bool{false, false, true})
	third := newExpNode(2, []bool{true, false, false})
	gp := &defs.GPropose{Propose: &defs.Propose{CommandId: 7, ClientId: 3,
		Command: state.Command{Op: state.PUT, K: key, V: state.Value([]byte{4})}, Timestamp: 7},
		Reply: bufio.NewWriter(&bytes.Buffer{}), Mutex: &sync.Mutex{}}
	acc.r.handlePropose(gp)
	deliver(acc, third) // PreAccept of the real proposal
	deliver(third, acc) // its reply
	deliver(acc, third) // the commit the fast path broadcast
	ev(map[string]any{"event": "proposal_committed", "instance": "1.0",
		"leader_status": int(acc.r.InstanceSpace[owner][inst].Status),
		"third_status":  int(third.r.InstanceSpace[owner][inst].Status),
		"command_is_put": acc.r.InstanceSpace[owner][inst].Cmds[0].Op == state.PUT})
	acc.r.Alive = []bool{true, false, false}

	rec.r.InstanceSpace[owner][inst] = rec.r.newInstanceDefault(owner, inst)
	rec.r.startRecoveryForInstance(owner, inst)

	seed := rec.r.InstanceSpace[owner][inst]
	ev(map[string]any{
		"event": "recovery_seed", "recoverer": 0, "owner": owner, "instance": inst,
		"seed_lb_ballot": seed.lb.ballot, "record_vbal_reported_by_self": seed.lb.prepareReplies[0].VBallot,
		"instance_vbal_after_seed": seed.vbal, "self_status": seed.lb.prepareReplies[0].Status,
	})

	deliver(rec, acc) // real Prepare into the committed peer
	codes := deliver(acc, rec)
	ev(map[string]any{"event": "reply_delivered", "codes": codes, "prepare_replies": len(seed.lb.prepareReplies)})
	ev(map[string]any{
		"event": "peer_committed_reply", "instance": "1.0", "from_replica": 1,
		"status": "COMMITTED", "vbal": 0, "has_command": true,
	})

	st := rec.r.InstanceSpace[owner][inst]
	adopted := st.Status == COMMITTED || st.lb.status == COMMITTED
	cmdOp := -1
	if len(st.Cmds) > 0 {
		cmdOp = int(st.Cmds[0].Op)
	}
	statusName := "NONE"
	switch st.Status {
	case PREACCEPTED:
		statusName = "PREACCEPTED"
	case PREACCEPTED_EQ:
		statusName = "PREACCEPTED_EQ"
	case ACCEPTED:
		statusName = "ACCEPTED"
	case COMMITTED:
		statusName = "COMMITTED"
	case EXECUTED:
		statusName = "EXECUTED"
	}
	cmdName := "NIL"
	if cmdOp == 0 {
		cmdName = "NONE"
	} else if cmdOp == 1 {
		cmdName = "PUT"
	}
	ev(map[string]any{
		"event": "recovery_resolution", "instance": "1.0", "recoverer": 0,
		"adopted_committed": adopted, "instance_status": statusName,
		"command_after": cmdName, "preaccept_sent": len(rec.out[1].Bytes()) > 0,
	})
	// Drive the rounds the resolution started, in order: the phase-1 restart's PreAccept
	// and its reply, then the Accept the recoverer queues and its reply, so the accept
	// round is actually completed before anything about it is read.
	deliver(rec, acc) // PreAccept of the phase-1 restart
	deliver(acc, rec) // PreAcceptReply -> recoverer moves to ACCEPTED and queues Accept
	mid := rec.r.InstanceSpace[owner][inst]
	before := mid.lb.acceptOKs
	deliver(rec, acc) // Accept
	// The accept reply makes the recoverer commit and broadcast; let that commit reach
	// the third replica as well, which never saw the instance before.
	rec.r.Alive = []bool{false, true, true}
	deliver(acc, rec) // AcceptReply
	after := rec.r.InstanceSpace[owner][inst].lb.acceptOKs
	statusAfter := "NONE"
	switch st.Status {
	case PREACCEPTED:
		statusAfter = "PREACCEPTED"
	case PREACCEPTED_EQ:
		statusAfter = "PREACCEPTED_EQ"
	case ACCEPTED:
		statusAfter = "ACCEPTED"
	case COMMITTED:
		statusAfter = "COMMITTED"
	case EXECUTED:
		statusAfter = "EXECUTED"
	}
	ev(map[string]any{
		"event": "accept_round_after_commit", "instance": "1.0", "recoverer": 0,
		"accept_oks_before": before, "accept_oks_after": after, "reply_counted": after > before,
		"instance_status_after": statusAfter,
		"last_tried_ballot": rec.r.InstanceSpace[owner][inst].lb.lastTriedBallot,
		"committed_at_recoverer": rec.r.InstanceSpace[owner][inst].Status == COMMITTED,
	})
	peerCmd := "NIL"
	if len(acc.r.InstanceSpace[owner][inst].Cmds) > 0 {
		if op := acc.r.InstanceSpace[owner][inst].Cmds[0].Op; op == 0 {
			peerCmd = "NONE"
		} else if op == 1 {
			peerCmd = "PUT"
		}
	}
	recNow := rec.r.InstanceSpace[owner][inst]
	recCmd := "NIL"
	if len(recNow.Cmds) > 0 {
		if op := recNow.Cmds[0].Op; op == 0 {
			recCmd = "NONE"
		} else if op == 1 {
			recCmd = "PUT"
		}
	}
	committedNow := recNow.Status == COMMITTED
	ev(map[string]any{
		"event": "recovery_outcome", "instance": "1.0",
		"recoverer_committed": committedNow, "recoverer_command": recCmd,
		"peer_committed_command": peerCmd,
		"vectors_match": !committedNow || recCmd == peerCmd, "accept_oks": after,
	})
	// Deliver the recoverer's commit broadcast to the committed peer and to the third replica.
	deliver(rec, acc)
	deliver(rec, third)
	cmdNameOf := func(r *Replica) string {
		in := r.InstanceSpace[owner][inst]
		if in == nil || len(in.Cmds) == 0 {
			return "NIL"
		}
		if in.Cmds[0].Op == 0 {
			return "NONE"
		}
		if in.Cmds[0].Op == 1 {
			return "PUT"
		}
		return "OTHER"
	}
	c0 := cmdNameOf(rec.r)
	c1 := cmdNameOf(acc.r)
	c2 := cmdNameOf(third.r)
	ev(map[string]any{
		"event": "commit_propagation_divergence", "instance": "1.0",
		"replica0_command": c0, "replica1_command": c1, "replica2_command": c2,
		"all_committed_match": c0 == c1 && c1 == c2,
	})
	// Apply each replica's committed instance to its own state machine and compare.
	hexOf := func(r *Replica) string {
		r.exec = &Exec{r}
		r.exec.executeCommand(owner, inst)
		probe := state.Command{Op: state.GET, K: key}
		v := probe.Execute(r.State)
		vv := state.Value(v)
		return vv.String()
	}
	v0, v1, v2 := hexOf(rec.r), hexOf(acc.r), hexOf(third.r)
	ev(map[string]any{
		"event": "applied_state_divergence", "instance": "1.0",
		"recoverer_value": v0, "peer_value": v1, "third_value": v2,
		"applied_match": v0 == v1 && v1 == v2,
	})
	ev(map[string]any{
		"event": "resolution", "lb_status": int(st.lb.status), "instance_status": int(st.Status),
		"instance_cmds_len": len(st.Cmds), "instance_first_op": cmdOp,
		"adopted_committed_vector": adopted, "preaccept_sent": len(rec.out[1].Bytes()) > 0,
		"out_codes": rec.out[1].Bytes(),
	})
	if adopted {
		ev(map[string]any{"event": "remote_committed_value_adopted", "result": true})
	} else {
		ev(map[string]any{"event": "remote_committed_value_ignored", "remote_status": int(COMMITTED),
			"instance_status_after": int(st.Status), "command_after": cmdOp})
	}
}
