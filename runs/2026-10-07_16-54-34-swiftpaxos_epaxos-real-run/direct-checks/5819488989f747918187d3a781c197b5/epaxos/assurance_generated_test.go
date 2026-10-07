package epaxos

// Exploration harness: a leader in the ACCEPTED phase of instance (1,0) receives an
// AcceptReply whose ballot is higher than the ballot it is using. The handler has a branch
// for that case (count a nack, and re-prepare once a majority nacks). The harness reports
// what the real handler does with the reply.

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

func nev2(m map[string]any) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func newAcceptNode() *Replica {
	w := make([]*bufio.Writer, 3)
	bufs := make([]*bytes.Buffer, 3)
	for i := range w {
		bufs[i] = &bytes.Buffer{}
		w[i] = bufio.NewWriter(bufs[i])
	}
	base := &replica.Replica{
		Logger: dlog.New("", false), N: 3, F: 1, Id: 0, Alias: "r0",
		PeerAddrList: []string{"a", "b", "c"}, PeerWriters: w,
		State: state.InitState(), Stats: &defs.Stats{M: map[string]int{}},
		Alive: []bool{true, true, true}, PreferredPeerOrder: []int32{1, 2, 0},
		ProposeChan: make(chan *defs.GPropose, 8), RPC: fastrpc.NewTableId(defs.RPC_TABLE),
		Thrifty: true, Dreply: true,
	}
	r := &Replica{
		Replica: base,
		prepareChan:           make(chan fastrpc.Serializable, 4),
		preAcceptChan:         make(chan fastrpc.Serializable, 4),
		acceptChan:            make(chan fastrpc.Serializable, 4),
		commitChan:            make(chan fastrpc.Serializable, 4),
		prepareReplyChan:      make(chan fastrpc.Serializable, 4),
		preAcceptReplyChan:    make(chan fastrpc.Serializable, 4),
		preAcceptOKChan:       make(chan fastrpc.Serializable, 4),
		acceptReplyChan:       make(chan fastrpc.Serializable, 4),
		tryPreAcceptChan:      make(chan fastrpc.Serializable, 4),
		tryPreAcceptReplyChan: make(chan fastrpc.Serializable, 4),
		InstanceSpace:         make([][]*Instance, 3),
		crtInstance:           make([]int32, 3),
		CommittedUpTo:         make([]int32, 3),
		ExecedUpTo:            make([]int32, 3),
		conflicts:             make([]map[state.Key]*InstPair, 3),
		maxSeqPerKey:          make(map[state.Key]int32),
		clientMutex:           new(sync.Mutex),
		instancesToRecover:    make(chan *instanceId, 4),
		maxRecvBallot:         -1,
		IsLeader:              true,
	}
	for i := 0; i < 3; i++ {
		r.InstanceSpace[i] = make([]*Instance, 8)
		r.crtInstance[i], r.CommittedUpTo[i], r.ExecedUpTo[i] = -1, -1, -1
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
	return r
}

func TestAssuranceAcceptReplyHigherBallot(t *testing.T) {
	r := newAcceptNode()
	owner, inst := int32(1), int32(0)
	round := int32(3)

	// The leader is in the accept phase for (1,0) at ballot 3.
	in := r.newInstance(owner, inst, []state.Command{{Op: state.PUT, K: state.Key(5), V: state.Value([]byte{1})}},
		round, round, ACCEPTED, 1, []int32{-1, -1, -1})
	in.lb = r.newLeaderBookkeeping(nil, r.newNilDeps(), r.newNilDeps(), r.newNilDeps(), round, in.Cmds, ACCEPTED, 1)
	r.InstanceSpace[owner][inst] = in
	nev2(map[string]any{"event": "leader_round", "instance": "1.0", "last_tried_ballot": round,
		"status": int(in.lb.status), "is_leader": r.IsLeader})

	// A peer that has promised a higher ballot answers the accept round.
	r.handleAcceptReply(&AcceptReply{Replica: owner, Instance: inst, Ballot: round + 2})
	after := r.InstanceSpace[owner][inst]
	nev2(map[string]any{"event": "accept_reply_higher_ballot", "instance": "1.0",
		"reply_ballot": round + 2, "nacks": after.lb.nacks, "accept_oks": after.lb.acceptOKs,
		"prepare_sent": r.PeerWriters[1].Buffered() > 0 || r.PeerWriters[2].Buffered() > 0,
		"status_after": int(after.lb.status)})
}
