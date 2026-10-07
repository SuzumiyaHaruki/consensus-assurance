package epaxos

// Exploration harness: a replica that owns instance (0,0) but holds a record created by a
// message (no leader bookkeeping) receives a legal NOOP Commit for that instance, as a
// recovering replica would broadcast after restarting phase 1 with NOOP. The handler runs
// unmodified; the harness observes whether it panics instead of letting the test process die.

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

func nev(m map[string]any) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func newNoopNode() *Replica {
	base := &replica.Replica{
		Logger:             dlog.New("", false),
		N:                  3,
		F:                  1,
		Id:                 0,
		Alias:              "r0",
		PeerAddrList:       []string{"a", "b", "c"},
		State:              state.InitState(),
		Stats:              &defs.Stats{M: map[string]int{}},
		Alive:              []bool{true, true, true},
		PreferredPeerOrder: []int32{1, 2, 0},
		ProposeChan:        make(chan *defs.GPropose, 8),
		RPC:                fastrpc.NewTableId(defs.RPC_TABLE),
		Thrifty:            true,
		Dreply:             true,
	}
	w := make([]*bufio.Writer, 3)
	for i := range w {
		w[i] = bufio.NewWriter(&bytes.Buffer{})
	}
	base.PeerWriters = w
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

func TestAssuranceNoopCommitWithoutBookkeeping(t *testing.T) {
	r := newNoopNode()
	owner, inst := int32(0), int32(0)

	// The record exists because a message created it (a recovery-led PreAccept reached this
	// replica after it restarted): newInstanceDefault leaves leader bookkeeping nil.
	pa := &PreAccept{LeaderId: 1, Replica: owner, Instance: inst, Ballot: 3,
		Command: []state.Command{{Op: state.PUT, K: state.Key(5), V: state.Value([]byte{7})}}, Seq: 1,
		Deps: []int32{-1, -1, -1}}
	r.handlePreAccept(pa)
	rec := r.InstanceSpace[owner][inst]
	nev(map[string]any{"event": "record_from_message", "instance": "0.0",
		"bookkeeping_nil": rec.lb == nil, "status": int(rec.Status), "has_command": len(rec.Cmds) > 0})

	// The recovering replica commits instance (0,0) as a NOOP and broadcasts it; this replica
	// owns the instance, so handleCommit takes the re-proposal branch.
	commit := &Commit{LeaderId: 1, Replica: owner, Instance: inst, Ballot: 4,
		Command: []state.Command{{Op: state.NONE, K: 0, V: state.NIL()}}, Seq: 0, Deps: []int32{-1, -1, -1}}

	panicked := false
	var panicValue string
	func() {
		defer func() {
			if v := recover(); v != nil {
				panicked = true
				panicValue = fmt.Sprint(v)
			}
		}()
		r.handleCommit(commit)
	}()

	after := r.InstanceSpace[owner][inst]
	statusAfter := int(after.Status)
	nev(map[string]any{"event": "handle_commit_result", "instance": "0.0", "panicked": panicked,
		"panic_value": panicValue, "instance_status_after": statusAfter,
		"no_effect": statusAfter != int(COMMITTED)})
}
