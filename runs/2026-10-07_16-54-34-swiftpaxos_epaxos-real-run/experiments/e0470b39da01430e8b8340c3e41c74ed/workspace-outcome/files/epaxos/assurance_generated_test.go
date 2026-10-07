package epaxos

// Exploration harness: with Durable enabled, a recovery-led phase 1 writes for an instance
// owned by another replica. The recorder is called with r.InstanceSpace[r.Id][instance], the
// recovering replica's own row, which need not hold that instance at all.

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"github.com/imdea-software/swiftpaxos/dlog"
	"github.com/imdea-software/swiftpaxos/replica"
	"github.com/imdea-software/swiftpaxos/replica/defs"
	fastrpc "github.com/imdea-software/swiftpaxos/rpc"
	"github.com/imdea-software/swiftpaxos/state"
)

func dev2(m map[string]any) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func durableNode(t *testing.T, f *os.File) *Replica {
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
		Thrifty: true, Dreply: true, Durable: true, StableStore: f,
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

func TestAssuranceDurableRowOfRecoveryLedPhase1(t *testing.T) {
	path := filepath.Join(t.TempDir(), "stable_store")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	r := durableNode(t, f)
	owner, inst := int32(1), int32(0)

	dev2(map[string]any{"event": "durable_phase1_prepared", "instance": "1.0",
		"durable": r.Durable, "recoverer": r.Id, "owner": owner,
		"own_row_record_present": r.InstanceSpace[r.Id][inst] != nil})

	panicked := false
	panicValue := ""
	func() {
		defer func() {
			if v := recover(); v != nil {
				panicked = true
				panicValue = fmt.Sprint(v)
			}
		}()
		r.startPhase1([]state.Command{{Op: state.PUT, K: state.Key(3), V: state.Value([]byte{5})}},
			owner, inst, 3, nil)
	}()
	dev2(map[string]any{"event": "durable_phase1_result", "instance": "1.0",
		"panicked": panicked, "panic_value": panicValue,
		"owner_record_written": r.InstanceSpace[owner][inst] != nil,
		"own_row_record_written": r.InstanceSpace[r.Id][inst] != nil})
}
