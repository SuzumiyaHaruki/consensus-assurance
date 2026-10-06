package raft

import (
 "encoding/json"
 "fmt"
 "reflect"
 "runtime"
 "sort"
 "testing"

 pb "go.etcd.io/raft/v3/raftpb"
)

// The single test goroutine owns all nodes, storage, queues and observations.
// No protocol fields are modified by this driver.
func TestAssuranceJointExitTransferCycle(t *testing.T) {
 for _, transfer := range []bool{false, true} {
  name := "control"
  if transfer { name = "transfer" }
  t.Run(name, func(t *testing.T) {
   nodes := map[uint64]*RawNode{}
   stores := map[uint64]*MemoryStorage{}
   applied := map[uint64]uint64{}
   var queue []pb.Message
   triggered := false
   dropTimeout := transfer
   dropped, delivered, readyBatches := 0, 0, 0
   var jointIndex uint64
   inCycle, pendingContinuously := false, true
   var cycleTerm, cycleLast uint64
   var cycleStart string
   observe := func() {
    if !inCycle { return }
    r := nodes[1].raft
    pendingContinuously = pendingContinuously && r.state == StateLeader && r.Term == cycleTerm && r.trk.Config.AutoLeave && len(r.trk.Config.Voters[1]) > 0 && r.raftLog.lastIndex() == cycleLast
   }
   stateText := func() string {
    // Include the complete recursively reachable RawNode/raft/storage value,
    // driver application cursors and all in-flight network work. No hash.
    state := map[string]interface{}{
     "nodes": assuranceValue(reflect.ValueOf(nodes)),
     "application_cursors": assuranceValue(reflect.ValueOf(applied)),
     "network_queue": assuranceValue(reflect.ValueOf(queue)),
     "drop_timeout_now": dropTimeout, "triggered": triggered,
     "scheduler_phase": "before-next-ten-ticks",
    }
    b, err := json.Marshal(state)
    if err != nil { t.Fatal(err) }
    return string(b)
   }
   emit := func(phase string) {
    r := nodes[1].raft
    b, err := json.Marshal(map[string]interface{}{
     "event": phase, "scenario": name, "with_transfer": transfer, "operation": "implicit-remove-3", "phase": phase, "node": uint64(1), "joint_index": jointIndex,
     "term": r.Term, "role": r.state.String(), "lead": r.lead,
     "transfer_target": r.leadTransferee, "auto_leave": r.trk.Config.AutoLeave,
     "configuration": r.trk.ConfState(), "last": r.raftLog.lastIndex(),
     "committed": r.raftLog.committed, "applied": r.raftLog.applied,
     "pending_conf": r.pendingConfIndex,
     "application_done": applied[1] >= jointIndex && r.raftLog.applied >= jointIndex,
     "ready_pending": nodes[1].HasReady(),
     "pending_continuously": pendingContinuously,
     "cycle_state": stateText(), "queued": len(queue),
     "dropped_timeout_now": dropped, "delivered": delivered, "ready_batches": readyBatches,
    })
    if err != nil { t.Fatal(err) }
    fmt.Println("CA_EVENT " + string(b))
   }
   for id := uint64(1); id <= 3; id++ {
    s := NewMemoryStorage()
    rn, err := NewRawNode(&Config{ID:id, ElectionTick:10, HeartbeatTick:1, Storage:s, MaxSizePerMsg:1<<20, MaxInflightMsgs:256, CheckQuorum:true})
    if err != nil { t.Fatal(err) }
    if err := rn.Bootstrap([]Peer{{ID:1},{ID:2},{ID:3}}); err != nil { t.Fatal(err) }
    nodes[id], stores[id] = rn, s
   }
   pump := func() {
    for iteration := 0; iteration < 10000; iteration++ {
     work := false
     for id := uint64(1); id <= 3; id++ {
      rn, s := nodes[id], stores[id]
      if !rn.HasReady() { continue }
      work = true
      readyBatches++
      rd := rn.Ready()
      if !IsEmptySnap(rd.Snapshot) { t.Fatal("unexpected snapshot in uncompacted test") }
      if err := s.Append(rd.Entries); err != nil { t.Fatal(err) }
      if !IsEmptyHardState(rd.HardState) {
       if err := s.SetHardState(rd.HardState); err != nil { t.Fatal(err) }
      }
      // Persistence precedes sending every message, including responses.
      queue = append(queue, rd.Messages...)
      for _, e := range rd.CommittedEntries {
       if e.Index != applied[id]+1 { t.Fatalf("node %d nonconsecutive apply %d after %d", id, e.Index, applied[id]) }
       switch e.Type {
       case pb.EntryConfChange:
        var cc pb.ConfChange
        if err := cc.Unmarshal(e.Data); err != nil { t.Fatal(err) }
        rn.ApplyConfChange(cc)
        observe()
       case pb.EntryConfChangeV2:
        var cc pb.ConfChangeV2
        if err := cc.Unmarshal(e.Data); err != nil { t.Fatal(err) }
        rn.ApplyConfChange(cc)
        observe()
        if id == 1 && cc.Transition == pb.ConfChangeTransitionJointImplicit && !triggered {
         triggered = true
         jointIndex = e.Index
         if transfer { rn.TransferLeader(2) }
         emit("joint_applied_before_advance")
        }
       }
       applied[id] = e.Index
      }
      rn.Advance(rd)
      observe()
     }
     if len(queue) != 0 {
      work = true
      m := queue[0]
      queue = queue[1:]
      if dropTimeout && m.Type == pb.MsgTimeoutNow {
       dropped++
       fmt.Printf("CA_EVENT {\"event\":\"network_drop\",\"scenario\":%q,\"from\":%d,\"to\":%d,\"message_type\":%q,\"term\":%d}\n", name, m.From, m.To, m.Type.String(), m.Term)
      } else {
       delivered++
       fmt.Printf("CA_EVENT {\"event\":\"network_delivery\",\"scenario\":%q,\"sequence\":%d,\"from\":%d,\"to\":%d,\"message_type\":%q,\"term\":%d,\"index\":%d,\"commit\":%d,\"entry_count\":%d}\n", name, delivered, m.From, m.To, m.Type.String(), m.Term, m.Index, m.Commit, len(m.Entries))
       err := nodes[m.To].Step(m)
       observe()
       // Late responses from a removed member are ordinary network inputs.
       if err != nil && err != ErrStepPeerNotFound { t.Fatal(err) }
      }
     }
     if !work { return }
    }
    t.Fatal("pump did not quiesce within construction bound")
   }
   pump()
   if err := nodes[1].Campaign(); err != nil { t.Fatal(err) }
   pump()
   if nodes[1].raft.state != StateLeader { t.Fatal("leader prerequisite not reached") }
   emit("elected")
   cc := pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit, Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode, NodeID:3}}}
   if err := nodes[1].ProposeConfChange(cc); err != nil { t.Fatal(err) }
   pump()
   if !triggered { t.Fatal("joint entry not applied") }
   emit("after_joint_completion")
   // No further network losses after the original TimeoutNow messages drain.
   dropTimeout = false
   for tick := 1; tick <= 20; tick++ {
    for id := uint64(1); id <= 3; id++ { nodes[id].Tick(); observe() }
    pump()
    if tick == 10 {
     r := nodes[1].raft
     cycleTerm, cycleLast = r.Term, r.raftLog.lastIndex()
     inCycle = true
     observe()
     cycleStart = stateText()
     emit("cycle_start")
    }
    if tick == 20 {
     emit("cycle_result")
     fmt.Printf("CA_EVENT {\"event\":\"cycle_diagnostic\",\"scenario\":%q,\"state_repeated\":%t}\n", name, stateText() == cycleStart)
     inCycle = false
    }
   }
   // A separately labelled diagnostic stimulus tests the later-entry retry path.
   if err := nodes[1].Propose([]byte("diagnostic-rescue")); err != nil { t.Fatal(err) }
   pump()
   emit("after_rescue_entry")
  })
 }
}

// Canonical value traversal retains unexported state without unsafe access or
// modifying the implementation. Only non-protocol observational state is omitted.
func assuranceValue(v reflect.Value) interface{} {
 if !v.IsValid() { return nil }
 switch v.Kind() {
 case reflect.Pointer, reflect.Interface:
  if v.IsNil() { return nil }
  return assuranceValue(v.Elem())
 case reflect.Bool: return v.Bool()
 case reflect.String: return v.String()
 case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64: return v.Int()
 case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64, reflect.Uintptr: return v.Uint()
 case reflect.Struct:
  out := map[string]interface{}{}
  typ := v.Type()
  for i:=0; i<v.NumField(); i++ {
   field := typ.Field(i).Name
   // Loggers do not make protocol decisions. TraceLogger is nil in this test.
   if (typ.Name()=="raft" || typ.Name()=="raftLog" || typ.Name()=="unstable") && (field=="logger" || field=="traceLogger") { continue }
   // The driver is single-threaded and all storage operations have returned.
   // callStats is increment-only diagnostic accounting, never read by Raft.
   if typ.Name()=="MemoryStorage" && (field=="Mutex" || field=="callStats") { continue }
   out[field] = assuranceValue(v.Field(i))
  }
  return out
 case reflect.Slice, reflect.Array:
  if v.Kind()==reflect.Slice && v.IsNil() { return nil }
  out:=make([]interface{},v.Len())
  for i:=0; i<v.Len(); i++ { out[i]=assuranceValue(v.Index(i)) }
  return out
 case reflect.Map:
  if v.IsNil() { return nil }
  out:=map[string]interface{}{}
  keys:=v.MapKeys()
  sort.Slice(keys,func(i,j int) bool { a,_:=json.Marshal(assuranceValue(keys[i])); b,_:=json.Marshal(assuranceValue(keys[j])); return string(a)<string(b) })
  for _,k:=range keys { b,_:=json.Marshal(assuranceValue(k)); out[string(b)]=assuranceValue(v.MapIndex(k)) }
  return out
 case reflect.Func:
  if v.IsNil() { return nil }
  // The only functions reachable here are fixed raft role handlers. Their
  // receiver bindings stay attached to the same nodes throughout the cycle.
  return runtime.FuncForPC(v.Pointer()).Name()
 default: panic(fmt.Sprintf("unsupported state kind %s in %s",v.Kind(),v.Type()))
 }
}
