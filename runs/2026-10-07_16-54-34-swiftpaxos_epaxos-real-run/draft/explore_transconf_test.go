package epaxos

// Exploration harness: the executor has a branch for transitive conflicts, gated on the
// transconf flag, whose stated purpose is to skip waiting for prior commands that commute
// with the instance being executed. The harness builds exactly that situation - a committed
// instance whose dependency is an uncommitted command on a different key - with the flag on
// and asks the real executor to run it.

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

func xev(m map[string]any) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func transconfNode() *Replica {
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
		Thrifty: true, Dreply: true, Exec: true,
	}
	r := &Replica{
		Replica: base,
		prepareChan: make(chan fastrpc.Serializable, 4), preAcceptChan: make(chan fastrpc.Serializable, 4),
		acceptChan: make(chan fastrpc.Serializable, 4), commitChan: make(chan fastrpc.Serializable, 4),
		prepareReplyChan: make(chan fastrpc.Serializable, 4), preAcceptReplyChan: make(chan fastrpc.Serializable, 4),
		preAcceptOKChan: make(chan fastrpc.Serializable, 4), acceptReplyChan: make(chan fastrpc.Serializable, 4),
		tryPreAcceptChan: make(chan fastrpc.Serializable, 4), tryPreAcceptReplyChan: make(chan fastrpc.Serializable, 4),
		InstanceSpace: make([][]*Instance, 3), crtInstance: make([]int32, 3),
		CommittedUpTo: make([]int32, 3), ExecedUpTo: make([]int32, 3),
		conflicts: make([]map[state.Key]*InstPair, 3), maxSeqPerKey: make(map[state.Key]int32),
		clientMutex: new(sync.Mutex), instancesToRecover: make(chan *instanceId, 8),
		maxRecvBallot: -1, transconf: true,
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

func TestAssuranceTransitiveCommutingDependency(t *testing.T) {
	r := transconfNode()
	k1 := state.Key(101)
	k2 := state.Key(202)
	// Row 1 holds an uncommitted command on k1; row 0's instance is committed with a
	// dependency on it, but its own command touches k2 only, so the two commute.
	r.InstanceSpace[1][0] = &Instance{
		Cmds: []state.Command{{Op: state.PUT, K: k1, V: state.Value([]byte{1})}},
		bal: 0, vbal: 0, Status: PREACCEPTED, Seq: 0, Deps: []int32{-1, -1, -1},
		id: &instanceId{1, 0},
	}
	r.InstanceSpace[0][0] = &Instance{
		Cmds: []state.Command{{Op: state.PUT, K: k2, V: state.Value([]byte{2})}},
		bal: 0, vbal: 0, Status: COMMITTED, Seq: 0,
		Deps: []int32{-1, 0, -1}, id: &instanceId{0, 0},
	}
	r.crtInstance[1], r.crtInstance[0] = 0, 0
	xev(map[string]any{"event": "transconf_prepared", "transconf": r.transconf,
		"dependency_status": int(r.InstanceSpace[1][0].Status),
		"executing_status":  int(r.InstanceSpace[0][0].Status),
		"commands_commute": !state.Conflict(&r.InstanceSpace[1][0].Cmds[0], &r.InstanceSpace[0][0].Cmds[0])})

	r.exec = &Exec{r}
	executed := r.exec.executeCommand(0, 0)
	xev(map[string]any{"event": "transconf_execution", "executed": executed,
		"status_after":      int(r.InstanceSpace[0][0].Status),
		"dependency_status": int(r.InstanceSpace[1][0].Status)})
}
