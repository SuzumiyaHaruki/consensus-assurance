package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssuranceAutoLeaveTransferExploration(t *testing.T) {
 for _, overlap := range []bool{false,true} {
  name:="no_transfer";if overlap {name="transfer_overlap"}
  t.Run(name,func(t *testing.T) {
   type peer struct {rn *RawNode; st *MemoryStorage; applied uint64}
   peers:=map[uint64]*peer{}
   emit:=func(e map[string]interface{}) {e["scenario"]=name;b,err:=json.Marshal(e);if err!=nil {t.Fatal(err)};fmt.Println("CA_EVENT "+string(b))}
   for _,id:=range []uint64{1,2,3} {
    st:=NewMemoryStorage()
    if err:=st.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1,2,3}}}});err!=nil {t.Fatal(err)}
    if err:=st.SetHardState(pb.HardState{Term:1,Commit:1});err!=nil {t.Fatal(err)}
    rn,err:=NewRawNode(&Config{ID:id,Storage:st,Applied:1,ElectionTick:10,HeartbeatTick:1,MaxSizePerMsg:4096,MaxInflightMsgs:256})
    if err!=nil {t.Fatal(err)}
    peers[id]= &peer{rn:rn,st:st,applied:1}
   }
   blocked3:=false;hooked:=false
   var queue []pb.Message
   pump:=func() {
    for round:=0;round<300;round++ {
     work:=false
     for _,id:=range []uint64{1,2,3} {
      n:=peers[id];if !n.rn.HasReady() {continue};work=true
      rd:=n.rn.Ready()
      if !IsEmptySnap(rd.Snapshot) {t.Fatal("unexpected runtime snapshot")}
      if err:=n.st.Append(rd.Entries);err!=nil {t.Fatal(err)}
      if !IsEmptyHardState(rd.HardState) {if err:=n.st.SetHardState(rd.HardState);err!=nil {t.Fatal(err)}}
      for _,ent:=range rd.CommittedEntries {
       if ent.Index!=n.applied+1 {t.Fatal("application order")}
       if ent.Type==pb.EntryConfChangeV2 {
        var cc pb.ConfChangeV2;if err:=cc.Unmarshal(ent.Data);err!=nil {t.Fatal(err)}
        cs:=n.rn.ApplyConfChange(cc)
        emit(map[string]interface{}{"event":"configuration_applied","node":id,"index":ent.Index,"auto_leave":cs.AutoLeave,"incoming":cs.Voters,"outgoing":cs.VotersOutgoing,"learners":cs.Learners})
        if id==1 && cs.AutoLeave && overlap && !hooked {
         hooked=true
         n.rn.TransferLeader(3)
         s:=n.rn.Status()
         emit(map[string]interface{}{"event":"transfer_requested_before_advance","node":id,"target":s.LeadTransferee,"role":s.RaftState.String(),"configuration_index":ent.Index})
        }
       } else if ent.Type!=pb.EntryNormal {t.Fatal("unexpected entry")}
       n.applied=ent.Index
      }
      queue=append(queue,rd.Messages...)
      n.rn.Advance(rd)
     }
     if len(queue)>0 {
      work=true;msgs:=queue;queue=nil
      for _,m:=range msgs {
       if blocked3 && (m.From==3 || m.To==3) {continue}
       if err:=peers[m.To].rn.Step(m);err!=nil {t.Fatal(err)}
      }
     }
     if !work {return}
    }
    t.Fatal("work bound exceeded")
   }
   observe:=func(stage string) {
    n:=peers[1];s:=n.rn.Status();last,err:=n.st.LastIndex();if err!=nil {t.Fatal(err)}
    emit(map[string]interface{}{"event":"state_observed","stage":stage,"node":uint64(1),"role":s.RaftState.String(),"term":s.Term,"target":s.LeadTransferee,"auto_leave":s.Config.AutoLeave,"incoming":s.Config.Voters[0].Slice(),"outgoing":s.Config.Voters[1].Slice(),"applied":n.applied,"commit":s.Commit,"last_index":last})
   }
   if err:=peers[1].rn.Campaign();err!=nil {t.Fatal(err)};pump()
   if peers[1].rn.Status().RaftState!=StateLeader {t.Fatal("initial election")}
   blocked3=true
   cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeAddLearnerNode,NodeID:3}}}
   if err:=peers[1].rn.ProposeConfChange(cc);err!=nil {t.Fatal(err)};pump()
   observe("after_joint_application_and_drain")
   // Quorums {1,2} remain connected for both incoming and outgoing sets.
   // No new client entries arrive during this fixed 30-tick window.
   for i:=1;i<=30;i++ {
    peers[1].rn.Tick();peers[2].rn.Tick();pump()
    if i==10 || i==30 {observe(fmt.Sprintf("after_%d_ticks",i))}
   }
   // This separately labelled stimulus tests the hypothesized missing trigger,
   // and does not redefine the preceding heartbeat-only observation window.
   if err:=peers[1].rn.Propose([]byte("independent-application-stimulus"));err!=nil {t.Fatal(err)};pump()
   observe("after_new_application")
  })
 }
}
