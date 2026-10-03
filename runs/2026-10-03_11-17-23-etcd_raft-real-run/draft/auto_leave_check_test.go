package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssuranceAutoLeaveTransfer(t *testing.T) {
 for _, transfer := range []bool{false,true} {
  name := "control"
  if transfer { name = "transfer_timeout" }
  t.Run(name,func(t *testing.T) {
   nodes:=map[uint64]*RawNode{}
   stores:=map[uint64]*MemoryStorage{}
   jointIndex:=uint64(0)
   tickNumber:=0
   startTerm:=uint64(0)
   stableAuthority:=true
   heartbeatAcks:=map[uint64]int{}
   exitEntries:=0
   emit:=func(stage string) {
    r:=nodes[1].raft
    out:=map[string]interface{}{"event":stage,"case":name,"joint_index":jointIndex,"tick":tickNumber,"stable_authority":stableAuthority,"acks2":heartbeatAcks[2],"acks3":heartbeatAcks[3],"exit_entries":exitEntries,"stage":stage,"term":r.Term,"role":r.state.String(),"commit":r.raftLog.committed,"applied":r.raftLog.applied,"last":r.raftLog.lastIndex(),"transferee":r.leadTransferee,"auto_leave":r.trk.AutoLeave,"outgoing":len(r.trk.Voters[1])}
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
      if id==1 {for _,e:=range rd.Entries {if e.Type==pb.EntryConfChangeV2 {var cc pb.ConfChangeV2;if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)};if cc.LeaveJoint(){exitEntries++}}}}
      for _,e:=range rd.CommittedEntries {
       if e.Type==pb.EntryConfChangeV2 {
        var cc pb.ConfChangeV2
        if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)}
        rn.ApplyConfChange(cc)
        if id==1 && !hooked && cc.Transition==pb.ConfChangeTransitionJointImplicit {
         hooked=true
         jointIndex=e.Index
         emit("joint_installed_before_advance")
         if transfer {rn.TransferLeader(2);emit("transfer_started_before_advance")}
         emit("admitted")
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
        if m.To==1 && m.Type==pb.MsgHeartbeatResp && m.Term==nodes[1].raft.Term {heartbeatAcks[m.From]++}
       }
      }
     }
     if startTerm!=0 && (nodes[1].raft.Term!=startTerm || nodes[1].raft.state!=StateLeader) {stableAuthority=false}
     if !work{return}
    }
    t.Fatal("exploration failed to quiesce within pump bound")
   }
   if err:=nodes[1].Campaign();err!=nil {t.Fatal(err)};pump()
   if nodes[1].raft.state!=StateLeader {t.Fatal("leader not established")}
   startTerm=nodes[1].raft.Term
   emit("elected")
   cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}}
   if err:=nodes[1].ProposeConfChange(cc);err!=nil {t.Fatal(err)};pump()
   if !hooked {t.Fatal("joint application not reached")}
   emit("after_joint_completion")
   for tick:=1;tick<=40;tick++ {
    tickNumber=tick
    for id:=uint64(1);id<=3;id++ {nodes[id].Tick()}
    pump()
    if tick==10 || tick==20 {emit(fmt.Sprintf("after_tick_%d",tick))}
   }
   emit("result")
   fmt.Printf("CA_EVENT {\"event\":\"diagnostics\",\"case\":%q,\"joint_index\":%d,\"dropped_timeout_now\":%d,\"queue_remaining\":%d}\n",name,jointIndex,dropped,len(queue))
   // Independent rescue observation tests whether new application work supplies the trigger.
   if err:=nodes[1].Propose([]byte("wake-application"));err!=nil {t.Fatal(err)};pump();emit("after_rescue_proposal")
  })
 }
}
