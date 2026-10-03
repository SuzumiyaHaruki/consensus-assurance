package raft

import (
 "bytes"
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssuranceRemovedReadFence(t *testing.T) {
 for _,stepDown:=range []bool{false,true} {
  name:="retained_role";if stepDown{name="stepdown_control"}
  t.Run(name,func(t *testing.T){
   nodes:=map[uint64]*RawNode{};stores:=map[uint64]*MemoryStorage{}
   values:=map[uint64]int{};applied:=map[uint64]uint64{}
   reads:=map[uint64][]ReadState{}
   writeIndex:=uint64(0)
   readID:="read-after-write-"+name
   emit:=func(stage string){
    r:=nodes[1].raft
    x:=map[string]interface{}{"event":stage,"case":name,"read_id":readID,"read_returned":len(reads[1])>0,"write_completed":writeIndex>0 && applied[2]>=writeIndex && values[2]==1,"covers_completed_write":false,"old_role":r.state.String(),"old_term":r.Term,"old_commit":r.raftLog.committed,"old_applied":applied[1],"old_value":values[1],"old_member":r.trk.Progress[1]!=nil,"old_voters":r.trk.VoterNodes(),"new_term":nodes[2].raft.Term,"new_role":nodes[2].raft.state.String(),"new_applied":applied[2],"new_value":values[2],"write_index":writeIndex,"read_count":len(reads[1])}
    if len(reads[1])>0{x["read_index"]=reads[1][len(reads[1])-1].Index;x["read_context"]=string(reads[1][len(reads[1])-1].RequestCtx);x["covers_completed_write"]=reads[1][len(reads[1])-1].Index>=writeIndex;x["applied_through_fence"]=applied[1]>=reads[1][len(reads[1])-1].Index}
    b,_:=json.Marshal(x);fmt.Println("CA_EVENT "+string(b))
   }
   for id:=uint64(1);id<=3;id++{
    st:=NewMemoryStorage()
    if err:=st.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1,2,3}}}});err!=nil{t.Fatal(err)}
    if err:=st.SetHardState(pb.HardState{Term:1,Commit:1});err!=nil{t.Fatal(err)}
    rn,err:=NewRawNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:st,Applied:1,MaxSizePerMsg:4096,MaxInflightMsgs:256,CheckQuorum:true,StepDownOnRemoval:stepDown,ReadOnlyOption:ReadOnlySafe});if err!=nil{t.Fatal(err)}
    nodes[id]=rn;stores[id]=st;applied[id]=1
   }
   pump:=func(){
    for rounds:=0;rounds<1000;rounds++{
     work:=false;var queue []pb.Message
     for id:=uint64(1);id<=3;id++{
      rn:=nodes[id];if !rn.HasReady(){continue};work=true;rd:=rn.Ready();st:=stores[id]
      if !IsEmptySnap(rd.Snapshot){if err:=st.ApplySnapshot(rd.Snapshot);err!=nil{t.Fatal(err)}}
      if !IsEmptyHardState(rd.HardState){if err:=st.SetHardState(rd.HardState);err!=nil{t.Fatal(err)}}
      if err:=st.Append(rd.Entries);err!=nil{t.Fatal(err)}
      for _,e:=range rd.CommittedEntries{
       switch e.Type{
       case pb.EntryConfChangeV2:var cc pb.ConfChangeV2;if err:=cc.Unmarshal(e.Data);err!=nil{t.Fatal(err)};rn.ApplyConfChange(cc)
       case pb.EntryConfChange:var cc pb.ConfChange;if err:=cc.Unmarshal(e.Data);err!=nil{t.Fatal(err)};rn.ApplyConfChange(cc)
       case pb.EntryNormal:if bytes.Equal(e.Data,[]byte("set-one")){values[id]=1;if id==2{writeIndex=e.Index}}
       }
       applied[id]=e.Index
      }
      reads[id]=append(reads[id],rd.ReadStates...)
      queue=append(queue,rd.Messages...);rn.Advance(rd)
     }
     for _,m:=range queue{if rn:=nodes[m.To];rn!=nil{if err:=rn.Step(m);err!=nil && err!=ErrStepPeerNotFound{t.Fatal(err)}}}
     if !work{return}
    }
    t.Fatal("pump did not drain")
   }
   if err:=nodes[1].Campaign();err!=nil{t.Fatal(err)};pump()
   if nodes[1].raft.state!=StateLeader{t.Fatal("initial election failed")}
   cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:1},{Type:pb.ConfChangeRemoveNode,NodeID:3}}}
   if err:=nodes[1].ProposeConfChange(cc);err!=nil{t.Fatal(err)};pump();emit("removed")
   if nodes[2].raft.trk.IsSingleton()!=true || nodes[2].raft.trk.Progress[1]!=nil{t.Fatal("final singleton configuration not reached")}
   if err:=nodes[2].Campaign();err!=nil{t.Fatal(err)};pump()
   if nodes[2].raft.state!=StateLeader{t.Fatal("successor not elected")}
   if err:=nodes[2].Propose([]byte("set-one"));err!=nil{t.Fatal(err)};pump()
   if writeIndex==0 || values[2]!=1{t.Fatal("write not applied")}
   emit("write_completed")
   emit("read_admitted")
   nodes[1].ReadIndex([]byte(readID));pump();emit("read_result")
  })
 }
}
