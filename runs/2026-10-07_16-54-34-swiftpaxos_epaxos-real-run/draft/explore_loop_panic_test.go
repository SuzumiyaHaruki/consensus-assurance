package epaxos

// Exploration harness: the crash findings (a legal NOOP commit for a record without leader
// bookkeeping) are observed here inside the replica's own event loop rather than by calling
// the handler, so the step from "the handler panics" to "the replica process ends" is
// exercised instead of inferred. A single-replica configuration is used so the loop starts
// without peers.

import (
	"bufio"
	"bytes"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/imdea-software/swiftpaxos/dlog"
	"github.com/imdea-software/swiftpaxos/replica"
	"github.com/imdea-software/swiftpaxos/replica/defs"
	fastrpc "github.com/imdea-software/swiftpaxos/rpc"
	"github.com/imdea-software/swiftpaxos/state"
)

func TestAssuranceRunLoopPanicPropagation(t *testing.T) {
	addr := "127.0.0.1:39451"
	base := &replica.Replica{
		Logger:             dlog.New("", false),
		N:                  1,
		F:                  0,
		Id:                 0,
		Alias:              "r0",
		PeerAddrList:       []string{addr},
		PeerWriters:        []*bufio.Writer{bufio.NewWriter(&bytes.Buffer{})},
		State:              state.InitState(),
		Stats:              &defs.Stats{M: map[string]int{}},
		Alive:              []bool{true},
		PreferredPeerOrder: []int32{0},
		ProposeChan:        make(chan *defs.GPropose, 8),
		BeaconChan:         make(chan *defs.GBeacon, 8),
		RPC:                fastrpc.NewTableId(defs.RPC_TABLE),
		Thrifty:            true,
		Dreply:             true,
	}
	r := &Replica{
		Replica:               base,
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
		InstanceSpace:         make([][]*Instance, 1),
		crtInstance:           make([]int32, 1),
		CommittedUpTo:         make([]int32, 1),
		ExecedUpTo:            make([]int32, 1),
		conflicts:             make([]map[state.Key]*InstPair, 1),
		maxSeqPerKey:          make(map[state.Key]int32),
		clientMutex:           new(sync.Mutex),
		instancesToRecover:    make(chan *instanceId, 4),
		maxRecvBallot:         -1,
	}
	r.InstanceSpace[0] = make([]*Instance, 8)
	r.crtInstance[0], r.CommittedUpTo[0], r.ExecedUpTo[0] = -1, -1, -1
	r.conflicts[0] = make(map[state.Key]*InstPair)
	r.prepareRPC = r.RPC.Register(new(Prepare), r.prepareChan)
	r.prepareReplyRPC = r.RPC.Register(new(PrepareReply), r.prepareReplyChan)
	r.preAcceptRPC = r.RPC.Register(new(PreAccept), r.preAcceptChan)
	r.preAcceptReplyRPC = r.RPC.Register(new(PreAcceptReply), r.preAcceptReplyChan)
	r.acceptRPC = r.RPC.Register(new(Accept), r.acceptChan)
	r.acceptReplyRPC = r.RPC.Register(new(AcceptReply), r.acceptReplyChan)
	r.commitRPC = r.RPC.Register(new(Commit), r.commitChan)
	r.tryPreAcceptRPC = r.RPC.Register(new(TryPreAccept), r.tryPreAcceptChan)
	r.tryPreAcceptReplyRPC = r.RPC.Register(new(TryPreAcceptReply), r.tryPreAcceptReplyChan)

	go r.run()
	time.Sleep(500 * time.Millisecond)
	fmt.Println("CA_EVENT {\"event\":\"loop_started\",\"listener_up\":", r.Listener != nil, "}")

	// The delivered message is the same legal NOOP commit the crash checks use; here it is
	// queued for the loop, so any panic happens inside the replica's own goroutine.
	r.InstanceSpace[0][0] = r.newInstanceDefault(0, 0)
	r.crtInstance[0] = 0
	r.commitChan <- &Commit{LeaderId: 1, Replica: 0, Instance: 0, Ballot: 1,
		Command: []state.Command{{Op: state.NONE, K: 0, V: state.NIL()}}, Seq: 0, Deps: []int32{-1}}
	time.Sleep(2 * time.Second)
	fmt.Println("CA_EVENT {\"event\":\"loop_survived\"}")
}
