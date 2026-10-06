package raft

import (
 "encoding/json"
 "fmt"
 "testing"
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
}
func assuranceEmit(kind string, fields map[string]interface{}) {
 fields["kind"] = kind
 b, err := json.Marshal(fields); if err != nil { panic(err) }
 fmt.Println("CA_EVENT " + string(b))
}
func assuranceNew(t *testing.T, transfer bool) *assuranceCluster {
 c := &assuranceCluster{t:t,nodes:map[uint64]*RawNode{},stores:map[uint64]*MemoryStorage{},transfer:transfer}
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
func TestAssuranceAutoExitExplore(t *testing.T){
 for _,transfer:=range []bool{false,true}{
  t.Run(fmt.Sprintf("transfer_%v",transfer),func(t *testing.T){
   c:=assuranceNew(t,transfer)
   if err:=c.nodes[1].Campaign();err!=nil{t.Fatal(err)};c.drain()
   if c.nodes[1].raft.state!=StateLeader{t.Fatal("campaign did not establish leader")}
   cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}}
   if err:=c.nodes[1].ProposeConfChange(cc);err!=nil{t.Fatal(err)};c.drain();c.observe("after_apply")
   // The removed node is decommissioned; the surviving quorum continues ticking.
   for i:=0;i<40;i++ {c.nodes[1].Tick();c.nodes[2].Tick();c.ticks++;c.drain();if c.ticks%10==0{c.observe("idle_ticks")}}
   // Separate diagnostic stimulus; not assumed necessary caller work.
   if err:=c.nodes[1].Propose([]byte("diagnostic-rescue"));err!=nil{t.Fatal(err)};c.drain();c.observe("after_extra_proposal")
  })
 }
}
