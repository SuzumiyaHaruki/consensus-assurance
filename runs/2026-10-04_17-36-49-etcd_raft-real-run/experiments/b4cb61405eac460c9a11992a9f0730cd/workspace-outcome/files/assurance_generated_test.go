package raft

import (
 "encoding/json"
 "fmt"
 "reflect"
 "testing"

 pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssuranceJointExitContinuation(t *testing.T) {
 for _, overlap := range []bool{false, true} {
  t.Run(fmt.Sprintf("overlap_%v", overlap), func(t *testing.T) {
   nodes := map[uint64]*RawNode{}
   stores := map[uint64]*MemoryStorage{}
   ids := []uint64{1,2,3}
   var configIndex uint64
   inCycle := false
   cycleMessagesOnlyHeartbeats := true
   emit := func(phase string, fields map[string]interface{}) {
    fields["phase"] = phase
    fields["event"] = phase
    fields["case_id"] = fmt.Sprintf("implicit-remove3-overlap-%v", overlap)
    fields["config_index"] = configIndex
    fields["overlap"] = overlap
    data, err := json.Marshal(fields)
    if err != nil { t.Fatal(err) }
    fmt.Println("CA_EVENT " + string(data))
   }
   must := func(err error) { if err != nil { t.Fatal(err) } }
   // An agreed initial snapshot is the explicit starting state. MemoryStorage
   // substitutes completed durable writes; this exploration includes no crash.
   for _, id := range ids {
    s := NewMemoryStorage()
    must(s.ApplySnapshot(pb.Snapshot{Metadata: pb.SnapshotMetadata{
     Index:1, Term:1, ConfState:pb.ConfState{Voters:[]uint64{1,2,3}},
    }}))
    must(s.SetHardState(pb.HardState{Term:1, Commit:1}))
    rn, err := NewRawNode(&Config{ID:id, Storage:s, Applied:1,
     ElectionTick:10, HeartbeatTick:1, MaxSizePerMsg:4096,
     MaxInflightMsgs:256, CheckQuorum:true, PreVote:true})
    must(err)
    nodes[id], stores[id] = rn, s
   }
   // RawNode owns no goroutine and has no Stop method. All calls below are
   // serialized; all Ready batches complete before another batch is accepted.
   var queue []pb.Message
   var transferStarted bool
   var timeoutDrops int
   var appliedConfigs int
   var readyCount, messageCount int
   observe := func(phase string) {
    states := []map[string]interface{}{}
    for _, id := range ids {
     rn := nodes[id]; r := rn.raft
     states = append(states,map[string]interface{}{
      "id":id,"term":r.Term,"role":r.state.String(),"lead":r.lead,
      "commit":r.raftLog.committed,"applied":r.raftLog.applied,
      "applying":r.raftLog.applying,"last":r.raftLog.lastIndex(),
      "auto_leave":r.trk.AutoLeave,"conf":r.trk.ConfState(),
      "transfer":r.leadTransferee,"pending_conf":r.pendingConfIndex,
      "election_elapsed":r.electionElapsed,"heartbeat_elapsed":r.heartbeatElapsed,
      "has_ready":rn.HasReady(),"unstable_count":len(r.raftLog.unstable.entries),
      "steps_on_advance":len(rn.stepsOnAdvance),"msgs":len(r.msgs),
      "msgs_after_append":len(r.msgsAfterAppend),
     })
    }
    emit(phase,map[string]interface{}{"states":states,"queue":len(queue),
     "timeout_drops":timeoutDrops,"config_index":configIndex,
     "applied_configs":appliedConfigs,"ready_count":readyCount,"message_count":messageCount})
   }
   pump := func() {
    for iteration:=0;iteration<10000;iteration++ {
     work:=false
     for _, id:=range ids {
      rn:=nodes[id]
      if !rn.HasReady() { continue }
      work=true;readyCount++
      rd:=rn.Ready()
      if !IsEmptySnap(rd.Snapshot) { must(stores[id].ApplySnapshot(rd.Snapshot)) }
      must(stores[id].Append(rd.Entries))
      if !IsEmptyHardState(rd.HardState) { must(stores[id].SetHardState(rd.HardState)) }
      // Persist before making any messages deliverable.
      queue=append(queue,rd.Messages...)
      for _, ent:=range rd.CommittedEntries {
       if ent.Type==pb.EntryConfChangeV2 {
        var cc pb.ConfChangeV2
        must(cc.Unmarshal(ent.Data))
        if len(cc.Changes)>0 && id==1 {
         configIndex=ent.Index
         if overlap {
          if transferStarted { t.Fatal("second initial joint application") }
          if rn.raft.state!=StateLeader || rn.raft.trk.Progress[2].Match!=rn.raft.raftLog.lastIndex() {
           t.Fatal("transfer prerequisite not reached: target must be caught up")
          }
          transferStarted=true
          rn.TransferLeader(2)
          emit("transfer_started",map[string]interface{}{"term":rn.raft.Term,
           "index":ent.Index,"target_match":rn.raft.trk.Progress[2].Match,
           "transfer":rn.raft.leadTransferee})
         }
        }
        cs:=rn.ApplyConfChange(cc)
        appliedConfigs++
        emit("configuration_applied",map[string]interface{}{"node":id,"index":ent.Index,
         "term":ent.Term,"leave_joint":cc.LeaveJoint(),"conf":cs})
       }
      }
      rn.Advance(rd)
     }
     if len(queue)>0 {
      work=true
      m:=queue[0];queue=queue[1:];messageCount++
      if inCycle && m.Type!=pb.MsgHeartbeat && m.Type!=pb.MsgHeartbeatResp { cycleMessagesOnlyHeartbeats=false }
      // A single network loss. Every subsequent emitted message is delivered.
      if overlap && m.Type==pb.MsgTimeoutNow && timeoutDrops==0 {
       timeoutDrops++
       emit("network_drop",map[string]interface{}{"type":m.Type.String(),"from":m.From,"to":m.To,"term":m.Term})
      } else {
       dst:=nodes[m.To]
       if dst==nil { t.Fatalf("unexpected destination %d",m.To) }
       err:=dst.Step(m)
       if err!=nil && err!=ErrStepPeerNotFound { t.Fatal(err) }
      }
     }
     if !work { return }
    }
    t.Fatal("pump did not drain within diagnostic bound")
   }
   must(nodes[1].Campaign());pump()
   if nodes[1].raft.state!=StateLeader || nodes[1].raft.raftLog.applied!=nodes[1].raft.raftLog.lastIndex() {
    t.Fatal("initial leader and applied-prefix prerequisites not reached")
   }
   observe("initial_election_drained")
   must(nodes[1].ProposeConfChange(pb.ConfChangeV2{
    Transition:pb.ConfChangeTransitionJointImplicit,
    Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}},
   }))
   pump();observe("joint_application_drained")
   if configIndex==0 || (overlap && (!transferStarted || timeoutDrops!=1)) {
    t.Fatal("selected scenario prerequisites not reached")
   }
   drained := func() bool {
    if len(queue)!=0 { return false }
    for _,id:=range ids {
     rn:=nodes[id];r:=rn.raft;l:=r.raftLog
     if rn.HasReady() || len(rn.stepsOnAdvance)!=0 || len(r.msgs)!=0 || len(r.msgsAfterAppend)!=0 ||
      l.applied!=l.applying || l.applied!=l.committed || l.committed!=l.lastIndex() ||
      len(l.unstable.entries)!=0 || l.unstable.snapshot!=nil { return false }
    }
    return true
   }
   emit("admitted",map[string]interface{}{
    "implicit":true,"applied":nodes[1].raft.raftLog.applied,
    "transfer":nodes[1].raft.leadTransferee,"timeout_drops":timeoutDrops,
    "auto_leave":nodes[1].raft.trk.AutoLeave,"drained":drained(),
   })
   tickRound := func() {
    for _,id:=range ids { nodes[id].Tick() }
    pump()
   }
   // The first ten rounds clear the transfer's documented election-timeout
   // blocker. Ten further rounds form the selected periodic input suffix.
   // Neither length is an invented deadline for configuration exit.
   for tick:=0;tick<10;tick++ { tickRound() }
   observe("cycle_start_state")
   emit("cycle_start",map[string]interface{}{
    "applied":nodes[1].raft.raftLog.applied,"leader":nodes[1].raft.state==StateLeader,
    "transfer":nodes[1].raft.leadTransferee,"drained":drained(),
    "timeout_drops":timeoutDrops,
   })
   snapshot := func() string {
    // Capture every field recursively, including term, vote, timers, log,
    // configuration, progress, inflight ring buffers, pending requests,
    // RawNode previous state and Advance callbacks. Storage is traversed
    // through the raftLog.storage interface. Exclusions are diagnostics or
    // single-threaded lock state, never protocol accounting.
    states:=map[string]interface{}{}
    for _,id:=range ids { states[fmt.Sprint(id)]=assuranceStateValue(reflect.ValueOf(nodes[id])) }
    states["transport_queue"]=assuranceStateValue(reflect.ValueOf(queue))
    states["caller_policy"]=map[string]interface{}{
     "node_order":ids,"completed_round_boundary":true,"overlap":overlap,
     "transfer_started":transferStarted,"timeout_drops":timeoutDrops,
     "config_index":configIndex,"storage_mode":"synchronous-no-crash",
    }
    data,err:=json.Marshal(states);must(err);return string(data)
   }
   before:=snapshot()
   inCycle=true
   cycleDrained:=drained()
   stableLeader:=nodes[1].raft.state==StateLeader
   for tick:=1;tick<=10;tick++ {
    tickRound()
    cycleDrained=cycleDrained && drained()
    stableLeader=stableLeader && nodes[1].raft.state==StateLeader
    observe(fmt.Sprintf("cycle_round_%d",tick))
   }
   inCycle=false
   after:=snapshot()
   // Full strings are retained for independent correspondence review. No
   // digest, precomputed expectation, or target mutation is used.
   emit("cycle_snapshots",map[string]interface{}{"before":before,"after":after})
   emit("cycle_result",map[string]interface{}{
    "state_equal":before==after,"all_rounds_drained":cycleDrained,
    "heartbeat_messages_only":cycleMessagesOnlyHeartbeats,"stable_leader":stableLeader,
    "cycle_closed":before==after && cycleDrained && cycleMessagesOnlyHeartbeats && stableLeader,
    "auto_leave":nodes[1].raft.trk.AutoLeave,"joint":len(nodes[1].raft.trk.Voters[1])>0,
    "applied":nodes[1].raft.raftLog.applied,"last":nodes[1].raft.raftLog.lastIndex(),
    "transfer":nodes[1].raft.leadTransferee,"timeout_drops":timeoutDrops,
   })
   observe("before_diagnostic_proposal")
   // This additional client operation is a diagnostic stimulus, not assumed
   // part of the implementation-owned automatic-exit obligation.
   must(nodes[1].Propose([]byte("diagnostic-after-observation")))
   pump();observe("after_diagnostic_proposal")
  })
 }
}

// assuranceStateValue takes an immutable value snapshot using read-only
// reflection. It never obtains an unsafe pointer or modifies unexported state.
func assuranceStateValue(v reflect.Value) interface{} {
 if !v.IsValid() { return nil }
 switch v.Kind() {
 case reflect.Interface,reflect.Pointer:
  if v.IsNil() { return nil };return assuranceStateValue(v.Elem())
 case reflect.Struct:
  out:=map[string]interface{}{"$type":v.Type().String()}
  for i:=0;i<v.NumField();i++ {
   name:=v.Type().Field(i).Name
   // Logger/TraceLogger are output sinks. The default trace logger is nil.
   if name=="logger" || name=="traceLogger" { continue }
   // MemoryStorage calls are serialized. Its callStats only count reads and
   // do not select a storage result; Mutex is unlocked at each observation.
   if v.Type()==reflect.TypeOf(MemoryStorage{}) && (name=="Mutex" || name=="callStats") { continue }
   out[name]=assuranceStateValue(v.Field(i))
  }
  return out
 case reflect.Map:
  if v.IsNil() { return nil }
  out:=map[string]interface{}{}
  iter:=v.MapRange()
  for iter.Next() {
   key,_:=json.Marshal(assuranceStateValue(iter.Key()))
   out[string(key)]=assuranceStateValue(iter.Value())
  }
  return out
 case reflect.Slice,reflect.Array:
  if v.Kind()==reflect.Slice && v.IsNil() { return nil }
  out:=make([]interface{},v.Len())
  for i:=range out { out[i]=assuranceStateValue(v.Index(i)) }
  return out
 case reflect.Bool:return v.Bool()
 case reflect.String:return v.String()
 case reflect.Int,reflect.Int8,reflect.Int16,reflect.Int32,reflect.Int64:return v.Int()
 case reflect.Uint,reflect.Uint8,reflect.Uint16,reflect.Uint32,reflect.Uint64,reflect.Uintptr:return v.Uint()
 case reflect.Func:
  if v.IsNil() { return nil }
  // Role callbacks bind the same unchanged raft receiver; include code
  // identity. No callback is invoked by this observation helper.
  return fmt.Sprintf("%s@%x",v.Type(),v.Pointer())
 default:panic(fmt.Sprintf("unsupported state kind %s (%s)",v.Kind(),v.Type()))
 }
}
