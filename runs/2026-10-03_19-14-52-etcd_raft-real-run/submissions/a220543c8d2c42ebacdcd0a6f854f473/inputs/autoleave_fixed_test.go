package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 "reflect"
 "runtime"
 "strconv"
 pb "go.etcd.io/raft/v3/raftpb"
)

// This driver uses only public mutation APIs. Private fields are observations.
// MemoryStorage models successful storage completion; there are no crashes.
type assuranceAutoNode struct { rn *RawNode; storage *MemoryStorage }
type assuranceAutoCluster struct {
 t *testing.T
 nodes map[uint64]*assuranceAutoNode
 queue []pb.Message
 transfer bool
 injected bool
 dropped int
 leaveEntries int
 ticks int
 caseID string
 configurationIndex uint64
 applied map[uint64][]pb.Entry
 deliveries map[string]int
 cycleMessages []string
 recording bool
}
func (c *assuranceAutoCluster) event(phase string, extra map[string]interface{}) {
 r:=c.nodes[1].rn.raft
 e:=map[string]interface{}{"event":phase,"operation_id":c.caseID+"/implicit-remove-3","configuration_index":c.configurationIndex,"case":c.caseID,"phase":phase,"term":r.Term,"role":r.state.String(),"lead":r.lead,"transfer":r.leadTransferee,"commit":r.raftLog.committed,"applied":r.raftLog.applied,"last":r.raftLog.lastIndex(),"pending_conf":r.pendingConfIndex,"config":r.trk.ConfState(),"queue":len(c.queue),"ticks":c.ticks,"dropped_timeout_now":c.dropped,"leave_entries":c.leaveEntries}
 for k,v:=range extra {e[k]=v}
 b,err:=json.Marshal(e);if err!=nil {c.t.Fatal(err)};fmt.Println("CA_EVENT "+string(b))
}
func (c *assuranceAutoCluster) drain() {
 for rounds:=0;rounds<10000;rounds++ {
  work:=false
  for id:=uint64(1);id<=3;id++ {
   n:=c.nodes[id]
   if !n.rn.HasReady(){continue};work=true
   rd:=n.rn.Ready()
   if !IsEmptySnap(rd.Snapshot){c.t.Fatal("unexpected snapshot")}
   if err:=n.storage.Append(rd.Entries);err!=nil{c.t.Fatal(err)}
   if !IsEmptyHardState(rd.HardState){if err:=n.storage.SetHardState(rd.HardState);err!=nil{c.t.Fatal(err)}}
   // Persist before sending all messages, including election/append replies.
   c.queue=append(c.queue,rd.Messages...)
   for _,e:=range rd.Entries {
    if id==1 && e.Type==pb.EntryConfChangeV2 {
     var cc pb.ConfChangeV2;if err:=cc.Unmarshal(e.Data);err!=nil{c.t.Fatal(err)}
     if cc.LeaveJoint(){c.leaveEntries++}
    }
   }
   for _,e:=range rd.CommittedEntries {
    c.applied[id]=append(c.applied[id],e)
    switch e.Type {
    case pb.EntryConfChange:
     var cc pb.ConfChange;if err:=cc.Unmarshal(e.Data);err!=nil{c.t.Fatal(err)};n.rn.ApplyConfChange(cc)
    case pb.EntryConfChangeV2:
     var cc pb.ConfChangeV2;if err:=cc.Unmarshal(e.Data);err!=nil{c.t.Fatal(err)};n.rn.ApplyConfChange(cc)
     if id==1 && cc.Transition==pb.ConfChangeTransitionJointImplicit && !c.injected {
      c.injected=true
      c.configurationIndex=e.Index
      c.event("joint_applied_before_advance",nil)
      if c.transfer {n.rn.TransferLeader(2);c.event("transfer_requested",nil)}
     }
    }
   }
   n.rn.Advance(rd)
  }
  if len(c.queue)>0 {
   work=true
   m:=c.queue[0];c.queue=c.queue[1:]
   // Only TimeoutNow is lost. Heartbeats and replication remain reliable.
   if c.transfer && c.dropped==0 && m.Type==pb.MsgTimeoutNow {c.dropped++;continue}
   key:=fmt.Sprintf("%d>%d:%s",m.From,m.To,m.Type)
   c.deliveries[key]++
   if c.recording { b,err:=json.Marshal(m);if err!=nil{c.t.Fatal(err)};c.cycleMessages=append(c.cycleMessages,string(b)) }
   n:=c.nodes[m.To];if n==nil{c.t.Fatalf("unknown destination %d",m.To)}
   if err:=n.rn.Step(m);err!=nil && err!=ErrStepPeerNotFound {c.t.Fatal(err)}
  }
  if !work {return}
 }
 c.t.Fatal("driver drain limit; not a protocol result")
}
func (c *assuranceAutoCluster) tick() {
 for id:=uint64(1);id<=3;id++ {c.nodes[id].rn.Tick()}
 c.ticks++;c.drain()
}
func TestAssuranceAutoLeaveRecurrence(t *testing.T) {
 for _,transfer:=range []bool{false,true} {
  name:="without_transfer";if transfer{name="aborted_transfer"}
  t.Run(name,func(t *testing.T){
   c:=&assuranceAutoCluster{t:t,nodes:map[uint64]*assuranceAutoNode{},transfer:transfer,caseID:name,applied:map[uint64][]pb.Entry{},deliveries:map[string]int{}}
   peers:=[]Peer{{ID:1},{ID:2},{ID:3}}
   for id:=uint64(1);id<=3;id++ {
    s:=NewMemoryStorage()
    rn,err:=NewRawNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:s,MaxSizePerMsg:4096,MaxInflightMsgs:256,CheckQuorum:true})
    if err!=nil{t.Fatal(err)};if err=rn.Bootstrap(peers);err!=nil{t.Fatal(err)}
    c.nodes[id]=&assuranceAutoNode{rn:rn,storage:s}
   }
   c.drain();if err:=c.nodes[1].rn.Campaign();err!=nil{t.Fatal(err)};c.drain()
   if c.nodes[1].rn.raft.state!=StateLeader {t.Fatal("election prerequisite failed")}
   c.event("elected",nil)
   cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}}
   if err:=c.nodes[1].rn.ProposeConfChange(cc);err!=nil{t.Fatal(err)}
   c.drain();if !c.injected{t.Fatal("joint application prerequisite not reached")}
   c.event("operation_admitted",map[string]interface{}{"entered":c.injected,"all_work_drained":!c.anyReady() && len(c.queue)==0})
   for i:=0;i<20;i++ {c.tick()}
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
   if transfer {
    if err:=c.nodes[1].rn.Propose([]byte("independent rescue command"));err!=nil{t.Fatal(err)}
    c.drain();c.event("after_rescue_proposal",map[string]interface{}{"exited":!leader.trk.AutoLeave && len(leader.trk.Voters[1])==0})
   }
  })
 }
}

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
