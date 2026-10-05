package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 "reflect"
 "sort"
 pb "go.etcd.io/raft/v3/raftpb"
)

// This driver models serialized RawNode callers and a FIFO in-memory network.
// MemoryStorage completion substitutes for durable storage in this no-crash run.
type assuranceAutoEnv struct {
 t *testing.T
 name string
 nodes map[uint64]*RawNode
 stores map[uint64]*MemoryStorage
 queue []pb.Message
 transfer bool
 triggered bool
 fault bool
 dropped int
 tick int
 confIndex uint64
 applied map[uint64]uint64
 delivered int
 suffixOnlyHeartbeats bool
 suffixErrors int
 suffixDeliveries int
 cycleStart string
 startPending bool
}

func (e *assuranceAutoEnv) emit(kind string, more map[string]interface{}) {
 m:=map[string]interface{}{"event":kind,"kind":kind,"scenario":e.name,"node":uint64(1),"conf_index":e.confIndex,"tick":e.tick,"policy_transfer":e.transfer}
 for k,v:=range more {m[k]=v}
 b,err:=json.Marshal(m); if err!=nil {e.t.Fatal(err)}
 fmt.Println("CA_EVENT "+string(b))
}
func (e *assuranceAutoEnv) enqueue(m pb.Message) {
 // Use actual serialization to give transport immutable owned message bytes.
 b,err:=m.Marshal(); if err!=nil {e.t.Fatal(err)}
 var cp pb.Message; if err=cp.Unmarshal(b); err!=nil {e.t.Fatal(err)}
 e.queue=append(e.queue,cp)
}
func (e *assuranceAutoEnv) ready(id uint64) bool {
 n:=e.nodes[id]
 if !n.HasReady() {return false}
 rd:=n.Ready()
 admitted:=false
 if !IsEmptySnap(rd.Snapshot) {
  if err:=e.stores[id].ApplySnapshot(rd.Snapshot); err!=nil {e.t.Fatal(err)}
  e.applied[id]=rd.Snapshot.Metadata.Index
 }
 if err:=e.stores[id].Append(rd.Entries); err!=nil {e.t.Fatal(err)}
 if !IsEmptyHardState(rd.HardState) {if err:=e.stores[id].SetHardState(rd.HardState);err!=nil {e.t.Fatal(err)}}
 for _,ent:=range rd.CommittedEntries {
  if ent.Index!=e.applied[id]+1 {e.t.Fatalf("node %d nonconsecutive apply %d after %d",id,ent.Index,e.applied[id])}
  switch ent.Type {
  case pb.EntryConfChange:
   var cc pb.ConfChange; if err:=cc.Unmarshal(ent.Data);err!=nil {e.t.Fatal(err)}
   n.ApplyConfChange(cc)
  case pb.EntryConfChangeV2:
   var cc pb.ConfChangeV2; if err:=cc.Unmarshal(ent.Data);err!=nil {e.t.Fatal(err)}
   cs:=n.ApplyConfChange(cc)
   e.emit("configuration_applied",map[string]interface{}{"node":id,"index":ent.Index,"auto_leave":cs.AutoLeave,"incoming":cs.Voters,"outgoing":cs.VotersOutgoing})
   if id==1 && len(cc.Changes)>0 && !e.triggered {
    e.triggered=true; e.confIndex=ent.Index; admitted=true
    if e.transfer {
     // Caller operations remain serialized. Node.run also permits transfer
     // messages while an earlier Ready is awaiting Advance.
     n.TransferLeader(2)
     e.emit("transfer_started_before_advance",map[string]interface{}{"node":id,"index":ent.Index,"transferee":n.BasicStatus().LeadTransferee,"auto_leave":n.raft.trk.Config.AutoLeave})
    }
   }
  }
  e.applied[id]=ent.Index
 }
 // Persistence and application are complete before network publication/Advance.
 for _,m:=range rd.Messages {e.enqueue(m)}
 n.Advance(rd)
 if admitted {e.emit("joint_admitted",map[string]interface{}{"live_auto_leave":n.raft.trk.Config.AutoLeave,"joint":len(n.raft.trk.Config.Voters[1])>0,"applied":n.raft.raftLog.applied,"term":n.raft.Term,"transfer_active":n.raft.leadTransferee==2,"role":n.raft.state.String()})}
 return true
}
func (e *assuranceAutoEnv) drain() {
 for steps:=0;steps<20000;steps++ {
  work:=false
  for id:=uint64(1);id<=3;id++ {if e.ready(id) {work=true}}
  if len(e.queue)>0 {
   work=true
   m:=e.queue[0];e.queue=e.queue[1:]
   if e.fault && m.Type==pb.MsgTimeoutNow {
    e.dropped++
    e.emit("network_drop",map[string]interface{}{"from":m.From,"to":m.To,"type":m.Type.String(),"term":m.Term})
   } else {
    n:=e.nodes[m.To];if n==nil {e.t.Fatalf("unknown target %d",m.To)}
    err:=n.Step(m)
    if e.tick>20 && e.tick<=30 {
     e.suffixDeliveries++
     if err!=nil {e.suffixErrors++}
     if m.Type!=pb.MsgHeartbeat && m.Type!=pb.MsgHeartbeatResp {e.suffixOnlyHeartbeats=false}
    }
    if err!=nil && err!=ErrStepPeerNotFound {e.t.Fatal(err)}
    e.delivered++
   }
  }
  if !work {return}
 }
 e.t.Fatal("drain exceeded step limit; no quiescence observation")
}
func (e *assuranceAutoEnv) observe(kind string) {
 n:=e.nodes[1];r:=n.raft;s:=n.Status()
 pending:=0
 for _,rn:=range e.nodes {if rn.HasReady(){pending++}}
 e.emit(kind,map[string]interface{}{
  "node":uint64(1),"term":s.Term,"role":s.RaftState.String(),"transferee":s.LeadTransferee,
  "live_auto_leave":r.trk.Config.AutoLeave,"status_auto_leave":s.Config.AutoLeave,"incoming":s.Config.Voters[0].Slice(),"outgoing":s.Config.Voters[1].Slice(),
  "last":r.raftLog.lastIndex(),"committed":s.Commit,"applied":s.Applied,"applying":r.raftLog.applying,
  "pending_conf":r.pendingConfIndex,"conf_index":e.confIndex,"network_pending":len(e.queue),"ready_nodes":pending,
  "self_pending_advance":len(n.stepsOnAdvance),"unstable_entries":len(r.raftLog.unstable.entries),
  "dropped":e.dropped,"delivered":e.delivered,"election_elapsed":r.electionElapsed,"heartbeat_elapsed":r.heartbeatElapsed,
 })
}
func TestAssuranceAutoLeaveFixed(t *testing.T) {
 for _,transfer:=range []bool{false,true} {
  name:="control";if transfer{name="failed_transfer"}
  t.Run(name,func(t *testing.T){
   e:=&assuranceAutoEnv{t:t,name:name,nodes:map[uint64]*RawNode{},stores:map[uint64]*MemoryStorage{},applied:map[uint64]uint64{},transfer:transfer,fault:transfer,suffixOnlyHeartbeats:true}
   for id:=uint64(1);id<=3;id++ {
    s:=NewMemoryStorage()
    n,err:=NewRawNode(&Config{ID:id,Storage:s,ElectionTick:10,HeartbeatTick:1,MaxSizePerMsg:4096,MaxInflightMsgs:256,CheckQuorum:true,PreVote:true})
    if err!=nil{t.Fatal(err)}
    if err=n.Bootstrap([]Peer{{ID:1},{ID:2},{ID:3}});err!=nil{t.Fatal(err)}
    e.nodes[id]=n;e.stores[id]=s
   }
   // RawNodes start no goroutines and need no Stop. All queues are owned here.
   e.drain()
   if err:=e.nodes[1].Campaign();err!=nil{t.Fatal(err)}
   e.drain()
   if e.nodes[1].BasicStatus().RaftState!=StateLeader {t.Fatal("campaign did not produce leader")}
   e.observe("initialized")
   cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}}
   if err:=e.nodes[1].ProposeConfChange(cc);err!=nil{t.Fatal(err)}
   e.drain()
   if !e.triggered {t.Fatal("joint-entry application not reached")}
   e.observe("after_joint_application")
   for tick:=1;tick<=30;tick++ {
    e.tick=tick
    // Fixed loss window ends before tick 11 regardless of observations.
    if tick==11 {e.fault=false}
    for id:=uint64(1);id<=3;id++ {e.nodes[id].Tick()}
    e.drain()
    if tick==10 || tick==20 || tick==30 {e.observe("quiet_checkpoint")}
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
    }
   }
   e.observe("before_rescue")
   if err:=e.nodes[1].Propose([]byte("diagnostic new client work"));err!=nil{t.Fatal(err)}
   e.drain()
   e.observe("after_rescue")
  })
 }
}

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
