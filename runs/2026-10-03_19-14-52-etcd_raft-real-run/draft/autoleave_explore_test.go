package raft

import (
 "encoding/json"
 "fmt"
 "testing"
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
}
func (c *assuranceAutoCluster) event(phase string, extra map[string]interface{}) {
 r:=c.nodes[1].rn.raft
 e:=map[string]interface{}{"case":c.caseID,"phase":phase,"term":r.Term,"role":r.state.String(),"lead":r.lead,"transfer":r.leadTransferee,"commit":r.raftLog.committed,"applied":r.raftLog.applied,"last":r.raftLog.lastIndex(),"pending_conf":r.pendingConfIndex,"config":r.trk.ConfState(),"queue":len(c.queue),"ticks":c.ticks,"dropped_timeout_now":c.dropped,"leave_entries":c.leaveEntries}
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
    switch e.Type {
    case pb.EntryConfChange:
     var cc pb.ConfChange;if err:=cc.Unmarshal(e.Data);err!=nil{c.t.Fatal(err)};n.rn.ApplyConfChange(cc)
    case pb.EntryConfChangeV2:
     var cc pb.ConfChangeV2;if err:=cc.Unmarshal(e.Data);err!=nil{c.t.Fatal(err)};n.rn.ApplyConfChange(cc)
     if id==1 && cc.Transition==pb.ConfChangeTransitionJointImplicit && !c.injected {
      c.injected=true
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
   if c.transfer && m.Type==pb.MsgTimeoutNow {c.dropped++;continue}
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
func TestAssuranceAutoLeaveExploration(t *testing.T) {
 for _,transfer:=range []bool{false,true} {
  name:="without_transfer";if transfer{name="aborted_transfer"}
  t.Run(name,func(t *testing.T){
   c:=&assuranceAutoCluster{t:t,nodes:map[uint64]*assuranceAutoNode{},transfer:transfer,caseID:name}
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
   c.event("initial_drain",nil)
   for i:=0;i<40;i++ {c.tick();if c.ticks%10==0{c.event("tick_boundary",nil)}}
   ready:=false;for _,n:=range c.nodes{ready=ready||n.rn.HasReady()}
   c.event("bounded_suffix",map[string]interface{}{"any_ready":ready})
   if transfer {
    if err:=c.nodes[1].rn.Propose([]byte("independent rescue command"));err!=nil{t.Fatal(err)}
    c.drain();c.event("after_rescue_proposal",nil)
   }
  })
 }
}
