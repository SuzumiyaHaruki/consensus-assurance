from pathlib import Path
s=Path('transfer_explore_test.go').read_text()
s=s.replace('"fmt"','"fmt"\n "reflect"\n "runtime"\n "sort"')
s=s.replace('func TestAssuranceJointExitTransfer', 'func TestAssuranceJointExitTransferCycle')
s=s.replace('var jointIndex uint64','''var jointIndex uint64
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
   }''')
s=s.replace('"scenario": name, "phase": phase,', '"event": phase, "scenario": name, "with_transfer": transfer, "operation": "implicit-remove-3", "phase": phase,')
s=s.replace('"pending_conf": r.pendingConfIndex,', '''"pending_conf": r.pendingConfIndex,
     "application_done": applied[1] >= jointIndex && r.raftLog.applied >= jointIndex,
     "ready_pending": nodes[1].HasReady(),
     "pending_continuously": pendingContinuously,
     "cycle_state": stateText(),''')
s=s.replace('rn.ApplyConfChange(cc)','rn.ApplyConfChange(cc)\n        observe()')
s=s.replace('rn.Advance(rd)','rn.Advance(rd)\n      observe()')
s=s.replace('err := nodes[m.To].Step(m)','err := nodes[m.To].Step(m)\n       observe()')
s=s.replace('dropped++', '''dropped++
       fmt.Printf("CA_EVENT {\\"event\\":\\"network_drop\\",\\"scenario\\":%q,\\"from\\":%d,\\"to\\":%d,\\"message_type\\":%q,\\"term\\":%d}\\n", name, m.From, m.To, m.Type.String(), m.Term)''')
s=s.replace('delivered++','''delivered++
       fmt.Printf("CA_EVENT {\\"event\\":\\"network_delivery\\",\\"scenario\\":%q,\\"sequence\\":%d,\\"from\\":%d,\\"to\\":%d,\\"message_type\\":%q,\\"term\\":%d,\\"index\\":%d,\\"commit\\":%d,\\"entry_count\\":%d}\\n", name, delivered, m.From, m.To, m.Type.String(), m.Term, m.Index, m.Commit, len(m.Entries))''')
a=s.index('   for tick := 1; tick <= 100; tick++ {')
b=s.index('   // A separately labelled',a)
s=s[:a]+'''   for tick := 1; tick <= 20; tick++ {
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
     fmt.Printf("CA_EVENT {\\"event\\":\\"cycle_diagnostic\\",\\"scenario\\":%q,\\"state_repeated\\":%t}\\n", name, stateText() == cycleStart)
     inCycle = false
    }
   }
''' +s[b:]
s+='''
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
'''
Path('transfer_cycle_test.go').write_text(s)
