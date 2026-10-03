package raft
import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)
func TestAssuranceStatusAutoLeaveCopy(t *testing.T) {
 for _,implicit:=range []bool{true,false} {
  name:="explicit"; transition:=pb.ConfChangeTransitionJointExplicit
  if implicit {name="implicit";transition=pb.ConfChangeTransitionJointImplicit}
  t.Run(name,func(t *testing.T) {
   emit:=func(v map[string]interface{}) {v["case"]=name;v["node"]=uint64(1);b,err:=json.Marshal(v);if err!=nil {t.Fatal(err)};fmt.Println("CA_EVENT "+string(b))}
   st:=NewMemoryStorage()
   if err:=st.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1}}}});err!=nil {t.Fatal(err)}
   if err:=st.SetHardState(pb.HardState{Term:1,Commit:1});err!=nil {t.Fatal(err)}
   rn,err:=NewRawNode(&Config{ID:1,Storage:st,Applied:1,ElectionTick:10,HeartbeatTick:1,MaxSizePerMsg:4096,MaxInflightMsgs:256})
   if err!=nil {t.Fatal(err)}
   applied:=uint64(1);observed:=false
   pump:=func() {
    for step:=0;step<100 && rn.HasReady();step++ {
     rd:=rn.Ready()
     if !IsEmptySnap(rd.Snapshot) {t.Fatal("unexpected snapshot")}
     if err:=st.Append(rd.Entries);err!=nil {t.Fatal(err)}
     if !IsEmptyHardState(rd.HardState) {if err:=st.SetHardState(rd.HardState);err!=nil {t.Fatal(err)}}
     for _,e:=range rd.CommittedEntries {
      if e.Index!=applied+1 {t.Fatal("apply order")}
      if e.Type==pb.EntryConfChangeV2 {
       var cc pb.ConfChangeV2;if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)}
       cs:=rn.ApplyConfChange(cc)
       // Observe only the entering operation, by its nonempty Changes identity;
       // this selects both true and false modes independently of the result.
       if len(cc.Changes)>0 {
        if observed {t.Fatal("duplicate entering change")};observed=true
        emit(map[string]interface{}{"event":"configuration_installed","index":e.Index,"auto_leave":cs.AutoLeave,"outgoing_count":len(cs.VotersOutgoing)})
        status:=rn.Status()
        emit(map[string]interface{}{"event":"status_copy","index":e.Index,"auto_leave":status.Config.AutoLeave,"outgoing_count":len(status.Config.Voters[1]),"observed":true})
       }
      } else if e.Type!=pb.EntryNormal {t.Fatal("unexpected entry")}
      applied=e.Index
     }
     // Outgoing messages can target the newly added learner 2. They are
     // dropped by the isolated transport; all voters are node 1 in both sets.
     rn.Advance(rd)
    }
    if rn.HasReady() {t.Fatal("work bound exceeded")}
   }
   if err:=rn.Campaign();err!=nil {t.Fatal(err)};pump()
   if rn.Status().RaftState!=StateLeader {t.Fatal("election failed")}
   cc:=pb.ConfChangeV2{Transition:transition,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeAddLearnerNode,NodeID:2}}}
   if err:=rn.ProposeConfChange(cc);err!=nil {t.Fatal(err)};pump()
   if !observed {t.Fatal("configuration was not applied")}
   emit(map[string]interface{}{"event":"run_completed","applied":applied})
  })
 }
}
