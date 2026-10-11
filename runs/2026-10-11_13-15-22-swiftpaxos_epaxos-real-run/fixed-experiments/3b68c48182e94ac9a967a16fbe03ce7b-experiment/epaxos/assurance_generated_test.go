package epaxos

import (
    "bufio"
    "bytes"
    "encoding/hex"
    "encoding/json"
    "fmt"
    "sync"
    "testing"

    "github.com/imdea-software/swiftpaxos/dlog"
    "github.com/imdea-software/swiftpaxos/replica"
    "github.com/imdea-software/swiftpaxos/replica/defs"
    "github.com/imdea-software/swiftpaxos/state"
)

// Initialize the empty, non-durable handler state of New without starting its
// network listeners, clocks or workers. No instance or leader state is supplied.
// Only instance capacity and transport are reduced; all protocol mutations below
// are made by production proposal, recovery and prepare handlers.
func assuranceEmptyReplica(id int32) (*Replica, []*bytes.Buffer) {
    const n = 3
    base := &replica.Replica{
        Logger: dlog.New("", false), N: n, F: 1, Id: id,
        Thrifty: true, Dreply: true,
        PeerWriters: make([]*bufio.Writer, n), Alive: make([]bool, n),
        PreferredPeerOrder: make([]int32, n),
        ProposeChan: make(chan *defs.GPropose, 8),
        Stats: &defs.Stats{M: make(map[string]int)}, State: state.InitState(),
    }
    r := &Replica{
        Replica: base, InstanceSpace: make([][]*Instance, n),
        crtInstance: make([]int32, n), CommittedUpTo: make([]int32, n),
        ExecedUpTo: make([]int32, n), conflicts: make([]map[state.Key]*InstPair, n),
        maxSeqPerKey: make(map[state.Key]int32), latestCPInstance: -1,
        maxRecvBallot: -1, clientMutex: new(sync.Mutex),
        prepareRPC: 1, prepareReplyRPC: 2, preAcceptRPC: 3,
    }
    wires := make([]*bytes.Buffer, n)
    for i := 0; i < n; i++ {
        r.InstanceSpace[i] = make([]*Instance, 8)
        r.crtInstance[i], r.CommittedUpTo[i], r.ExecedUpTo[i] = -1, -1, -1
        r.conflicts[i] = make(map[state.Key]*InstPair)
        r.PreferredPeerOrder[i] = (id + 1 + int32(i)) % n
        r.Alive[i] = int32(i) != id
        wires[i] = new(bytes.Buffer)
        r.PeerWriters[i] = bufio.NewWriter(wires[i])
    }
    return r, wires
}

func assuranceEmit(t *testing.T, e map[string]interface{}) {
    t.Helper()
    b, err := json.Marshal(e)
    if err != nil { t.Fatal(err) }
    fmt.Println("CA_EVENT " + string(b))
}

func TestAssurancePrepareValueBallotWire(t *testing.T) {
    for _, origin := range []int32{0, 1} {
        producer, output := assuranceEmptyReplica(origin)
        recovery, requests := assuranceEmptyReplica(2)
        caseID := fmt.Sprintf("origin-%d", origin)
        producer.handlePropose(&defs.GPropose{Propose: &defs.Propose{
            CommandId: 17, ClientId: 23,
            Command: state.Command{Op: state.PUT, K: 9, V: state.Value("value")},
        }})
        // Delay all preaccept traffic. Recovery is requested at an empty peer.
        // This local probe does not claim a timeout-triggered distributed prefix.
        for _, b := range output { b.Reset() }
        recovery.startRecoveryForInstance(origin, 0)
        requestBytes := requests[origin]
        code, err := requestBytes.ReadByte()
        if err != nil || code != recovery.prepareRPC { t.Fatalf("prepare framing: %v %d", err, code) }
        request := new(Prepare)
        if err := request.Unmarshal(requestBytes); err != nil { t.Fatal(err) }
        before := producer.InstanceSpace[origin][0]
        assuranceEmit(t, map[string]interface{}{
            "event": "prepare_admission", "case_id": caseID,
            "source_replica": producer.Id, "instance_replica": origin, "instance": 0,
            "source_vballot": before.vbal, "source_status": before.Status,
            "request_ballot": request.Ballot, "request": request,
        })
        producer.handlePrepare(request)
        after := producer.InstanceSpace[origin][0]
        raw := append([]byte(nil), output[2].Bytes()...)
        reader := bytes.NewReader(raw)
        code, err = reader.ReadByte()
        if err != nil || code != producer.prepareReplyRPC { t.Fatalf("reply framing: %v %d", err, code) }
        decoded := new(PrepareReply).New().(*PrepareReply)
        decodeErr := decoded.Unmarshal(reader)
        errText := ""
        if decodeErr != nil { errText = decodeErr.Error() }
        assuranceEmit(t, map[string]interface{}{
            "event": "prepare_roundtrip", "case_id": caseID,
            "source_replica": producer.Id, "instance_replica": origin, "instance": 0,
            "source_vballot": after.vbal, "decoded_vballot": decoded.VBallot,
            "source_ballot": after.bal, "source_status": after.Status,
            "source_commands": after.Cmds, "source_seq": after.Seq, "source_deps": after.Deps,
            "decoded": decoded, "decode_error": errText,
            "remaining_bytes": reader.Len(), "wire_hex": hex.EncodeToString(raw),
        })
        if decodeErr != nil { t.Fatal(decodeErr) }
    }
}
