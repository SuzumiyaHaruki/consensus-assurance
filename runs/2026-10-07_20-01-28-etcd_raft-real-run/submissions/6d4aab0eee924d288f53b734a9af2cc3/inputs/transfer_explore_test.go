package raft

import (
    "encoding/json"
    "fmt"
    "testing"

    pb "go.etcd.io/raft/v3/raftpb"
)

// This driver uses only actual RawNode output as peer traffic. All calls are
// serialized; persistence, configuration application and Advance finish each
// Ready before accepting another Ready from that node.
type assuranceTransferEnv struct {
    t *testing.T
    nodes []*RawNode
    stores []*MemoryStorage
    queue []pb.Message
    armed, triggered, dropTimeout bool
    dropped, delivered, readies, applyBatches int
    tick int
}

func (e *assuranceTransferEnv) emit(phase string) {
    r := e.nodes[0].raft
    out := map[string]interface{}{
        "phase": phase, "tick": e.tick, "triggered": e.triggered,
        "term": r.Term, "role": r.state.String(), "leader": r.lead,
        "transferee": r.leadTransferee, "last": r.raftLog.lastIndex(),
        "commit": r.raftLog.committed, "applied": r.raftLog.applied,
        "pending_conf": r.pendingConfIndex, "config": r.trk.ConfState(),
        "queue": len(e.queue), "dropped_timeout_now": e.dropped,
        "delivered": e.delivered, "readies": e.readies,
        "apply_batches": e.applyBatches,
    }
    b, err := json.Marshal(out)
    if err != nil { e.t.Fatal(err) }
    fmt.Println("CA_EVENT " + string(b))
}

func (e *assuranceTransferEnv) ready(i int) bool {
    n, s := e.nodes[i], e.stores[i]
    if !n.HasReady() { return false }
    rd := n.Ready()
    e.readies++
    if !IsEmptySnap(rd.Snapshot) {
        if err := s.ApplySnapshot(rd.Snapshot); err != nil { e.t.Fatal(err) }
    }
    if err := s.Append(rd.Entries); err != nil { e.t.Fatal(err) }
    if !IsEmptyHardState(rd.HardState) {
        if err := s.SetHardState(rd.HardState); err != nil { e.t.Fatal(err) }
    }
    if len(rd.CommittedEntries) > 0 { e.applyBatches++ }
    for _, ent := range rd.CommittedEntries {
        switch ent.Type {
        case pb.EntryConfChange:
            var cc pb.ConfChange
            if err := cc.Unmarshal(ent.Data); err != nil { e.t.Fatal(err) }
            n.ApplyConfChange(cc)
        case pb.EntryConfChangeV2:
            var cc pb.ConfChangeV2
            if err := cc.Unmarshal(ent.Data); err != nil { e.t.Fatal(err) }
            n.ApplyConfChange(cc)
            if i == 0 && e.armed && !e.triggered && string(cc.Context) == "enter" {
                // Configuration is genuinely committed and applied. Transfer
                // interleaves before the caller acknowledges this Ready.
                e.triggered = true
                n.TransferLeader(2)
                if n.raft.leadTransferee != 2 { e.t.Fatal("transfer not admitted") }
                e.emit("transfer_before_application_ack")
            }
        }
    }
    // Storage is complete before releasing any peer message from this Ready.
    e.queue = append(e.queue, rd.Messages...)
    n.Advance(rd)
    return true
}

func (e *assuranceTransferEnv) pump() {
    for work := 0; work < 20000; work++ {
        changed := false
        for i := range e.nodes { if e.ready(i) { changed = true } }
        if len(e.queue) > 0 {
            m := e.queue[0]
            e.queue = e.queue[1:]
            if e.dropTimeout && m.Type == pb.MsgTimeoutNow {
                e.dropped++
            } else {
                if m.To < 1 || m.To > uint64(len(e.nodes)) { e.t.Fatalf("unknown destination %d", m.To) }
                err := e.nodes[m.To-1].Step(m)
                if err != nil && err != ErrStepPeerNotFound { e.t.Fatal(err) }
                e.delivered++
            }
            changed = true
        }
        if !changed { return }
    }
    e.t.Fatal("driver work bound reached before queues drained")
}

func TestAssuranceTransferAutoLeaveExplore(t *testing.T) {
    e := &assuranceTransferEnv{t:t, dropTimeout:true}
    peers := []Peer{{ID:1}, {ID:2}, {ID:3}}
    for id := uint64(1); id <= 3; id++ {
        s := NewMemoryStorage()
        n, err := NewRawNode(&Config{ID:id, ElectionTick:10, HeartbeatTick:1,
            Storage:s, MaxSizePerMsg:4096, MaxInflightMsgs:16, CheckQuorum:true})
        if err != nil { t.Fatal(err) }
        if err := n.Bootstrap(peers); err != nil { t.Fatal(err) }
        e.nodes = append(e.nodes,n)
        e.stores = append(e.stores,s)
    }
    e.pump()
    if err := e.nodes[0].Campaign(); err != nil { t.Fatal(err) }
    e.pump()
    if e.nodes[0].raft.state != StateLeader { t.Fatal("campaign did not elect node 1") }
    e.emit("elected_and_drained")
    e.armed = true
    cc := pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,
        Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}, Context:[]byte("enter")}
    if err := e.nodes[0].ProposeConfChange(cc); err != nil { t.Fatal(err) }
    e.pump()
    if !e.triggered || e.dropped == 0 { t.Fatal("overlap or transport fault not reached") }
    e.emit("application_acknowledged_and_drained")
    for e.tick < 30 {
        e.tick++
        for _, n := range e.nodes { n.Tick() }
        e.pump()
        if e.tick == 10 {
            // The bounded loss period ends. All later traffic is delivered.
            e.dropTimeout = false
            e.emit("transfer_timeout")
        }
        if e.tick == 20 || e.tick == 30 { e.emit("idle_after_timeout") }
    }
    // Separate rescue phase: ordinary client work is an additional stimulus,
    // not silently included in the automatic-continuation observation.
    if err := e.nodes[0].Propose([]byte("rescue")); err != nil { t.Fatal(err) }
    e.pump()
    e.emit("after_unrelated_proposal")
}
