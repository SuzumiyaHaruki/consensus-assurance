package epaxos

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
    "github.com/imdea-software/swiftpaxos/state"
    fastrpc "github.com/imdea-software/swiftpaxos/rpc"
)

// Initialize the empty, non-durable handler state of New without starting its
// network listeners, clocks or workers. No instance or leader state is supplied.
// Only instance capacity and transport are reduced; all protocol mutations below
// are made by production proposal, recovery and prepare handlers.
func assuranceEmptyReplica(id int32) (*Replica, []*bytes.Buffer) {
    const n = 5
    base := &replica.Replica{
        Logger: dlog.New("", false), N: n, F: 2, Id: id,
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
        preAcceptReplyRPC: 4, acceptRPC: 5, acceptReplyRPC: 6, commitRPC: 7,
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

func assuranceRead(t *testing.T, wire *bytes.Buffer, code byte, msg fastrpc.Serializable) {
    t.Helper()
    got, err := wire.ReadByte()
    if err != nil || got != code { t.Fatalf("wire code: got %d, want %d, err %v", got, code, err) }
    if err := msg.Unmarshal(wire); err != nil { t.Fatal(err) }
}

func assurancePropose(r *Replica, id int32, value string) {
    r.handlePropose(&defs.GPropose{Propose: &defs.Propose{
        CommandId: id, ClientId: 23,
        Command: state.Command{Op: state.PUT, K: 9, V: state.Value(value)},
    }})
}

func TestAssuranceAcceptRetainsPhase(t *testing.T) {
    nodes := make([]*Replica, 5)
    wires := make([][]*bytes.Buffer, 5)
    for i := range nodes { nodes[i], wires[i] = assuranceEmptyReplica(int32(i)) }
    // A real conflicting proposal at peer 1 changes A's dependency attributes.
    // Its outbound traffic remains delayed throughout this local probe.
    assurancePropose(nodes[1], 100, "B")
    delayedB := make(map[int][]byte)
    for _, peer := range []int{2, 3} {
        delayedB[peer] = append([]byte(nil), wires[1][peer].Bytes()...)
        wires[1][peer].Reset()
    }
    assuranceEmit(t, map[string]interface{}{"event": "delayed_conflicting_traffic", "from": 1, "wire_bytes_by_peer": delayedB})
    assurancePropose(nodes[0], 101, "A")
    for _, peer := range []int{1, 2} {
        pre := new(PreAccept)
        assuranceRead(t, wires[0][peer], nodes[0].preAcceptRPC, pre)
        nodes[peer].handlePreAccept(pre)
        reply := new(PreAcceptReply)
        assuranceRead(t, wires[peer][0], nodes[peer].preAcceptReplyRPC, reply)
        assuranceEmit(t, map[string]interface{}{
            "event": "slow_prefix", "peer": peer, "reply": reply,
            "leader_before_status": nodes[0].InstanceSpace[0][0].Status,
        })
        nodes[0].handlePreAcceptReply(reply)
    }
    leader := nodes[0].InstanceSpace[0][0]
    assuranceEmit(t, map[string]interface{}{
        "event": "slow_accept_produced", "leader_status": leader.Status,
        "leader_ballot": leader.bal, "leader_vballot": leader.vbal,
        "leader_seq": leader.Seq, "leader_deps": leader.Deps,
        "slow_count": nodes[0].Stats.M["slow"],
    })
    if leader.Status != ACCEPTED { t.Fatal("prefix did not enter slow accept") }
    for _, peer := range []int{1, 2} {
        accept := new(Accept)
        assuranceRead(t, wires[0][peer], nodes[0].acceptRPC, accept)
        inst := nodes[peer].InstanceSpace[0][0]
        caseID := fmt.Sprintf("acceptor-%d", peer)
        assuranceEmit(t, map[string]interface{}{
            "event": "accept_admission", "case_id": caseID, "acceptor": peer,
            "instance_replica": accept.Replica, "instance": accept.Instance,
            "accept": accept, "before_status": inst.Status,
            "before_ballot": inst.bal, "before_vballot": inst.vbal,
        })
        nodes[peer].handleAccept(accept)
        ack := new(AcceptReply)
        assuranceRead(t, wires[peer][0], nodes[peer].acceptReplyRPC, ack)
        assuranceEmit(t, map[string]interface{}{
            "event": "accept_completion", "case_id": caseID, "acceptor": peer,
            "instance_replica": accept.Replica, "instance": accept.Instance,
            "accept_ballot": accept.Ballot, "ack_ballot": ack.Ballot,
            "after_status": inst.Status, "expected_accepted_status": ACCEPTED,
            "after_ballot": inst.bal, "after_vballot": inst.vbal,
            "after_seq": inst.Seq, "after_deps": inst.Deps,
        })
        // A fresh recovering peer constructs the Prepare request; no recovery
        // selection is performed in this local phase-retention probe.
        recovery, recoveryWires := assuranceEmptyReplica(3)
        recovery.startRecoveryForInstance(0, 0)
        prepare := new(Prepare)
        assuranceRead(t, recoveryWires[peer], recovery.prepareRPC, prepare)
        nodes[peer].handlePrepare(prepare)
        prepared := new(PrepareReply)
        assuranceRead(t, wires[peer][3], nodes[peer].prepareReplyRPC, prepared)
        assuranceEmit(t, map[string]interface{}{
            "event": "accepted_prepare_report", "case_id": caseID, "acceptor": peer,
            "instance_replica": accept.Replica, "instance": accept.Instance,
            "reported_status": prepared.Status, "expected_accepted_status": ACCEPTED,
            "prepare": prepare, "reply": prepared,
        })
    }
}
