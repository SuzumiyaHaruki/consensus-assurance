p='autoleave_explore_test.go'
s=open(p).read().replace(' "testing"',' "testing"\n "reflect"\n "runtime"\n "strconv"')
s=s.replace(' ticks int\n caseID string',' ticks int\n caseID string\n configurationIndex uint64\n applied map[uint64][]pb.Entry\n deliveries map[string]int\n cycleMessages []string\n recording bool')
s=s.replace('e:=map[string]interface{}{"case":c.caseID,','e:=map[string]interface{}{"event":phase,"operation_id":c.caseID+"/implicit-remove-3","configuration_index":c.configurationIndex,"case":c.caseID,')
s=s.replace('   for _,e:=range rd.CommittedEntries {','   for _,e:=range rd.CommittedEntries {\n    c.applied[id]=append(c.applied[id],e)')
s=s.replace('      c.injected=true','      c.injected=true\n      c.configurationIndex=e.Index')
s=s.replace('if c.transfer && m.Type==pb.MsgTimeoutNow {c.dropped++;continue}','if c.transfer && c.dropped==0 && m.Type==pb.MsgTimeoutNow {c.dropped++;continue}\n   key:=fmt.Sprintf("%d>%d:%s",m.From,m.To,m.Type)\n   c.deliveries[key]++\n   if c.recording { b,err:=json.Marshal(m);if err!=nil{c.t.Fatal(err)};c.cycleMessages=append(c.cycleMessages,string(b)) }')
s=s.replace('func TestAssuranceAutoLeaveExploration','func TestAssuranceAutoLeaveRecurrence')
s=s.replace('transfer:transfer,caseID:name}', 'transfer:transfer,caseID:name,applied:map[uint64][]pb.Entry{},deliveries:map[string]int{}}')
s=s.replace('   c.event("initial_drain",nil)','   c.event("operation_admitted",map[string]interface{}{"entered":c.injected,"all_work_drained":!c.anyReady() && len(c.queue)==0})')
a=s.index('   for i:=0;i<40;i++')
b=s.index('   if transfer {',a)
s=s[:a]+'''   for i:=0;i<20;i++ {c.tick()}
   left:=c.protocolState()
   leader:=c.nodes[1].rn.raft
   eligible:=leader.state==StateLeader && leader.leadTransferee==None && leader.raftLog.applied>=c.configurationIndex && !c.anyReady() && len(c.queue)==0
   c.event("suffix_start",map[string]interface{}{"eligible":eligible,"state":left})
   c.recording=true
   for i:=0;i<10;i++ {c.tick()}
   c.recording=false
   right:=c.protocolState()
   same:=reflect.DeepEqual(left,right)
   c.event("recurrence_result",map[string]interface{}{
    "cycle_repeat":same,"pending":leader.trk.AutoLeave && len(leader.trk.Voters[1])>0,
    "cycle_ticks":10,"state":right,"cycle_messages":c.cycleMessages,
    "all_work_drained":!c.anyReady() && len(c.queue)==0,"deliveries":c.deliveries,
   })
''' +s[b:]
s=s.replace('c.drain();c.event("after_rescue_proposal",nil)','c.drain();c.event("after_rescue_proposal",map[string]interface{}{"exited":!leader.trk.AutoLeave && len(leader.trk.Voters[1])==0})')
s+='''
func (c *assuranceAutoCluster) anyReady() bool {
 for id:=uint64(1);id<=3;id++ {if c.nodes[id].rn.HasReady(){return true}}
 return false
}

// Observe every field recursively, including private protocol and storage state.
// Logger objects are output infrastructure; storage callStats are diagnostic
// counters, incremented but never consulted by protocol code. Both are omitted.
// No field is written by this observer. Callback code identity is retained;
// their receiver is the same live raft instance throughout this suffix.
func assuranceObserve(v reflect.Value) interface{} {
 if !v.IsValid(){return nil}
 switch v.Kind() {
 case reflect.Interface:
  if v.IsNil(){return nil};return assuranceObserve(v.Elem())
 case reflect.Pointer:
  if v.IsNil(){return nil};return assuranceObserve(v.Elem())
 case reflect.Struct:
  out:=map[string]interface{}{"_type":v.Type().String()}
  for i:=0;i<v.NumField();i++ {
   name:=v.Type().Field(i).Name
   if v.Type().PkgPath()=="go.etcd.io/raft/v3" {
    typ:=v.Type().Name()
    if name=="logger" && (typ=="raft" || typ=="raftLog" || typ=="unstable") {continue}
    if typ=="MemoryStorage" && name=="callStats" {continue}
   }
   out[name]=assuranceObserve(v.Field(i))
  }
  return out
 case reflect.Map:
  if v.IsNil(){return nil};out:=map[string]interface{}{}
  it:=v.MapRange()
  for it.Next(){
   k:=it.Key();var key string
   switch k.Kind(){case reflect.String:key=k.String();case reflect.Uint64:key=strconv.FormatUint(k.Uint(),10);default:panic("unsupported map key: "+k.Type().String())}
   out[key]=assuranceObserve(it.Value())
  }
  return out
 case reflect.Slice:
  if v.IsNil(){return nil}
  out:=make([]interface{},v.Len());for i:=range out{out[i]=assuranceObserve(v.Index(i))}
  return map[string]interface{}{"len":v.Len(),"cap":v.Cap(),"values":out}
 case reflect.Array:
  out:=make([]interface{},v.Len());for i:=range out{out[i]=assuranceObserve(v.Index(i))};return out
 case reflect.String:return v.String()
 case reflect.Bool:return v.Bool()
 case reflect.Int,reflect.Int8,reflect.Int16,reflect.Int32,reflect.Int64:return v.Int()
 case reflect.Uint,reflect.Uint8,reflect.Uint16,reflect.Uint32,reflect.Uint64,reflect.Uintptr:return v.Uint()
 case reflect.Func:
  if v.IsNil(){return nil};return runtime.FuncForPC(v.Pointer()).Name()
 default:panic("unsupported observation kind: "+v.Kind().String())
 }
}
func (c *assuranceAutoCluster) protocolState() interface{} {
 out:=map[string]interface{}{}
 for id:=uint64(1);id<=3;id++ {
  n:=c.nodes[id]
  out[strconv.FormatUint(id,10)]=assuranceObserve(reflect.ValueOf(n.rn))
 }
 out["network_queue"]=assuranceObserve(reflect.ValueOf(c.queue))
 out["application_journals"]=assuranceObserve(reflect.ValueOf(c.applied))
 out["transfer_policy"]=c.transfer
 out["transfer_injected"]=c.injected
 out["timeout_now_already_dropped"]=c.dropped
 out["configuration_index"]=c.configurationIndex
 // Absolute test ticks, event counts and trace strings do not drive Raft.
 // The compared transition is always ten Tick-all/fully-drain iterations.
 return out
}
'''
open('autoleave_fixed_test.go','w').write(s)
