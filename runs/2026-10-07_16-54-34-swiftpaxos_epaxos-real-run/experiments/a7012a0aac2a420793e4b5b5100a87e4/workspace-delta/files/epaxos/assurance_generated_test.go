package epaxos

// Exploration harness: with an instance that cannot be executed (its record has no commands
// and is not committed), does the executor's timeout path enqueue it for recovery, and after
// roughly the configured grace period? The executor runs as its own goroutine, as in the
// launched configuration, and the harness only reads the recovery channel.

import (
	"bufio"
	"bytes"
	"encoding/json"
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

func triggerNode() *Replica {
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
		prepareChan: make(chan fastrpc.Serializable, 4), preAcceptChan: make(chan fastrpc.Serializable, 4),
		acceptChan: make(chan fastrpc.Serializable, 4), commitChan: make(chan fastrpc.Serializable, 4),
		prepareReplyChan: make(chan fastrpc.Serializable, 4), preAcceptReplyChan: make(chan fastrpc.Serializable, 4),
		preAcceptOKChan: make(chan fastrpc.Serializable, 4), acceptReplyChan: make(chan fastrpc.Serializable, 4),
		tryPreAcceptChan: make(chan fastrpc.Serializable, 4), tryPreAcceptReplyChan: make(chan fastrpc.Serializable, 4),
		InstanceSpace: make([][]*Instance, 3), crtInstance: make([]int32, 3),
		CommittedUpTo: make([]int32, 3), ExecedUpTo: make([]int32, 3),
		conflicts: make([]map[state.Key]*InstPair, 3), maxSeqPerKey: make(map[state.Key]int32),
		clientMutex: new(sync.Mutex), instancesToRecover: make(chan *instanceId, 8), maxRecvBallot: -1,
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

func tev(m map[string]any) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func TestAssuranceRecoveryTriggerOnTimeout(t *testing.T) {
	r := triggerNode()
	owner, inst := int32(1), int32(0)

	// Row 1 is blocked at instance 0: the record exists but carries no commands and is not
	// committed, which is what a replica sees for an instance it never completed.
	r.InstanceSpace[owner][inst] = r.newInstanceDefault(owner, inst)
	r.crtInstance[owner] = inst
	r.ExecedUpTo[owner] = -1
	rec := r.InstanceSpace[owner][inst]
	tev(map[string]any{"event": "blocked_instance_prepared", "instance": "1.0",
		"status": int(rec.Status), "has_commands": len(rec.Cmds) > 0, "crt_instance": r.crtInstance[owner],
		"execed_up_to": r.ExecedUpTo[owner]})

	go r.executeCommands()
	defer func() { r.Shutdown = true }()

	start := time.Now()
	select {
	case iid := <-r.instancesToRecover:
		tev(map[string]any{"event": "recovery_enqueued", "instance": "1.0",
			"enqueued": true, "waited_ms": time.Since(start).Milliseconds(),
			"enqueued_replica": iid.replica, "enqueued_instance": iid.instance})
	case <-time.After(25 * time.Second):
		tev(map[string]any{"event": "recovery_enqueued", "instance": "1.0",
			"enqueued": false, "waited_ms": time.Since(start).Milliseconds()})
	}
}
