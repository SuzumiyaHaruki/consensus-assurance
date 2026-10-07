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
	// Peer 1 has already committed that instance with a real command.
	acc := newExpNode(1, []bool{true, false, false})
	cmds := []state.Command{{Op: state.PUT, K: key, V: state.Value([]byte{4})}}
	acc.r.InstanceSpace[owner][inst] = &Instance{
		Cmds: cmds, bal: 0, vbal: 0, Status: COMMITTED, Seq: 3,
		Deps: []int32{-1, -1, -1}, id: &instanceId{owner, inst},
	}

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

	st := rec.r.InstanceSpace[owner][inst]
	adopted := st.Status == COMMITTED || st.lb.status == COMMITTED
	cmdOp := -1
	if len(st.Cmds) > 0 {
		cmdOp = int(st.Cmds[0].Op)
	}
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
