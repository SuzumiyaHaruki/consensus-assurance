from pathlib import Path
s=Path('autoleave_explore_test.go').read_text().replace('"testing"','"testing"\n "reflect"\n "sort"\n "strconv"')
s=s.replace('TestAssuranceAutoLeaveTransferExplore','TestAssuranceAutoLeaveTransferCheck')
s=s.replace('dropped:=0','dropped:=0\n   dropTransfer:=overlap\n   cycleActive:=false\n   cycleMessages:=map[string]int{}\n   cycleOnlyHeartbeats:=true\n   cycleAllJoint:=true')
s=s.replace('"stage":stage,"overlap":overlap','"event":stage,"operation":"implicit-remove-3", "overlap":overlap')
s=s.replace('if overlap && m.Type==pb.MsgTimeoutNow {dropped++}', '''if cycleActive {
       cycleMessages[m.Type.String()]++
       if m.Type!=pb.MsgHeartbeat && m.Type!=pb.MsgHeartbeatResp {cycleOnlyHeartbeats=false}
      }
      if dropTransfer && m.Type==pb.MsgTimeoutNow {dropped++}''')
s=s.replace('if !progressed {return}', '''if cycleActive {
      for id:=uint64(1);id<=3;id++ {
       r:=nodes[id].raft
       if !r.trk.Config.AutoLeave || len(r.trk.Config.Voters[1])==0 {cycleAllJoint=false}
      }
     }
     if !progressed {return}''')
a=s.index('   emit("after_joint_drain")')
s=s[:a]+'''   emit("after_joint_drain")
   // The only network fault is over. The measured suffix is fully reliable.
   dropTransfer=false
   var first,second string
   for tick:=0;tick<30;tick++ {
    for id:=uint64(1);id<=3;id++ {nodes[id].Tick()}
    pump()
    if tick==9 {emit("after_transfer_timeout")}
    if tick==19 && overlap {
     first=assuranceState(t,nodes,queue)
     cycleActive=true
     fmt.Println("CA_EVENT "+assuranceJSON(t,map[string]interface{}{"event":"cycle_start","operation":"implicit-remove-3","overlap":overlap,"state":first}))
    }
   }
   emit("after_30_ticks")
   if overlap {
    second=assuranceState(t,nodes,queue)
    fmt.Println("CA_EVENT "+assuranceJSON(t,map[string]interface{}{"event":"cycle_end","operation":"implicit-remove-3","overlap":overlap,"state":second}))
    r:=nodes[1].raft
    drained:=len(queue)==0
    for _,rn:=range nodes {drained=drained && !rn.HasReady() && len(rn.stepsOnAdvance)==0}
    recurrence:=first==second
    completed:=!r.trk.Config.AutoLeave && len(r.trk.Config.Voters[1])==0
    repeatable:=recurrence && cycleOnlyHeartbeats && cycleAllJoint && drained && r.leadTransferee==None && r.state==StateLeader && r.raftLog.applied==r.raftLog.lastIndex()
    result:=map[string]interface{}{"event":"cycle_diagnostic","operation":"implicit-remove-3","overlap":overlap,"state_equal":recurrence,"only_heartbeats":cycleOnlyHeartbeats,"joint_throughout":cycleAllJoint,"drained":drained,"completed":completed,"cycle_messages":cycleMessages,"dropped_timeout_now":dropped,"change_index":changeIndex,"term":r.Term,"last":r.raftLog.lastIndex(),"applied":r.raftLog.applied,"transferee":r.leadTransferee,"forbidden_cycle":repeatable}
    // An unequal state with no completion is inconclusive, not a passing check.
    if completed || repeatable {result["event"]="continuation_result"}
    fmt.Println("CA_EVENT "+assuranceJSON(t,result))
    cycleActive=false
    if err:=nodes[1].Propose([]byte("diagnostic continuation stimulus"));err!=nil {t.Fatal(err)};pump()
    emit("after_new_proposal")
   }
  })
 }
}

func assuranceJSON(t *testing.T, value interface{}) string {
 t.Helper(); b,err:=json.Marshal(value);if err!=nil {t.Fatal(err)};return string(b)
}

// Read-only structural snapshots include all RawNode/raft/log/storage/progress
// fields, timers, buffers, saved Ready responses, and transport queue contents.
// The only omitted fields are logger sinks and MemoryStorage call statistics.
// These snapshots are compared directly: there is no digest or saved baseline.
func assuranceState(t *testing.T, nodes map[uint64]*RawNode, queue []pb.Message) string {
 state:=map[string]interface{}{}
 for id:=uint64(1);id<=3;id++ {state[strconv.FormatUint(id,10)]=assuranceValue(t,reflect.ValueOf(nodes[id]))}
 state["network"]=assuranceValue(t,reflect.ValueOf(queue))
 return assuranceJSON(t,state)
}

func assuranceValue(t *testing.T,v reflect.Value) interface{} {
 t.Helper()
 if !v.IsValid(){return nil}
 typ:=v.Type()
 switch v.Kind() {
 case reflect.Interface,reflect.Ptr:
  if v.IsNil(){return map[string]interface{}{"type":typ.String(),"nil":true}}
  return map[string]interface{}{"type":typ.String(),"value":assuranceValue(t,v.Elem())}
 case reflect.Struct:
  fields:=map[string]interface{}{}
  for i:=0;i<v.NumField();i++ {
   name:=typ.Field(i).Name
   if (typ.Name()=="raft" && (name=="logger" || name=="traceLogger")) || ((typ.Name()=="raftLog" || typ.Name()=="unstable") && name=="logger") || (typ.Name()=="MemoryStorage" && name=="callStats") {continue}
   fields[name]=assuranceValue(t,v.Field(i))
  }
  return map[string]interface{}{"type":typ.String(),"fields":fields}
 case reflect.Map:
  if v.IsNil(){return map[string]interface{}{"type":typ.String(),"nil":true}}
  pairs:=[]string{}
  for _,k:=range v.MapKeys(){pairs=append(pairs,assuranceJSON(t,[]interface{}{assuranceValue(t,k),assuranceValue(t,v.MapIndex(k))}))}
  sort.Strings(pairs)
  return map[string]interface{}{"type":typ.String(),"pairs":pairs}
 case reflect.Slice,reflect.Array:
  values:=[]interface{}{}
  for i:=0;i<v.Len();i++ {values=append(values,assuranceValue(t,v.Index(i)))}
  result:=map[string]interface{}{"type":typ.String(),"values":values}
  if v.Kind()==reflect.Slice {result["nil"]=v.IsNil();result["capacity"]=v.Cap()}
  return result
 case reflect.Bool:return v.Bool()
 case reflect.String:return v.String()
 case reflect.Int,reflect.Int8,reflect.Int16,reflect.Int32,reflect.Int64:return v.Int()
 case reflect.Uint,reflect.Uint8,reflect.Uint16,reflect.Uint32,reflect.Uint64,reflect.Uintptr:return v.Uint()
 case reflect.Func:
  // Function code identity is compared within this execution. Receiver state
  // is serialized above; no callback replacement occurs in the suffix.
  return map[string]interface{}{"type":typ.String(),"function":v.Pointer()}
 default:t.Fatalf("unsupported state kind %v of %v",v.Kind(),typ);return nil
 }
}
'''
Path('autoleave_check_test.go').write_text(s)
