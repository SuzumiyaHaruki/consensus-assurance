package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssuranceExploreAutoLeaveTransfer(t *testing.T) {
 for _, transfer := range []bool{false,true} {
  name := "control"
  if transfer { name = "transfer_timeout" }
  t.Run(name,func(t *testing.T) {
   nodes:=map[uint64]*RawNode{}
   stores:=map[uint64]*MemoryStorage{}
   emit:=func(stage string) {
    r:=nodes[1].raft
    out:=map[string]interface{}{"case":name,"stage":stage,"term":r.Term,"role":r.state.String(),"commit":r.raftLog.committed,"applied":r.raftLog.applied,"last":r.raftLog.lastIndex(),"transferee":r.leadTransferee,"auto_leave":r.trk.AutoLeave,"outgoing":len(r.trk.Voters[1])}
    b,_:=json.Marshal(out);fmt.Println("CA_EVENT "+string(b))
   }
   for id:=uint64(1);id<=3;id++ {
    st:=NewMemoryStorage()
    // Identical genesis snapshots establish the initial cluster. No crashes occur.
    if err:=st.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1,2,3}}}});err!=nil {t.Fatal(err)}
    if err:=st.SetHardState(pb.HardState{Term:1,Commit:1});err!=nil {t.Fatal(err)}
    rn,err:=NewRawNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:st,Applied:1,MaxSizePerMsg:4096,MaxInflightMsgs:256,CheckQuorum:true})
    if err!=nil {t.Fatal(err)}
    nodes[id]=rn;stores[id]=st
   }
   hooked:=false
   dropped:=0
   queue:=[]pb.Message{}
   pump:=func() {
    for round:=0;round<1000;round++ {
     work:=false
     for id:=uint64(1);id<=3;id++ {
      rn:=nodes[id]
      if !rn.HasReady(){continue};work=true
      rd:=rn.Ready()
      st:=stores[id]
      if !IsEmptySnap(rd.Snapshot) {if err:=st.ApplySnapshot(rd.Snapshot);err!=nil {t.Fatal(err)}}
      if !IsEmptyHardState(rd.HardState) {if err:=st.SetHardState(rd.HardState);err!=nil {t.Fatal(err)}}
      if err:=st.Append(rd.Entries);err!=nil {t.Fatal(err)}
      for _,e:=range rd.CommittedEntries {
       if e.Type==pb.EntryConfChangeV2 {
        var cc pb.ConfChangeV2
        if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)}
        rn.ApplyConfChange(cc)
        if id==1 && !hooked && cc.Transition==pb.ConfChangeTransitionJointImplicit {
         hooked=true
         emit("joint_installed_before_advance")
         if transfer {rn.TransferLeader(2);emit("transfer_started_before_advance")}
        }
       } else if e.Type==pb.EntryConfChange {
        var cc pb.ConfChange;if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)};rn.ApplyConfChange(cc)
       }
      }
      // Persistence and application finish before all message delivery and Advance.
      queue=append(queue,rd.Messages...)
      rn.Advance(rd)
     }
     if len(queue)>0 {
      work=true;batch:=queue;queue=nil
      for _,m:=range batch {
       // Only transfer-triggering packets are lost. All quorum traffic is delivered.
       if transfer && m.Type==pb.MsgTimeoutNow {dropped++;continue}
       if rn:=nodes[m.To];rn!=nil {
        if err:=rn.Step(m);err!=nil && err!=ErrStepPeerNotFound {t.Fatal(err)}
       }
      }
     }
     if !work{return}
    }
    t.Fatal("exploration failed to quiesce within pump bound")
   }
   if err:=nodes[1].Campaign();err!=nil {t.Fatal(err)};pump()
   if nodes[1].raft.state!=StateLeader {t.Fatal("leader not established")}
   emit("elected")
   cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}}
   if err:=nodes[1].ProposeConfChange(cc);err!=nil {t.Fatal(err)};pump()
   if !hooked {t.Fatal("joint application not reached")}
   emit("after_joint_completion")
   for tick:=1;tick<=40;tick++ {
    for id:=uint64(1);id<=3;id++ {nodes[id].Tick()}
    pump()
    if tick==10 || tick==20 || tick==40 {emit(fmt.Sprintf("after_tick_%d",tick))}
   }
   fmt.Printf("CA_EVENT {\"case\":%q,\"stage\":\"driver_summary\",\"dropped_timeout_now\":%d}\n",name,dropped)
   // Independent rescue observation tests whether new application work supplies the trigger.
   if err:=nodes[1].Propose([]byte("wake-application"));err!=nil {t.Fatal(err)};pump();emit("after_rescue_proposal")
  })
 }
}
