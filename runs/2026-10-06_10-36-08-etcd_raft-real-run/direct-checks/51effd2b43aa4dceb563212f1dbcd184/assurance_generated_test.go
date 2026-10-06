package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 "reflect"
 "sort"
 pb "go.etcd.io/raft/v3/raftpb"
)

type assuranceCluster struct {
 t *testing.T
 nodes map[uint64]*RawNode
 stores map[uint64]*MemoryStorage
 queue []pb.Message
 transfer bool
 injected bool
 drops int
 changeIndex uint64
 ticks int
 suffixTrace []string
 inSuffix bool
 heartbeatAcks map[uint64]int
}
func assuranceEmit(kind string, fields map[string]interface{}) {
 fields["event"] = kind
 b, err := json.Marshal(fields); if err != nil { panic(err) }
 fmt.Println("CA_EVENT " + string(b))
}
func assuranceNew(t *testing.T, transfer bool) *assuranceCluster {
 c := &assuranceCluster{t:t,nodes:map[uint64]*RawNode{},stores:map[uint64]*MemoryStorage{},transfer:transfer,heartbeatAcks:map[uint64]int{}}
 for id:=uint64(1); id<=3; id++ {
  s:=NewMemoryStorage()
  if err:=s.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1,2,3}}}}); err!=nil { t.Fatal(err) }
  if err:=s.SetHardState(pb.HardState{Term:1,Commit:1}); err!=nil {t.Fatal(err)}
  rn,err:=NewRawNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:s,Applied:1,MaxSizePerMsg:4096,MaxInflightMsgs:16,CheckQuorum:true,PreVote:true})
  if err!=nil {t.Fatal(err)}
  c.nodes[id]=rn;c.stores[id]=s
 }
 return c
}
func(c *assuranceCluster) drain() {
 for step:=0;step<10000;step++ {
  work:=false
  for id:=uint64(1);id<=3;id++ {
   rn:=c.nodes[id];s:=c.stores[id]
   if !rn.HasReady(){continue};work=true
   rd:=rn.Ready()
   if !IsEmptySnap(rd.Snapshot){if err:=s.ApplySnapshot(rd.Snapshot);err!=nil{c.t.Fatal(err)}}
   if err:=s.Append(rd.Entries);err!=nil{c.t.Fatal(err)}
   if !IsEmptyHardState(rd.HardState){if err:=s.SetHardState(rd.HardState);err!=nil{c.t.Fatal(err)}}
   // Queue only after the corresponding persistence work, and deliver FIFO.
   c.queue=append(c.queue,rd.Messages...)
   for _,ent:=range rd.CommittedEntries {
    switch ent.Type {
    case pb.EntryConfChangeV2:
     var cc pb.ConfChangeV2;if err:=cc.Unmarshal(ent.Data);err!=nil{c.t.Fatal(err)}
     if id==1 && len(cc.Changes)>0 {
      c.changeIndex=ent.Index
      if c.transfer && !c.injected {
       rn.TransferLeader(2);c.injected=true
       assuranceEmit("transfer_started",map[string]interface{}{"index":ent.Index,"term":rn.raft.Term,"target":rn.raft.leadTransferee})
      }
     }
     cs:=rn.ApplyConfChange(cc)
     if id==1 && len(cc.Changes)>0 { assuranceEmit("admitted",map[string]interface{}{"op_id":"implicit-remove-3","node":1,"change_index":ent.Index,"entry_term":ent.Term,"term":rn.raft.Term,"auto_leave":cs.AutoLeave,"target":rn.raft.leadTransferee,"policy":"drop_timeout_now","role":rn.raft.state.String()}) }
     if id==1 {assuranceEmit("configuration_applied",map[string]interface{}{"index":ent.Index,"term":rn.raft.Term,"auto_leave":cs.AutoLeave,"outgoing":cs.VotersOutgoing,"transfer":rn.raft.leadTransferee})}
    case pb.EntryConfChange:
     var cc pb.ConfChange;if err:=cc.Unmarshal(ent.Data);err!=nil{c.t.Fatal(err)};rn.ApplyConfChange(cc)
    }
   }
   rn.Advance(rd)
  }
  if len(c.queue)>0 {
   work=true;m:=c.queue[0];c.queue=c.queue[1:]
   // The transport policy is chosen before execution, not from observed failure.
   if c.transfer && m.Type==pb.MsgTimeoutNow {
    c.drops++;assuranceEmit("transport_drop",map[string]interface{}{"type":m.Type.String(),"from":m.From,"to":m.To,"term":m.Term})
   } else if n:=c.nodes[m.To];n!=nil {
    if c.inSuffix { b,err:=json.Marshal(m);if err!=nil{c.t.Fatal(err)};c.suffixTrace=append(c.suffixTrace,string(b));if m.Type==pb.MsgHeartbeatResp && m.To==1 {c.heartbeatAcks[m.From]++} }
    if err:=n.Step(m);err!=nil && err!=ErrStepPeerNotFound {c.t.Fatal(err)}
   } else {c.t.Fatalf("unknown destination %d",m.To)}
  }
  if !work{return}
 }
 c.t.Fatal("driver did not drain within operation bound")
}
func(c *assuranceCluster) observe(phase string) {
 r:=c.nodes[1].raft
 ready:=false;unstable:=0;localMessages:=0
 for _,n:=range c.nodes {ready=ready||n.HasReady();unstable+=len(n.raft.raftLog.unstable.entries);localMessages+=len(n.raft.msgs)+len(n.raft.msgsAfterAppend)+len(n.stepsOnAdvance)}
 assuranceEmit("observation",map[string]interface{}{"phase":phase,"transfer_policy":c.transfer,"ticks":c.ticks,"term":r.Term,"role":r.state.String(),"change_index":c.changeIndex,"last":r.raftLog.lastIndex(),"committed":r.raftLog.committed,"applied":r.raftLog.applied,"applying":r.raftLog.applying,"auto_leave":r.trk.AutoLeave,"outgoing":r.trk.ConfState().VotersOutgoing,"transferee":r.leadTransferee,"pending_conf":r.pendingConfIndex,"queue":len(c.queue),"local_messages":localMessages,"unstable":unstable,"has_ready":ready,"timeout_drops":c.drops})
}

// Capture protocol state without invoking String methods or mutating target values.
// The only exclusions are IO/logging diagnostics and the duplicate Storage interface.
// MemoryStorage content is included separately; all access is on this test goroutine.
func assuranceValue(v reflect.Value) interface{} {
 if !v.IsValid(){return nil}
 switch v.Kind(){
 case reflect.Interface,reflect.Pointer:
  if v.IsNil(){return nil};return assuranceValue(v.Elem())
 case reflect.Struct:
  out:=map[string]interface{}{}
  for i:=0;i<v.NumField();i++ {
   name:=v.Type().Field(i).Name
   switch name {case "logger","traceLogger","storage","Mutex","callStats":continue}
   out[name]=assuranceValue(v.Field(i))
  };return out
 case reflect.Slice:
  if v.IsNil(){return nil}
  a:=make([]interface{},v.Len());for i:=range a{a[i]=assuranceValue(v.Index(i))}
  return map[string]interface{}{"capacity":v.Cap(),"values":a}
 case reflect.Array:
  a:=make([]interface{},v.Len());for i:=range a{a[i]=assuranceValue(v.Index(i))};return a
 case reflect.Map:
  if v.IsNil(){return nil}
  keys:=v.MapKeys();sort.Slice(keys,func(i,j int)bool{return assuranceKey(keys[i])<assuranceKey(keys[j])})
  a:=make([]interface{},0,len(keys));for _,k:=range keys{a=append(a,[]interface{}{assuranceValue(k),assuranceValue(v.MapIndex(k))})};return a
 case reflect.Bool:return v.Bool()
 case reflect.String:return v.String()
 case reflect.Int,reflect.Int8,reflect.Int16,reflect.Int32,reflect.Int64:return v.Int()
 case reflect.Uint,reflect.Uint8,reflect.Uint16,reflect.Uint32,reflect.Uint64,reflect.Uintptr:return v.Uint()
 case reflect.Func:
  if v.IsNil(){return nil};return fmt.Sprintf("function-code:%x",v.Pointer())
 default:panic(fmt.Sprintf("unsupported captured state %s",v.Type()))
 }
}
func assuranceKey(v reflect.Value)string {b,e:=json.Marshal(assuranceValue(v));if e!=nil{panic(e)};return string(b)}
func(c *assuranceCluster) state()string {
 // Driver counters and observations cannot influence future delivery or protocol work.
 // The suffix schedule is fixed: tick 1,2,3, then drain; compare at its boundary.
 nodes:=map[uint64]interface{}{};stores:=map[uint64]interface{}{}
 for id:=uint64(1);id<=3;id++ {nodes[id]=assuranceValue(reflect.ValueOf(c.nodes[id]));stores[id]=assuranceValue(reflect.ValueOf(c.stores[id]))}
 out:=map[string]interface{}{"nodes":nodes,"stores":stores,"queue":assuranceValue(reflect.ValueOf(c.queue)),"transfer_policy":c.transfer,"injected":c.injected,"change_index":c.changeIndex,"schedule_phase":"before_tick_1"}
 b,e:=json.Marshal(out);if e!=nil{c.t.Fatal(e)};return string(b)
}
func(c *assuranceCluster) resultFields()map[string]interface{} {
 r:=c.nodes[1].raft;pending:=0;ready:=false
 for _,n:=range c.nodes{pending+=len(n.raft.msgs)+len(n.raft.msgsAfterAppend)+len(n.stepsOnAdvance);ready=ready||n.HasReady()}
 return map[string]interface{}{"policy":"drop_timeout_now","op_id":"implicit-remove-3","node":1,"change_index":c.changeIndex,"term":r.Term,"role":r.state.String(),"target":r.leadTransferee,"auto_leave":r.trk.AutoLeave,"outgoing_count":len(r.trk.Voters[1]),"last":r.raftLog.lastIndex(),"committed":r.raftLog.committed,"applied":r.raftLog.applied,"applying":r.raftLog.applying,"queue_count":len(c.queue),"local_messages":pending,"has_ready":ready,"ticks":c.ticks,"timeout_drops":c.drops,"state":c.state()}
}
func(c *assuranceCluster) tickAll(){
 for id:=uint64(1);id<=3;id++{c.nodes[id].Tick()};c.ticks++;c.drain()
}
func TestAssuranceAutoExitCycle(t *testing.T){
 c:=assuranceNew(t,true)
 if StateTraceDeployed {t.Fatal("this check requires the default no-op trace build")}
 if err:=c.nodes[1].Campaign();err!=nil{t.Fatal(err)};c.drain()
 if c.nodes[1].raft.state!=StateLeader{t.Fatal("campaign did not establish leader")}
 cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}}
 if err:=c.nodes[1].ProposeConfChange(cc);err!=nil{t.Fatal(err)};c.drain()
 if !c.injected || c.changeIndex==0 {t.Fatal("configuration and transfer prefix not reached")}
 c.observe("after_apply")
 for i:=0;i<10;i++{c.tickAll()}
 startState:=c.state()
 assuranceEmit("cycle_start",c.resultFields())
 c.inSuffix=true
 for i:=0;i<10;i++{c.tickAll()}
 c.inSuffix=false
 out:=c.resultFields();out["cycle_repeats"]=out["state"].(string)==startState;out["heartbeat_acks_2"]=c.heartbeatAcks[2];out["heartbeat_acks_3"]=c.heartbeatAcks[3]
 out["delivery_trace"]=c.suffixTrace
 assuranceEmit("cycle_result",out)
}
