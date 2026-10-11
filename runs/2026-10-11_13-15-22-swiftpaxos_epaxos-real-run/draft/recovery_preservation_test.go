package epaxos

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
    "github.com/imdea-software/swiftpaxos/state"
    fastrpc "github.com/imdea-software/swiftpaxos/rpc"
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
    r.exec = &Exec{r}
    r.instancesToRecover = make(chan *instanceId)
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

func assuranceCommandText(t *testing.T, cmds []state.Command) string {
    t.Helper()
    b, err := json.Marshal(cmds)
    if err != nil { t.Fatal(err) }
    return string(b)
}

func assuranceSnapshot(t *testing.T, inst *Instance) map[string]interface{} {
    t.Helper()
    if inst == nil { return map[string]interface{}{"exists": false} }
    return map[string]interface{}{
        "exists": true, "status": inst.Status, "ballot": inst.bal,
        "vballot": inst.vbal, "commands": inst.Cmds, "seq": inst.Seq, "deps": inst.Deps,
    }
}

func TestAssuranceRecoveryPreservesCommittedCommand(t *testing.T) {
    // The delayed case runs last because its actual executor remains blocked on
    // the second recovery-channel send. No receiver consumes that pending request.
    for _, delayed := range []bool{false, true} {
        caseID := "commit-delivered-control"
        if delayed { caseID = "commit-delayed" }
        nodes := make([]*Replica, 3)
        wires := make([][]*bytes.Buffer, 3)
        for i := range nodes { nodes[i], wires[i] = assuranceEmptyReplica(int32(i)) }
        clientOutputs := []*bytes.Buffer{new(bytes.Buffer), new(bytes.Buffer)}
        var heldCommit *Commit
        for slot := 0; slot < 2; slot++ {
            proposal := &defs.GPropose{Propose: &defs.Propose{
                CommandId: int32(200 + slot), ClientId: 29,
                Command: state.Command{Op: state.PUT, K: state.Key(9 + slot), V: state.Value(fmt.Sprintf("value-%d", slot))},
            }, Reply: bufio.NewWriter(clientOutputs[slot]), Mutex: new(sync.Mutex)}
            nodes[0].handlePropose(proposal)
            pre := new(PreAccept)
            assuranceRead(t, wires[0][1], nodes[0].preAcceptRPC, pre)
            nodes[1].handlePreAccept(pre)
            reply := new(PreAcceptReply)
            assuranceRead(t, wires[1][0], nodes[1].preAcceptReplyRPC, reply)
            nodes[0].handlePreAcceptReply(reply)
            for _, peer := range []int{1, 2} {
                commit := new(Commit)
                assuranceRead(t, wires[0][peer], nodes[0].commitRPC, commit)
                assuranceEmit(t, map[string]interface{}{
                    "event": "initial_commit_produced", "case_id": caseID,
                    "sender": 0, "destination": peer, "slot": slot, "commit": commit,
                    "producer": assuranceSnapshot(t, nodes[0].InstanceSpace[0][slot]),
                })
                if delayed && slot == 0 && peer == 2 {
                    // Decode in wire order, but defer this handler dispatch. The
                    // production receiver enqueues decoded messages asynchronously.
                    heldCommit = commit
                } else { nodes[peer].handleCommit(commit) }
            }
        }
        if !nodes[0].exec.executeCommand(0, 0) { t.Fatal("original execution incomplete") }
        clientReply := new(defs.ProposeReplyTS)
        if err := clientReply.Unmarshal(clientOutputs[0]); err != nil { t.Fatal(err) }
        original := nodes[0].InstanceSpace[0][0]
        sourceValue, sourcePresent := nodes[0].State.Store.Get(state.Key(9))
        assuranceEmit(t, map[string]interface{}{
            "event": "chosen_admission", "case_id": caseID,
            "instance_replica": 0, "instance": 0,
            "original_status": original.Status,
            "original_commands": assuranceCommandText(t, original.Cmds),
            "original_state_present": sourcePresent, "original_state_value": sourceValue,
            "client_reply": clientReply, "client_reply_remaining": clientOutputs[0].Len(),
            "receiver_before": assuranceSnapshot(t, nodes[2].InstanceSpace[0][0]),
            "receiver_crt": nodes[2].crtInstance[0],
            "receiver_execed": nodes[2].ExecedUpTo[0],
        })
        if delayed {
            // There is a real hole at 0.0 below the received commit at 0.1.
            // Run the actual timeout producer, with immutable handler state until
            // the first channel handoff. It next blocks sending the request for
            // 0.1 (the for-k loop at epaxos.go:408-410). crtInstance stays 1,
            // so it does not inspect or mutate protocol instances during replay.
            go nodes[2].executeCommands()
            var trigger *instanceId
            select {
            case trigger = <-nodes[2].instancesToRecover:
            case <-time.After(30 * time.Second): t.Fatal("no actual recovery trigger")
            }
            assuranceEmit(t, map[string]interface{}{
                "event": "recovery_trigger", "case_id": caseID,
                "trigger_replica": trigger.replica, "trigger_instance": trigger.instance,
                "receiver_crt": nodes[2].crtInstance[0],
            })
            if trigger.replica != 0 || trigger.instance != 0 { t.Fatal("unexpected trigger") }
            nodes[2].startRecoveryForInstance(trigger.replica, trigger.instance)
            assuranceEmit(t, map[string]interface{}{
                "event": "recovery_self_reply", "case_id": caseID,
                "self_replies": nodes[2].InstanceSpace[0][0].lb.prepareReplies,
            })
            prepare := new(Prepare)
            assuranceRead(t, wires[2][0], nodes[2].prepareRPC, prepare)
            nodes[0].handlePrepare(prepare)
            prepared := new(PrepareReply)
            assuranceRead(t, wires[0][2], nodes[0].prepareReplyRPC, prepared)
            assuranceEmit(t, map[string]interface{}{
                "event": "committed_prepare_reply", "case_id": caseID,
                "reply": prepared, "producer": assuranceSnapshot(t, nodes[0].InstanceSpace[0][0]),
            })
            nodes[2].handlePrepareReply(prepared)
            assuranceEmit(t, map[string]interface{}{
                "event": "recovery_selection", "case_id": caseID,
                "selected": assuranceSnapshot(t, nodes[2].InstanceSpace[0][0]),
            })
            pre := new(PreAccept)
            assuranceRead(t, wires[2][0], nodes[2].preAcceptRPC, pre)
            nodes[0].handlePreAccept(pre)
            preReply := new(PreAcceptReply)
            assuranceRead(t, wires[0][2], nodes[0].preAcceptReplyRPC, preReply)
            assuranceEmit(t, map[string]interface{}{
                "event": "recovery_preaccept", "case_id": caseID, "request": pre, "reply": preReply,
            })
            nodes[2].handlePreAcceptReply(preReply)
            accept := new(Accept)
            assuranceRead(t, wires[2][0], nodes[2].acceptRPC, accept)
            nodes[0].handleAccept(accept)
            accepted := new(AcceptReply)
            assuranceRead(t, wires[0][2], nodes[0].acceptReplyRPC, accepted)
            assuranceEmit(t, map[string]interface{}{
                "event": "recovery_accept", "case_id": caseID, "request": accept, "reply": accepted,
                "original": assuranceSnapshot(t, nodes[0].InstanceSpace[0][0]),
            })
            nodes[2].handleAcceptReply(accepted)
            // Deliver the previously delayed commit after the recovered decision.
            // This tests whether normal dissemination repairs the discrepancy.
            nodes[2].handleCommit(heldCommit)
        } else {
            // The same explicit invocation is a no-op when the original Commit
            // was delivered; the guard must preserve the existing command.
            nodes[2].startRecoveryForInstance(0, 0)
        }
        recovered := nodes[2].InstanceSpace[0][0]
        executionComplete := nodes[2].exec.executeCommand(0, 0)
        receiverValue, receiverPresent := nodes[2].State.Store.Get(state.Key(9))
        assuranceEmit(t, map[string]interface{}{
            "event": "recovery_endpoint", "case_id": caseID,
            "instance_replica": 0, "instance": 0,
            "receiver_status": recovered.Status, "execution_complete": executionComplete,
            "receiver_commands": assuranceCommandText(t, recovered.Cmds),
            "receiver_state_present": receiverPresent, "receiver_state_value": receiverValue,
            "receiver": assuranceSnapshot(t, recovered),
            "original": assuranceSnapshot(t, nodes[0].InstanceSpace[0][0]),
            "delayed_commit": heldCommit,
        })
    }
}
