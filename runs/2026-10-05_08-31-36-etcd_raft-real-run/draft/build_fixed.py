p=open('autoleave_explore_test.go').read()
p=p.replace(' "testing"',' "testing"\n "reflect"\n "sort"')
p=p.replace(' delivered int\n',' delivered int\n suffixOnlyHeartbeats bool\n suffixErrors int\n suffixDeliveries int\n cycleStart string\n startPending bool\n')
p=p.replace('"kind":kind,"scenario":e.name,"tick":e.tick','"event":kind,"kind":kind,"scenario":e.name,"node":uint64(1),"conf_index":e.confIndex,"tick":e.tick,"policy_transfer":e.transfer')
p=p.replace(' rd:=n.Ready()',' rd:=n.Ready()\n admitted:=false')
p=p.replace('e.triggered=true; e.confIndex=ent.Index','e.triggered=true; e.confIndex=ent.Index; admitted=true')
p=p.replace('"auto_leave":n.Status().Config.AutoLeave','"auto_leave":n.raft.trk.Config.AutoLeave')
p=p.replace(' n.Advance(rd)\n return true',' n.Advance(rd)\n if admitted {e.emit("joint_admitted",map[string]interface{}{"live_auto_leave":n.raft.trk.Config.AutoLeave,"joint":len(n.raft.trk.Config.Voters[1])>0,"applied":n.raft.raftLog.applied,"term":n.raft.Term,"transfer_active":n.raft.leadTransferee==2,"role":n.raft.state.String()})}\n return true')
p=p.replace('    if err:=n.Step(m);err!=nil && err!=ErrStepPeerNotFound {e.t.Fatal(err)}','    err:=n.Step(m)\n    if e.tick>20 && e.tick<=30 {\n     e.suffixDeliveries++\n     if err!=nil {e.suffixErrors++}\n     if m.Type!=pb.MsgHeartbeat && m.Type!=pb.MsgHeartbeatResp {e.suffixOnlyHeartbeats=false}\n    }\n    if err!=nil && err!=ErrStepPeerNotFound {e.t.Fatal(err)}')
p=p.replace('"auto_leave":s.Config.AutoLeave','"live_auto_leave":r.trk.Config.AutoLeave,"status_auto_leave":s.Config.AutoLeave')
p=p.replace('func TestAssuranceAutoLeaveExploration','func TestAssuranceAutoLeaveFixed')
p=p.replace('transfer:transfer,fault:transfer}', 'transfer:transfer,fault:transfer,suffixOnlyHeartbeats:true}')
p=p.replace('tick<=40','tick<=30').replace('tick==40','tick==30')
p=p.replace('    if tick==10 || tick==20 || tick==30 {e.observe("quiet_checkpoint")}','''    if tick==10 || tick==20 || tick==30 {e.observe("quiet_checkpoint")}
    if tick==20 {
     e.cycleStart=e.protocolState()
     e.startPending=e.pendingAutomatic()
     e.emit("cycle_state_start",map[string]interface{}{"state":e.cycleStart,"pending_automatic":e.startPending})
    }
    if tick==30 {
     end:=e.protocolState()
     same:=e.cycleStart==end
     closed:=same && e.startPending && e.pendingAutomatic() && e.suffixOnlyHeartbeats && e.suffixErrors==0 && e.suffixDeliveries>0 && !e.fault
     e.emit("cycle_state_end",map[string]interface{}{"state":end,"pending_automatic":e.pendingAutomatic()})
     e.emit("cycle_result",map[string]interface{}{"same_state":same,"start_pending":e.startPending,"end_pending":e.pendingAutomatic(),"only_heartbeat_delivery":e.suffixOnlyHeartbeats,"delivery_errors":e.suffixErrors,"deliveries":e.suffixDeliveries,"closed_pending_cycle":closed,"live_auto_leave":e.nodes[1].raft.trk.Config.AutoLeave,"outgoing_count":len(e.nodes[1].raft.trk.Config.Voters[1])})
    }''')
# Add structural state serialization; this observes rather than modifies state.
p+='''
// project serializes all recursively reachable protocol fields, including
// unexported scalar fields, without unsafe access or calls to target methods.
// Logging objects, unlocked storage mutex and diagnostic counters are excluded:
// they do not feed protocol choices in this serialized no-crash execution.
// Slice capacities and unused backing-array cells affect allocation, not entries.
func assuranceProject(v reflect.Value) interface{} {
 if !v.IsValid(){return nil}
 switch v.Kind() {
 case reflect.Interface,reflect.Pointer:
  if v.IsNil(){return nil};return assuranceProject(v.Elem())
 case reflect.Struct:
  fields:=map[string]interface{}{}
  for i:=0;i<v.NumField();i++ {
   n:=v.Type().Field(i).Name
   if n=="logger" || n=="traceLogger" || (v.Type()==reflect.TypeOf(MemoryStorage{}) && (n=="Mutex" || n=="callStats")){continue}
   fields[n]=assuranceProject(v.Field(i))
  }
  return fields
 case reflect.Map:
  if v.IsNil(){return nil}
  entries:=[]interface{}{}
  keys:=v.MapKeys()
  sort.Slice(keys,func(i,j int)bool{a,_:=json.Marshal(assuranceProject(keys[i]));b,_:=json.Marshal(assuranceProject(keys[j]));return string(a)<string(b)})
  for _,k:=range keys{entries=append(entries,[]interface{}{assuranceProject(k),assuranceProject(v.MapIndex(k))})}
  return entries
 case reflect.Slice,reflect.Array:
  if v.Kind()==reflect.Slice && v.IsNil(){return nil}
  a:=make([]interface{},v.Len());for i:=range a{a[i]=assuranceProject(v.Index(i))};return a
 case reflect.Bool:return v.Bool()
 case reflect.String:return v.String()
 case reflect.Int,reflect.Int8,reflect.Int16,reflect.Int32,reflect.Int64:return v.Int()
 case reflect.Uint,reflect.Uint8,reflect.Uint16,reflect.Uint32,reflect.Uint64,reflect.Uintptr:return v.Uint()
 case reflect.Float32,reflect.Float64:return v.Float()
 case reflect.Func:
  if v.IsNil(){return nil};return fmt.Sprintf("function:%x",v.Pointer())
 default:panic("unsupported state kind: "+v.Kind().String())
 }
}
func (e *assuranceAutoEnv) protocolState() string {
 // The remaining caller state is fixed policy plus applied cursors and network.
 // tick/delivered/drop counters are diagnostic. At both cuts fault=false forever
 // for the compared quiet suffix; every round ticks 1,2,3 then drains FIFO.
 s:=map[string]interface{}{"nodes":assuranceProject(reflect.ValueOf(e.nodes)),"queue":assuranceProject(reflect.ValueOf(e.queue)),"applied":assuranceProject(reflect.ValueOf(e.applied)),"fault":e.fault,"transfer_policy":e.transfer,"triggered":e.triggered,"conf_index":e.confIndex}
 b,err:=json.Marshal(s);if err!=nil{e.t.Fatal(err)};return string(b)
}
func (e *assuranceAutoEnv) pendingAutomatic() bool {
 r:=e.nodes[1].raft
 return r.state==StateLeader && r.leadTransferee==0 && r.trk.Config.AutoLeave && len(r.trk.Config.Voters[1])>0 && r.raftLog.applied>=e.confIndex && r.raftLog.lastIndex()==e.confIndex && len(e.queue)==0
}
'''
open('autoleave_fixed_test.go','w').write(p)
