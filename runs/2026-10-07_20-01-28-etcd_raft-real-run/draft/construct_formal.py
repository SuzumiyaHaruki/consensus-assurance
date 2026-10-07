from pathlib import Path
p=Path('transfer_explore_test.go').read_text()
p=p.replace('"fmt"','"fmt"\n    "reflect"')
p=p.replace('tick int','tick int\n    configIndex uint64\n    cycleTracking, cycleOnlyHeartbeats, cycleRolesStable bool')
p=p.replace('"phase": phase,', '"event": phase, "operation_id":"remove-node3-implicit-1", "scenario":"failed_transfer_idle", "config_index":e.configIndex, "phase": phase,')
p=p.replace('e.triggered = true','e.triggered = true\n                e.configIndex = ent.Index')
p=p.replace('m := e.queue[0]','m := e.queue[0]\n            if e.cycleTracking && m.Type != pb.MsgHeartbeat && m.Type != pb.MsgHeartbeatResp { e.cycleOnlyHeartbeats = false }')
p=p.replace('e.delivered++','e.delivered++\n                e.recordRoles()')
p=p.replace('e.emit("application_acknowledged_and_drained")','e.emit("admitted")')
p=p.replace('func TestAssuranceTransferAutoLeaveExplore', 'func TestAssuranceTransferAutoLeaveCycle')
p=p.replace('for e.tick < 30 {','var cycleStart string\n    var readyStart, deliveredStart, applyStart int\n    for e.tick < 30 {')
p=p.replace('for _, n := range e.nodes { n.Tick() }','for _, n := range e.nodes { n.Tick(); e.recordRoles() }')
p=p.replace('if e.tick == 20 || e.tick == 30 { e.emit("idle_after_timeout") }','''if e.tick == 20 {
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
        }''')
p += r'''

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
'''
Path('transfer_formal_test.go').write_text(p)
