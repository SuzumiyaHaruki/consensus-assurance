from pathlib import Path
s=Path('joint_exit_explore_test.go').read_text()
s=s.replace('"fmt"','"fmt"\n "reflect"')
s=s.replace('TestAssuranceJointExitTransferExploration','TestAssuranceJointExitContinuation')
s=s.replace('   emit := func','   var configIndex uint64\n   inCycle := false\n   cycleMessagesOnlyHeartbeats := true\n   emit := func')
s=s.replace('    fields["phase"] = phase','    fields["phase"] = phase\n    fields["event"] = phase\n    fields["case_id"] = fmt.Sprintf("implicit-remove3-overlap-%v", overlap)\n    fields["config_index"] = configIndex')
s=s.replace('   var configIndex uint64\n   var appliedConfigs int','   var appliedConfigs int')
s=s.replace('      m:=queue[0];queue=queue[1:];messageCount++','      m:=queue[0];queue=queue[1:];messageCount++\n      if inCycle && m.Type!=pb.MsgHeartbeat && m.Type!=pb.MsgHeartbeatResp { cycleMessagesOnlyHeartbeats=false }')
a=s.index('   // All nodes are ticked.')
b=s.index('   observe("before_diagnostic_proposal")',a)
s=s[:a]+'''   drained := func() bool {
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
''' +s[b:]
s+='''
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
'''
Path('joint_exit_fixed_test.go').write_text(s)
