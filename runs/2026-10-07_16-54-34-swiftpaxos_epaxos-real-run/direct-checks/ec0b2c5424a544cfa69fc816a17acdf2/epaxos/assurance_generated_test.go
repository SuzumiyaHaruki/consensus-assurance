package epaxos

// Exploration harness: with Durable enabled, does recordInstanceMetadata preserve
// every scalar it writes (bal, vbal, Status, Seq) in the record it produces?
// Only the real recorder is used; the file is a temp file created by the harness.

import (
	"encoding/binary"
	"encoding/hex"
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

func dev(m map[string]any) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func newDurableNode(t *testing.T, f *os.File) *Replica {
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
		Durable:            true,
		StableStore:        f,
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

func TestAssuranceDurableMetadata(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "stable_store")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	r := newDurableNode(t, f)
	if !r.Durable {
		t.Fatal("harness requires Durable true")
	}
	bal := int32(0x0A0B0C0D)
	vbal := int32(0x01020304)
	seq := int32(0x0D0E0F10)
	inst := &Instance{
		Cmds: []state.Command{{Op: state.PUT, K: state.Key(1), V: state.Value([]byte{9})}},
		bal:  bal, vbal: vbal, Status: ACCEPTED, Seq: seq,
		Deps: []int32{2, 3, 4}, id: &instanceId{0, 0},
	}
	dev(map[string]any{
		"event": "durable_write_request", "instance": "0.0", "durable": r.Durable,
		"bal": int(bal), "vbal": int(vbal), "status": int(ACCEPTED), "seq": int(seq),
	})
	r.recordInstanceMetadata(inst)
	r.sync()
	f.Close()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	headerLen := 9 + 3*4
	header := raw
	if len(header) > headerLen {
		header = header[:headerLen]
	}
	be := func(v int32) []byte {
		b := make([]byte, 4)
		binary.LittleEndian.PutUint32(b, uint32(v))
		return b
	}
	has := func(needle []byte, start, end int) bool {
		if end > len(header) {
			return false
		}
		return string(header[start:end]) == string(needle)
	}
	dev(map[string]any{
		"event": "durable_record_header", "instance": "0.0", "record_len": len(raw), "header_len": headerLen,
		"header_hex": hex.EncodeToString(header),
		"bal_at_0": has(be(bal), 0, 4), "vbal_at_0": has(be(vbal), 0, 4),
		"status_at_4": header[4] == byte(ACCEPTED), "seq_at_5": has(be(seq), 5, 9),
		"bal_field_present": string(header[0:4]) == string(be(bal)),
		"written_bal": int(bal), "written_vbal": int(vbal), "written_status": int(ACCEPTED), "written_seq": int(seq),
	})
	if string(header[0:4]) != string(be(bal)) {
		dev(map[string]any{"event": "durable_record_field_lost", "field": "bal",
			"expected_hex": hex.EncodeToString(be(bal)), "found_hex": hex.EncodeToString(header[0:4])})
	} else {
		dev(map[string]any{"event": "durable_record_field_lost", "field": "none"})
	}
}
