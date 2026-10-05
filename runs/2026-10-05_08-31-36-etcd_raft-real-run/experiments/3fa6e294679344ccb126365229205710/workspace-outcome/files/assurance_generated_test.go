package raft

import (
 "encoding/json"
 "fmt"
 "testing"
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
}

func (e *assuranceAutoEnv) emit(kind string, more map[string]interface{}) {
 m:=map[string]interface{}{"kind":kind,"scenario":e.name,"tick":e.tick}
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
    e.triggered=true; e.confIndex=ent.Index
    if e.transfer {
     // Caller operations remain serialized. Node.run also permits transfer
     // messages while an earlier Ready is awaiting Advance.
     n.TransferLeader(2)
     e.emit("transfer_started_before_advance",map[string]interface{}{"node":id,"index":ent.Index,"transferee":n.BasicStatus().LeadTransferee,"auto_leave":n.Status().Config.AutoLeave})
    }
   }
  }
  e.applied[id]=ent.Index
 }
 // Persistence and application are complete before network publication/Advance.
 for _,m:=range rd.Messages {e.enqueue(m)}
 n.Advance(rd)
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
    if err:=n.Step(m);err!=nil && err!=ErrStepPeerNotFound {e.t.Fatal(err)}
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
  "auto_leave":s.Config.AutoLeave,"incoming":s.Config.Voters[0].Slice(),"outgoing":s.Config.Voters[1].Slice(),
  "last":r.raftLog.lastIndex(),"committed":s.Commit,"applied":s.Applied,"applying":r.raftLog.applying,
  "pending_conf":r.pendingConfIndex,"conf_index":e.confIndex,"network_pending":len(e.queue),"ready_nodes":pending,
  "self_pending_advance":len(n.stepsOnAdvance),"unstable_entries":len(r.raftLog.unstable.entries),
  "dropped":e.dropped,"delivered":e.delivered,"election_elapsed":r.electionElapsed,"heartbeat_elapsed":r.heartbeatElapsed,
 })
}
func TestAssuranceAutoLeaveExploration(t *testing.T) {
 for _,transfer:=range []bool{false,true} {
  name:="control";if transfer{name="failed_transfer"}
  t.Run(name,func(t *testing.T){
   e:=&assuranceAutoEnv{t:t,name:name,nodes:map[uint64]*RawNode{},stores:map[uint64]*MemoryStorage{},applied:map[uint64]uint64{},transfer:transfer,fault:transfer}
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
   for tick:=1;tick<=40;tick++ {
    e.tick=tick
    // Fixed loss window ends before tick 11 regardless of observations.
    if tick==11 {e.fault=false}
    for id:=uint64(1);id<=3;id++ {e.nodes[id].Tick()}
    e.drain()
    if tick==10 || tick==20 || tick==40 {e.observe("quiet_checkpoint")}
   }
   e.observe("before_rescue")
   if err:=e.nodes[1].Propose([]byte("diagnostic new client work"));err!=nil{t.Fatal(err)}
   e.drain()
   e.observe("after_rescue")
  })
 }
}
