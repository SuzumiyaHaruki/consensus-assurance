package epaxos

import (
    "bufio"
    "bytes"
    "encoding/json"
    "fmt"
    "reflect"
    "testing"

    "github.com/imdea-software/swiftpaxos/dlog"
    "github.com/imdea-software/swiftpaxos/replica"
    "github.com/imdea-software/swiftpaxos/replica/defs"
    fastrpc "github.com/imdea-software/swiftpaxos/rpc"
    "github.com/imdea-software/swiftpaxos/state"
)

// This probe uses constructor-equivalent empty protocol containers of bounded
// size. It bypasses network startup, the event loop, timers and execution workers.
// All instance contents after initialization are produced by actual handlers.
func assuranceEmptyReplica(id int32) (*Replica, []*bytes.Buffer) {
    const n = 3
    base := &replica.Replica{
        Logger: dlog.New("", false), N: n, F: 1, Id: id, Thrifty: true,
        PeerWriters: make([]*bufio.Writer, n), Alive: []bool{true,true,true},
        PreferredPeerOrder: []int32{(id+1)%n, (id+2)%n, id},
        Stats: &defs.Stats{M: make(map[string]int)},
        ProposeChan: make(chan *defs.GPropose, 1),
    }
    r := &Replica{Replica: base, InstanceSpace: make([][]*Instance,n),
        crtInstance: []int32{-1,-1,-1}, CommittedUpTo: []int32{-1,-1,-1},
        ExecedUpTo: []int32{-1,-1,-1}, conflicts: make([]map[state.Key]*InstPair,n),
        maxSeqPerKey: make(map[state.Key]int32), maxRecvBallot: -1,
        latestCPInstance: -1, prepareRPC: 10, prepareReplyRPC: 11,
        preAcceptRPC: 12, preAcceptReplyRPC: 13,
    }
    wires := make([]*bytes.Buffer,n)
    for i:=0;i<n;i++ {
        r.InstanceSpace[i] = make([]*Instance,4)
        r.conflicts[i] = make(map[state.Key]*InstPair)
        wires[i] = new(bytes.Buffer)
        base.PeerWriters[i] = bufio.NewWriter(wires[i])
    }
    return r,wires
}

func assuranceDecode(t *testing.T, wire *bytes.Buffer, code byte, dst fastrpc.Serializable) {
    t.Helper()
    got,err:=wire.ReadByte()
    if err!=nil || got!=code { t.Fatalf("RPC code got %d, err %v; want %d",got,err,code) }
    if err:=dst.Unmarshal(wire);err!=nil { t.Fatal(err) }
    if wire.Len()!=0 { t.Fatalf("unexpected trailing bytes: %d",wire.Len()) }
}

func TestAssurancePrepareReplyProducerTransport(t *testing.T) {
    owner, ow := assuranceEmptyReplica(1)
    acceptor, aw := assuranceEmptyReplica(2)
    recoverer, rw := assuranceEmptyReplica(0)
    proposal := &defs.GPropose{Propose: &defs.Propose{CommandId: 71,ClientId: 9,
        Command: state.Command{Op: state.PUT,K: 17,V: state.Value("payload")}}}
    owner.handlePropose(proposal)
    pa := new(PreAccept)
    assuranceDecode(t,ow[2],owner.preAcceptRPC,pa)
    acceptor.handlePreAccept(pa)
    // Keep the actual PreAcceptReply pending; no quorum or commit is asserted.
    before := acceptor.InstanceSpace[1][0]
    acceptedValueBallot := before.vbal
    if acceptedValueBallot!=1 || before.Status!=PREACCEPTED_EQ { t.Fatal("preaccept prefix not reached") }
    recoverer.startRecoveryForInstance(1,0)
    prep := new(Prepare)
    assuranceDecode(t,rw[2],recoverer.prepareRPC,prep)
    acceptor.handlePrepare(prep)
    // This is the actual handlePrepare -> replyPrepare -> SendMsg byte stream.
    reply := new(PrepareReply).New().(*PrepareReply)
    assuranceDecode(t,aw[0],acceptor.prepareReplyRPC,reply)
    inst := acceptor.InstanceSpace[1][0]
    identityOK := reply.AcceptorId==2 && reply.Replica==1 && reply.Instance==0
    otherFieldsOK := reply.Ballot==inst.bal && reply.Status==inst.Status && reply.Seq==inst.Seq &&
        reflect.DeepEqual(reply.Command,inst.Cmds) && reflect.DeepEqual(reply.Deps,inst.Deps)
    event := map[string]any{
        "kind":"prepare_reply_transport", "operation_id":"client9-command71-instance1.0",
        "preaccept_ballot":pa.Ballot,"prepare_ballot":prep.Ballot,
        "producer_vballot_before_prepare":acceptedValueBallot,"producer_vballot_after_prepare":inst.vbal,
        "decoded_vballot":reply.VBallot,"identity_preserved":identityOK,
        "other_fields_preserved":otherFieldsOK,"value_ballot_preserved":reply.VBallot==inst.vbal,
        "producer_status":inst.Status,"decoded_status":reply.Status,
    }
    data,err:=json.Marshal(event);if err!=nil { t.Fatal(err) }
    fmt.Println("CA_EVENT "+string(data))
    if !identityOK || !otherFieldsOK { t.Fatal("probe correlation or other fields failed") }
    // This exploration reports the measured comparison without a formal verdict.
}
