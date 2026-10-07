package raft

import (
    "encoding/json"
    "fmt"
    "reflect"
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
    configIndex uint64
    cycleTracking, cycleOnlyHeartbeats, cycleRolesStable bool
}

func (e *assuranceTransferEnv) emit(phase string) {
    r := e.nodes[0].raft
    out := map[string]interface{}{
        "event": phase, "operation_id":"remove-node3-implicit-1", "scenario":"failed_transfer_idle", "config_index":e.configIndex, "phase": phase, "tick": e.tick, "triggered": e.triggered,
        "term": r.Term, "role": r.state.String(), "leader": r.lead,
        "transferee": r.leadTransferee, "last": r.raftLog.lastIndex(),
        "commit": r.raftLog.committed, "applied": r.raftLog.applied,
        "pending_conf": r.pendingConfIndex, "config": r.trk.ConfState(),
        "queue": len(e.queue), "drained":e.drained(), "all_applied_config":e.allAppliedConfig(), "dropped_timeout_now": e.dropped,
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
                e.configIndex = ent.Index
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
            if e.cycleTracking && m.Type != pb.MsgHeartbeat && m.Type != pb.MsgHeartbeatResp { e.cycleOnlyHeartbeats = false }
            e.queue = e.queue[1:]
            if e.dropTimeout && m.Type == pb.MsgTimeoutNow {
                e.dropped++
            } else {
                if m.To < 1 || m.To > uint64(len(e.nodes)) { e.t.Fatalf("unknown destination %d", m.To) }
                err := e.nodes[m.To-1].Step(m)
                if err != nil && err != ErrStepPeerNotFound { e.t.Fatal(err) }
                e.delivered++
                e.recordRoles()
            }
            changed = true
        }
        if !changed { return }
    }
    e.t.Fatal("driver work bound reached before queues drained")
}

func TestAssuranceTransferAutoLeaveCycle(t *testing.T) {
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
    e.emit("admitted")
    var cycleStart string
    var readyStart, deliveredStart, applyStart int
    for e.tick < 30 {
        e.tick++
        for _, n := range e.nodes { n.Tick(); e.recordRoles() }
        e.pump()
        if e.tick == 10 {
            // The bounded loss period ends. All later traffic is delivered.
            e.dropTimeout = false
            e.emit("transfer_timeout")
        }
        if e.tick == 20 {
            e.cycleTracking = true
            e.cycleOnlyHeartbeats = true
            e.cycleRolesStable = true
            readyStart, deliveredStart, applyStart = e.readies, e.delivered, e.applyBatches
            cycleStart = e.snapshot()
            e.output(map[string]interface{}{"event":"cycle_start", "snapshot":cycleStart, "tick":e.tick})
        }
        if e.tick == 30 {
            finish := e.snapshot()
            drained := e.drained()
            r := e.nodes[0].raft
            equal := cycleStart == finish
            pending := r.trk.AutoLeave && len(r.trk.Voters[1]) > 0
            unchangedTail := r.raftLog.lastIndex() == e.configIndex && r.raftLog.committed == e.configIndex && r.raftLog.applied == e.configIndex
            closed := equal && drained && e.cycleOnlyHeartbeats && e.cycleRolesStable && e.applyBatches == applyStart
            e.output(map[string]interface{}{
                "event":"cycle_result", "tick":e.tick, "snapshot":finish,
                "same_state":equal, "drained":drained,
                "only_heartbeats":e.cycleOnlyHeartbeats, "roles_stable":e.cycleRolesStable,
                "ready_delta":e.readies-readyStart, "message_delta":e.delivered-deliveredStart,
                "apply_delta":e.applyBatches-applyStart, "joint_pending":pending,
                "unchanged_tail":unchangedTail, "transferee":r.leadTransferee,
                "forbidden_idle_cycle":closed && pending && unchangedTail && r.leadTransferee == 0,
            })
            e.cycleTracking = false
        }
    }
    // Separate rescue phase: ordinary client work is an additional stimulus,
    // not silently included in the automatic-continuation observation.
    if err := e.nodes[0].Propose([]byte("rescue")); err != nil { t.Fatal(err) }
    e.pump()
    e.emit("after_unrelated_proposal")
}


// A read-only structural projection, not a hash or an expected-state template.
// All target fields are retained except diagnostic loggers/call counters and
// the MemoryStorage mutex, which is unlocked throughout this serialized model.
// Function code identities are retained; their bound raft receivers are also
// recursively captured. No protocol field is written by this observer.
func assuranceProjection(v reflect.Value) interface{} {
    if !v.IsValid() { return nil }
    switch v.Kind() {
    case reflect.Pointer, reflect.Interface:
        if v.IsNil() { return nil }
        return map[string]interface{}{"type":v.Type().String(),"value":assuranceProjection(v.Elem())}
    case reflect.Struct:
        out := map[string]interface{}{}
        for i:=0; i<v.NumField(); i++ {
            name := v.Type().Field(i).Name
            typ := v.Type().String()
            if (typ == "raft.raft" && (name == "logger" || name == "traceLogger")) ||
               ((typ == "raft.raftLog" || typ == "raft.unstable") && name == "logger") ||
               (typ == "raft.MemoryStorage" && (name == "Mutex" || name == "callStats")) { continue }
            out[name] = assuranceProjection(v.Field(i))
        }
        return out
    case reflect.Slice, reflect.Array:
        if v.Kind() == reflect.Slice && v.IsNil() { return nil }
        out := make([]interface{}, v.Len())
        for i:=range out { out[i]=assuranceProjection(v.Index(i)) }
        return out
    case reflect.Map:
        if v.IsNil() { return nil }
        out := map[string]interface{}{}
        for _, key := range v.MapKeys() {
            b, err := json.Marshal(assuranceProjection(key)); if err != nil { panic(err) }
            out[string(b)] = assuranceProjection(v.MapIndex(key))
        }
        return out
    case reflect.Bool: return v.Bool()
    case reflect.String: return v.String()
    case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64: return v.Int()
    case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64, reflect.Uintptr: return v.Uint()
    case reflect.Func:
        if v.IsNil() { return nil }; return v.Pointer()
    default: panic("unhandled snapshot kind: " + v.Kind().String())
    }
}

func (e *assuranceTransferEnv) recordRoles() {
    if !e.cycleTracking { return }
    for i,n := range e.nodes {
        want := StateFollower; if i == 0 { want = StateLeader }
        if n.raft.Term != 2 || n.raft.state != want || n.raft.lead != 1 { e.cycleRolesStable = false }
    }
}

func (e *assuranceTransferEnv) drained() bool {
    if len(e.queue) != 0 { return false }
    for _, n := range e.nodes {
        r := n.raft
        if n.HasReady() || len(n.stepsOnAdvance) != 0 || len(r.msgs) != 0 || len(r.msgsAfterAppend) != 0 ||
           r.raftLog.hasNextOrInProgressUnstableEnts() || r.raftLog.hasNextOrInProgressSnapshot() ||
           r.raftLog.applied != r.raftLog.committed || r.raftLog.applying != r.raftLog.applied { return false }
    }
    return true
}

func (e *assuranceTransferEnv) snapshot() string {
    state := map[string]interface{}{
        "nodes":assuranceProjection(reflect.ValueOf(e.nodes)),
        "queue":assuranceProjection(reflect.ValueOf(e.queue)),
        "policy":map[string]interface{}{"armed":e.armed,"triggered":e.triggered,"drop_timeout":e.dropTimeout,
            "schedule_phase":e.tick%10,"config_index":e.configIndex},
    }
    b,err:=json.Marshal(state); if err!=nil { e.t.Fatal(err) }; return string(b)
}

func (e *assuranceTransferEnv) output(m map[string]interface{}) {
    m["operation_id"]="remove-node3-implicit-1"
    m["scenario"]="failed_transfer_idle"
    m["config_index"]=e.configIndex
    b,err:=json.Marshal(m); if err!=nil { e.t.Fatal(err) }
    fmt.Println("CA_EVENT " + string(b))
}

func (e *assuranceTransferEnv) allAppliedConfig() bool {
    if e.configIndex == 0 { return false }
    for _, n := range e.nodes {
        if n.raft.raftLog.applied != e.configIndex || n.raft.raftLog.committed != e.configIndex { return false }
    }
    return true
}
