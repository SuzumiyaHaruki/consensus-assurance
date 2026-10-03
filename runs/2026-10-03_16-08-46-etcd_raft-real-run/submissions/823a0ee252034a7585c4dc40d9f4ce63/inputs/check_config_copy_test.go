package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssuranceStatusConfigurationCopy(t *testing.T) {
 for _,mode:=range []pb.ConfChangeTransition{pb.ConfChangeTransitionJointImplicit,pb.ConfChangeTransitionJointExplicit} {
  name:=mode.String()
  t.Run(name,func(t *testing.T){
   must:=func(err error){if err!=nil{t.Fatal(err)}}
   emit:=func(event string,f map[string]interface{}){f["event"]=event;f["case"]=name;b,err:=json.Marshal(f);must(err);fmt.Println("CA_EVENT "+string(b))}
   nodes:=map[uint64]*RawNode{};stores:=map[uint64]*MemoryStorage{}
   for id:=uint64(1);id<=3;id++ {
    st:=NewMemoryStorage();stores[id]=st
    n,err:=NewRawNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:st,MaxSizePerMsg:4096,MaxInflightMsgs:16});must(err);nodes[id]=n
    must(n.Bootstrap([]Peer{{ID:1},{ID:2},{ID:3}}))
   }
   observed:=0
   pump:=func(){
    for round:=0;round<10000;round++ {
     did:=false;var messages []pb.Message
     for id:=uint64(1);id<=3;id++ {
      n:=nodes[id];if !n.HasReady(){continue};did=true
      rd:=n.Ready();if !IsEmptySnap(rd.Snapshot){t.Fatal("unexpected snapshot in uncompacted history")}
      must(stores[id].Append(rd.Entries));if !IsEmptyHardState(rd.HardState){must(stores[id].SetHardState(rd.HardState))}
      for _,m:=range rd.Messages {b,err:=m.Marshal();must(err);var detached pb.Message;must(detached.Unmarshal(b));messages=append(messages,detached)}
      for _,ent:=range rd.CommittedEntries {
       switch ent.Type {
       case pb.EntryConfChange:
        var cc pb.ConfChange;must(cc.Unmarshal(ent.Data));n.ApplyConfChange(cc)
       case pb.EntryConfChangeV2:
        var cc pb.ConfChangeV2;must(cc.Unmarshal(ent.Data));cs:=n.ApplyConfChange(cc)
        if id==1&&len(cc.Changes)>0 {
         observed++
         // Capture the established live source value before copying it. No
         // protocol operation occurs between this admission and Status below.
         live:=n.raft.trk.AutoLeave
         emit("copy_admitted",map[string]interface{}{"operation":"committed-remove-3","node":id,"index":ent.Index,"entry_term":ent.Term,"source_auto_leave":live,"apply_return_auto_leave":cs.AutoLeave,"joint":len(cs.VotersOutgoing)>0,"mode":cc.Transition.String(),"commit":n.BasicStatus().Commit})
         status:=n.Status()
         direct:=n.raft.trk.Config.Clone()
         emit("copy_result",map[string]interface{}{"operation":"committed-remove-3","node":id,"index":ent.Index,"entry_term":ent.Term,"copied_auto_leave":status.Config.AutoLeave,"direct_clone_auto_leave":direct.AutoLeave,"live_after":n.raft.trk.AutoLeave,"voters":status.Config.Voters[0].Slice(),"outgoing":status.Config.Voters[1].Slice()})
        }
       }
      }
      n.Advance(rd)
     }
     for _,m:=range messages {
      n:=nodes[m.To];if n==nil{t.Fatalf("unknown recipient %d",m.To)}
      err:=n.Step(m)
      if err==ErrStepPeerNotFound {emit("removed_peer_reply",map[string]interface{}{"from":m.From,"to":m.To,"type":m.Type.String()})} else {must(err)}
     }
     if !did {return}
    }
    t.Fatal("driver operation bound reached")
   }
   pump();must(nodes[1].Campaign());pump()
   if nodes[1].BasicStatus().RaftState!=StateLeader{t.Fatal("node 1 was not elected")}
   must(nodes[1].ProposeConfChange(pb.ConfChangeV2{Transition:mode,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}}))
   pump();if observed!=1{t.Fatalf("expected one source application, got %d",observed)}
  })
 }
}
