package epaxos

// Exploration harness: the owner of an instance that a recovery commits as NOOP receives
// that commit while it still holds the admitted client proposal. Does handleCommit
// re-propose the operation, and is the proposal then pending on the replica's propose
// channel (the path that later produces the client's reply)?

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

func rev(m map[string]any) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func newReproposeNode() *Replica {
	w := make([]*bufio.Writer, 3)
	for i := range w {
		w[i] = bufio.NewWriter(&bytes.Buffer{})
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

func TestAssuranceNoopCommitReproposes(t *testing.T) {
	r := newReproposeNode()
	owner, inst := int32(0), int32(0)
	key := state.Key(5)

	// The owner admits a client operation: handlePropose attaches the proposal to the
	// instance it allocates and broadcasts the PreAccept.
	reply := bufio.NewWriter(&bytes.Buffer{})
	gp := &defs.GPropose{Propose: &defs.Propose{CommandId: 1, ClientId: 1,
		Command: state.Command{Op: state.PUT, K: key, V: state.Value([]byte{9})}, Timestamp: 1},
		Reply: reply, Mutex: &sync.Mutex{}}
	r.handlePropose(gp)
	rec := r.InstanceSpace[owner][inst]
	rev(map[string]any{"event": "proposal_admitted", "instance": "0.0",
		"has_bookkeeping": rec.lb != nil, "pending": len(rec.lb.clientProposals)})

	// A recoverer commits the instance as NOOP and the commit reaches the owner.
	commit := &Commit{LeaderId: 1, Replica: owner, Instance: inst, Ballot: 4,
		Command: []state.Command{{Op: state.NONE, K: 0, V: state.NIL()}}, Seq: 0, Deps: []int32{-1, -1, -1}}
	r.handleCommit(commit)
	after := r.InstanceSpace[owner][inst]
	rev(map[string]any{"event": "noop_commit_at_owner", "instance": "0.0",
		"instance_status": int(after.Status), "pending_after": len(after.lb.clientProposals),
		"reproposed_on_channel": len(r.ProposeChan)})
}
