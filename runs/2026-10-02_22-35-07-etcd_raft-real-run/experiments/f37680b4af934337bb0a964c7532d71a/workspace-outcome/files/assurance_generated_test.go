package raft
import (
 "context"
 "encoding/json"
 "fmt"
 "testing"
 "time"
 pb "go.etcd.io/raft/v3/raftpb"
)
func assuranceEarlyEmit(m map[string]any){b,e:=json.Marshal(m);if e!=nil{panic(e)};fmt.Println("CA_EVENT "+string(b))}
func TestAssuranceEarlyAdvanceAdmission(t *testing.T){
 for _,scenario:=range []string{"hold_advance","early_advance","apply_then_advance"}{t.Run(scenario,func(t *testing.T){
  ctx,cancel:=context.WithTimeout(context.Background(),5*time.Second);defer cancel()
  s:=NewMemoryStorage();if e:=s.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1}}}});e!=nil{t.Fatal(e)}
  s.SetHardState(pb.HardState{Term:1,Commit:1})
  n:=RestartNode(&Config{ID:1,ElectionTick:10,HeartbeatTick:1,Storage:s,Applied:1,MaxSizePerMsg:4096,MaxInflightMsgs:256});defer n.Stop()
  userApplied:=uint64(1)
  next:=func()Ready{select{case rd:=<-n.Ready():
   if !IsEmptySnap(rd.Snapshot){t.Fatal("unexpected runtime snapshot")}
   if e:=s.Append(rd.Entries);e!=nil{t.Fatal(e)}
   if !IsEmptyHardState(rd.HardState){if e:=s.SetHardState(rd.HardState);e!=nil{t.Fatal(e)}}
   // All remote destinations are learners not needed for the single voter.
   return rd
  case <-ctx.Done():t.Fatal("Ready prerequisite timed out");return Ready{}}}
  apply:=func(es []pb.Entry){for _,e:=range es{
   if e.Index!=userApplied+1{t.Fatalf("application order %d after %d",e.Index,userApplied)}
   if e.Type==pb.EntryConfChange{var cc pb.ConfChange;if x:=cc.Unmarshal(e.Data);x!=nil{t.Fatal(x)};n.ApplyConfChange(cc)}
   userApplied=e.Index
  }}
  if e:=n.Campaign(ctx);e!=nil{t.Fatal(e)}
  for userApplied<2{rd:=next();apply(rd.CommittedEntries);n.Advance()}
  if n.Status().RaftState!=StateLeader{t.Fatal("not leader")}
  first:=pb.ConfChange{Type:pb.ConfChangeAddLearnerNode,NodeID:2}
  second:=pb.ConfChange{Type:pb.ConfChangeAddLearnerNode,NodeID:3}
  if e:=n.ProposeConfChange(ctx,first);e!=nil{t.Fatal(e)}
  var held Ready;firstIndex:=uint64(0)
  for i:=0;i<32;i++{rd:=next();for _,e:=range rd.CommittedEntries{if e.Type==pb.EntryConfChange{firstIndex=e.Index}}
   if firstIndex!=0{held=rd;break};apply(rd.CommittedEntries);n.Advance()
  }
  if firstIndex==0{t.Fatal("first configuration never committed")}
  if scenario=="apply_then_advance"{apply(held.CommittedEntries);n.Advance()} else if scenario=="early_advance"{n.Advance()}
  before:=n.Status()
  priorApplied:=userApplied>=firstIndex
  assuranceEarlyEmit(map[string]any{"event":"before_second","scenario":scenario,"first_index":firstIndex,"prior_applied_at_proposal":priorApplied,"user_applied":userApplied,"reported_applied":before.Applied,"learners":len(before.Config.Learners),"commit":before.Commit})
  if e:=n.ProposeConfChange(ctx,second);e!=nil{t.Fatal(e)}
  // Status synchronizes after the serialized proposal handling. It does not
  // complete application or alter the pending configuration.
  n.Status()
  if scenario=="hold_advance"{apply(held.CommittedEntries);n.Advance()}
  var secondIndex uint64
  var secondType pb.EntryType
  for i:=0;i<32;i++{rd:=next()
   for _,e:=range rd.Entries{if e.Index>firstIndex{secondIndex=e.Index;secondType=e.Type}}
   if secondIndex!=0{
    st:=n.Status()
    assuranceEarlyEmit(map[string]any{"event":"second_appended","scenario":scenario,"first_index":firstIndex,"second_index":secondIndex,"second_type":secondType.String(),"prior_applied_at_proposal":priorApplied,"user_applied":userApplied,"reported_applied":st.Applied,"learners":len(st.Config.Learners)})
    // Finish caller duties after retaining the earlier admission observation.
    if scenario=="early_advance"{apply(held.CommittedEntries)}
    apply(rd.CommittedEntries);n.Advance();break
   }
   // Preserve application order while the first configuration is deferred.
   if len(rd.CommittedEntries)>0{t.Fatal("unexpected application work before second entry observation")}
   n.Advance()
  }
  if secondIndex==0{t.Fatal("second proposal outcome not observed")}
  for userApplied<secondIndex{rd:=next();apply(rd.CommittedEntries);n.Advance()}
  assuranceEarlyEmit(map[string]any{"event":"completed","scenario":scenario,"user_applied":userApplied,"learners":len(n.Status().Config.Learners)})
 })}
}
