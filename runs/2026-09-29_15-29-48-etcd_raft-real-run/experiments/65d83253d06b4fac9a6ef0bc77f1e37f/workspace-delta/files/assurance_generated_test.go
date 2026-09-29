package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssuranceRemovedLeaderReadExplore(t *testing.T) {
 for _,stepDown:=range []bool{false,true} { t.Run(fmt.Sprint(stepDown),func(t *testing.T){
  nodes:=map[uint64]*RawNode{}
  stores:=map[uint64]*MemoryStorage{}
  values:=map[uint64]string{}
  applied:=map[uint64]uint64{1:1,2:1}
  var reads []ReadState
  emit:=func(event string,id uint64,extra map[string]interface{}) {
   r:=nodes[id].raft
   row:=map[string]interface{}{"event":event,"node":id,"step_down":stepDown,"term":r.Term,"role":r.state.String(),"leader":r.lead,"commit":r.raftLog.committed,"app_index":applied[id],"value":values[id],"voters":r.trk.VoterNodes()}
   for k,v:=range extra {row[k]=v}; b,err:=json.Marshal(row);if err!=nil{t.Fatal(err)};fmt.Println("CA_EVENT "+string(b))
  }
  for id:=uint64(1);id<=2;id++ {
   st:=NewMemoryStorage()
   if err:=st.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1,2}}}});err!=nil{t.Fatal(err)}
   if err:=st.SetHardState(pb.HardState{Term:1,Commit:1});err!=nil{t.Fatal(err)}
   rn,err:=NewRawNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:st,Applied:1,AsyncStorageWrites:true,StepDownOnRemoval:stepDown,ReadOnlyOption:ReadOnlySafe,MaxSizePerMsg:4096,MaxInflightMsgs:16});if err!=nil{t.Fatal(err)}
   nodes[id],stores[id]=rn,st
  }
  var queue []pb.Message
  pump:=func(){
   for n:=0;;n++ {
    if n>10000{t.Fatal("finite exploration schedule exceeded")}
    work:=false
    for id:=uint64(1);id<=2;id++ {
     rn:=nodes[id];if !rn.HasReady(){continue};work=true;rd:=rn.Ready()
     for _,rs:=range rd.ReadStates { reads=append(reads,rs);emit("read_state",id,map[string]interface{}{"read_index":rs.Index,"context":string(rs.RequestCtx)}) }
     for _,m:=range rd.Messages {
      switch m.Type {
      case pb.MsgStorageAppend:
       st:=stores[id]
       if m.Snapshot!=nil{if err:=st.ApplySnapshot(*m.Snapshot);err!=nil{t.Fatal(err)}}
       if err:=st.Append(m.Entries);err!=nil{t.Fatal(err)}
       hs:=pb.HardState{Term:m.Term,Vote:m.Vote,Commit:m.Commit}
       if !IsEmptyHardState(hs){if err:=st.SetHardState(hs);err!=nil{t.Fatal(err)}}
       queue=append(queue,m.Responses...)
      case pb.MsgStorageApply:
       for _,e:=range m.Entries {
        if e.Index!=applied[id]+1 {t.Fatalf("nonconsecutive application: %d after %d",e.Index,applied[id])}
        switch e.Type {
        case pb.EntryConfChange:
         var cc pb.ConfChange;if err:=cc.Unmarshal(e.Data);err!=nil{t.Fatal(err)};rn.ApplyConfChange(cc)
        case pb.EntryConfChangeV2:
         var cc pb.ConfChangeV2;if err:=cc.Unmarshal(e.Data);err!=nil{t.Fatal(err)};rn.ApplyConfChange(cc)
        case pb.EntryNormal:
         if len(e.Data)>0{values[id]=string(e.Data)}
        }
        applied[id]=e.Index
        emit("applied",id,map[string]interface{}{"entry_index":e.Index,"entry_type":e.Type.String()})
       }
       queue=append(queue,m.Responses...)
      default:queue=append(queue,m)
      }
     }
    }
    if len(queue)>0 {m:=queue[0];queue=queue[1:];if err:=nodes[m.To].Step(m);err!=nil{t.Fatal(err)};continue}
    if !work{return}
   }
  }
  if err:=nodes[1].Campaign();err!=nil{t.Fatal(err)};pump()
  if nodes[1].raft.state!=StateLeader{t.Fatal("node 1 not elected")}
  if err:=nodes[1].Propose([]byte("old"));err!=nil{t.Fatal(err)};pump()
  if err:=nodes[1].ProposeConfChange(pb.ConfChange{Type:pb.ConfChangeRemoveNode,NodeID:1});err!=nil{t.Fatal(err)};pump()
  emit("after_removal",1,nil);emit("after_removal",2,nil)
  if nodes[2].raft.trk.Progress[1]!=nil {t.Fatal("removal not applied on successor")}
  if err:=nodes[2].Campaign();err!=nil{t.Fatal(err)};pump()
  if nodes[2].raft.state!=StateLeader{t.Fatal("node 2 not elected")}
  if err:=nodes[2].Propose([]byte("new"));err!=nil{t.Fatal(err)};pump()
  emit("write_complete",2,nil)
  emit("read_invoked",1,map[string]interface{}{"context":"after-new-write","new_write_index":applied[2]})
  nodes[1].ReadIndex([]byte("after-new-write"));pump()
  emit("finished",1,map[string]interface{}{"read_states":len(reads),"new_write_index":applied[2]})
 }) }
}
