package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

// This driver uses actual RawNode outputs and a single FIFO delivery queue.
// Storage and application work finish synchronously before Advance.
func TestAssuranceAutoLeaveTransferExplore(t *testing.T) {
 for _, overlap := range []bool{false, true} {
  t.Run(fmt.Sprint(overlap), func(t *testing.T) {
   nodes := map[uint64]*RawNode{}
   stores := map[uint64]*MemoryStorage{}
   for id:=uint64(1); id<=3; id++ {
    st:=NewMemoryStorage()
    rn,err:=NewRawNode(&Config{ID:id, ElectionTick:10, HeartbeatTick:1, Storage:st, MaxSizePerMsg:4096, MaxInflightMsgs:256, CheckQuorum:true, PreVote:true})
    if err!=nil {t.Fatal(err)}
    if err=rn.Bootstrap([]Peer{{ID:1},{ID:2},{ID:3}});err!=nil {t.Fatal(err)}
    nodes[id]=rn;stores[id]=st
   }
   var queue []pb.Message
   hooked:=false
   dropped:=0
   changeIndex:=uint64(0)
   emit:=func(stage string) {
    r:=nodes[1].raft
    event:=map[string]interface{}{"stage":stage,"overlap":overlap,"term":r.Term,"role":r.state.String(),"applied":r.raftLog.applied,"committed":r.raftLog.committed,"last":r.raftLog.lastIndex(),"auto_leave":r.trk.Config.AutoLeave,"outgoing":r.trk.Config.Voters[1].Slice(),"incoming":r.trk.Config.Voters[0].Slice(),"transferee":r.leadTransferee,"pending_conf":r.pendingConfIndex,"change_index":changeIndex,"dropped_timeout_now":dropped,"queue_length":len(queue),"ready":nodes[1].HasReady()}
    data,err:=json.Marshal(event);if err!=nil {t.Fatal(err)}
    fmt.Println("CA_EVENT "+string(data))
   }
   pump:=func() {
    for round:=0;round<1000;round++ {
     progressed:=false
     for id:=uint64(1);id<=3;id++ {
      rn:=nodes[id];st:=stores[id]
      if !rn.HasReady(){continue};progressed=true
      rd:=rn.Ready()
      if !IsEmptySnap(rd.Snapshot) {if err:=st.ApplySnapshot(rd.Snapshot);err!=nil {t.Fatal(err)}}
      if err:=st.Append(rd.Entries);err!=nil {t.Fatal(err)}
      if !IsEmptyHardState(rd.HardState) {if err:=st.SetHardState(rd.HardState);err!=nil {t.Fatal(err)}}
      queue=append(queue,rd.Messages...)
      for _,ent:=range rd.CommittedEntries {
       switch ent.Type {
       case pb.EntryConfChange:
        var cc pb.ConfChange;if err:=cc.Unmarshal(ent.Data);err!=nil {t.Fatal(err)};rn.ApplyConfChange(cc)
       case pb.EntryConfChangeV2:
        var cc pb.ConfChangeV2;if err:=cc.Unmarshal(ent.Data);err!=nil {t.Fatal(err)};cs:=rn.ApplyConfChange(cc)
        if id==1 && cs.AutoLeave && !hooked {
         changeIndex=ent.Index;hooked=true
         if overlap {rn.TransferLeader(2)}
         emit("joint_applied_before_advance")
        }
       }
      }
      rn.Advance(rd)
     }
     if len(queue)>0 {
      m:=queue[0];queue=queue[1:];progressed=true
      // This is a network loss policy, never a fabricated response.
      if overlap && m.Type==pb.MsgTimeoutNow {dropped++} else if target:=nodes[m.To];target!=nil {
       err:=target.Step(m)
       // Removed peers may still have previously emitted responses in flight.
       if err!=nil && err!=ErrStepPeerNotFound {t.Fatal(err)}
      } else {t.Fatalf("unknown target %d",m.To)}
     }
     if !progressed {return}
    }
    t.Fatal("driver pump did not quiesce")
   }
   pump()
   if err:=nodes[1].Campaign();err!=nil {t.Fatal(err)};pump()
   if nodes[1].raft.state!=StateLeader || nodes[1].raft.raftLog.applied!=nodes[1].raft.raftLog.lastIndex(){t.Fatal("initial election/application incomplete")}
   cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit, Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}}
   if err:=nodes[1].ProposeConfChange(cc);err!=nil {t.Fatal(err)};pump()
   if !hooked {t.Fatal("joint entry was not applied")}
   emit("after_joint_drain")
   for tick:=0;tick<30;tick++ {
    for id:=uint64(1);id<=3;id++ {nodes[id].Tick()}
    pump()
    if tick==9 {emit("after_transfer_timeout")}
   }
   emit("after_30_ticks")
   if overlap {
    if err:=nodes[1].Propose([]byte("diagnostic continuation stimulus"));err!=nil {t.Fatal(err)};pump()
    emit("after_new_proposal")
   }
  })
 }
}
