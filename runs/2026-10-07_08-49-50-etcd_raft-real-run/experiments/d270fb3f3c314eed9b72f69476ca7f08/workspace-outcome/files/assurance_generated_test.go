package raft

import (
 "context"
 "encoding/json"
 "fmt"
 "testing"
 "time"

 pb "go.etcd.io/raft/v3/raftpb"
)

func assuranceEmit(v map[string]interface{}) {
 b, err := json.Marshal(v); if err != nil { panic(err) }; fmt.Println("CA_EVENT " + string(b))
}
func assuranceConfig(id uint64, s *MemoryStorage) *Config {
 return &Config{ID:id, ElectionTick:10, HeartbeatTick:1, Storage:s, Applied:1, MaxSizePerMsg:4096, MaxInflightMsgs:16}
}
func assurancePersist(t *testing.T, s *MemoryStorage, rd Ready) {
 t.Helper()
 if !IsEmptySnap(rd.Snapshot) { if err:=s.ApplySnapshot(rd.Snapshot); err!=nil {t.Fatal(err)} }
 if len(rd.Entries)>0 {if err:=s.Append(rd.Entries);err!=nil {t.Fatal(err)}}
 if !IsEmptyHardState(rd.HardState) {if err:=s.SetHardState(rd.HardState);err!=nil {t.Fatal(err)}}
}
func assuranceApplyRaw(t *testing.T, r *RawNode, entries []pb.Entry) {
 t.Helper()
 for _,e:=range entries {
  switch e.Type {
  case pb.EntryConfChange:
   var cc pb.ConfChange; if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)};r.ApplyConfChange(cc)
  case pb.EntryConfChangeV2:
   var cc pb.ConfChangeV2; if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)};r.ApplyConfChange(cc)
  }
 }
}
// Generate the removal with actual participants and persist-before-send Ready handling.
// The initial snapshot is the explicitly selected initial cluster, not an invented election.
func assuranceRemovalPrefix(t *testing.T) (*MemoryStorage,uint64) {
 rs:=map[uint64]*RawNode{};ss:=map[uint64]*MemoryStorage{}
 for id:=uint64(1);id<=3;id++ {
  s:=NewMemoryStorage();if err:=s.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1,2,3}}}});err!=nil {t.Fatal(err)}
  if err:=s.SetHardState(pb.HardState{Term:1,Commit:1});err!=nil {t.Fatal(err)}
  r,err:=NewRawNode(assuranceConfig(id,s));if err!=nil {t.Fatal(err)};rs[id]=r;ss[id]=s
 }
 pump:=func(){
  for round:=0;round<100;round++ {
   var queue []pb.Message;work:=false
   for id:=uint64(1);id<=3;id++ {
    r:=rs[id];if !r.HasReady(){continue};work=true;rd:=r.Ready();assurancePersist(t,ss[id],rd)
    queue=append(queue,rd.Messages...)
    assuranceApplyRaw(t,r,rd.CommittedEntries);r.Advance(rd)
   }
   for _,msg:=range queue {if err:=rs[msg.To].Step(msg);err!=nil && err!=ErrStepPeerNotFound {t.Fatal(err)}}
   if !work && len(queue)==0{return}
  }
  t.Fatal("prefix failed to drain within diagnostic round bound")
 }
 if err:=rs[2].Campaign();err!=nil {t.Fatal(err)};pump()
 if rs[2].BasicStatus().RaftState!=StateLeader {t.Fatal("prefix did not elect node 2")}
 if err:=rs[2].ProposeConfChange(pb.ConfChange{Type:pb.ConfChangeRemoveNode,NodeID:1});err!=nil {t.Fatal(err)};pump()
 hs,_,err:=ss[1].InitialState();if err!=nil {t.Fatal(err)}
 first,err:=ss[1].FirstIndex();if err!=nil {t.Fatal(err)};last,err:=ss[1].LastIndex();if err!=nil {t.Fatal(err)}
 ents,err:=ss[1].Entries(first,last+1,^uint64(0));if err!=nil {t.Fatal(err)}
 var removal uint64
 for _,e:=range ents {if e.Type==pb.EntryConfChange {var cc pb.ConfChange;if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)};if cc.Type==pb.ConfChangeRemoveNode && cc.NodeID==1 {removal=e.Index}}}
 if removal==0 || hs.Commit<removal {t.Fatal("node 1 did not durably learn committed removal")}
 assuranceEmit(map[string]interface{}{"event":"prefix","node":1,"leader":2,"term":hs.Term,"commit":hs.Commit,"removal_index":removal})
 return ss[1],removal
}
func assuranceClone(t *testing.T,s *MemoryStorage)*MemoryStorage {
 snap,err:=s.Snapshot();if err!=nil {t.Fatal(err)};hs,_,err:=s.InitialState();if err!=nil {t.Fatal(err)}
 first,err:=s.FirstIndex();if err!=nil {t.Fatal(err)};last,err:=s.LastIndex();if err!=nil {t.Fatal(err)}
 ents,err:=s.Entries(first,last+1,^uint64(0));if err!=nil {t.Fatal(err)}
 out:=NewMemoryStorage();if err:=out.ApplySnapshot(snap);err!=nil {t.Fatal(err)};if err:=out.Append(ents);err!=nil {t.Fatal(err)};if err:=out.SetHardState(hs);err!=nil {t.Fatal(err)};return out
}
func TestAssuranceAdvanceBeforeConfigurationExploration(t *testing.T) {
 prefix,removal:=assuranceRemovalPrefix(t)
 for _,early:=range []bool{false,true} {
  t.Run(fmt.Sprintf("early_%v",early),func(t *testing.T){
   // Restore application state from the initial snapshot, replaying persisted log entries.
   s:=assuranceClone(t,prefix);n:=RestartNode(assuranceConfig(1,s));defer n.Stop()
   ctx,cancel:=context.WithTimeout(context.Background(),5*time.Second);defer cancel()
   var rd Ready
   select {case rd=<-n.Ready():case <-ctx.Done():t.Fatal("replay Ready unavailable")}
   assurancePersist(t,s,rd)
   var cc pb.ConfChange;found:=false
   for _,e:=range rd.CommittedEntries {if e.Index==removal {if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)};found=true}}
   if !found || cc.NodeID!=1 || cc.Type!=pb.ConfChangeRemoveNode {t.Fatal("replay did not contain expected removal")}
   before:=n.Status()
   // Control campaigns while the unadvanced Ready remains pending. The conditional
   // schedule acknowledges that same Ready before installing its configuration.
   if early {n.Advance()}
   if err:=n.Campaign(ctx);err!=nil {t.Fatal(err)}
   after:=n.Status() // actor-owned coherent copy, after campaign dispatch
   _,eligible:=after.Config.Voters[0][1]
   assuranceEmit(map[string]interface{}{"event":"campaign_observation","early_advance":early,"node":1,"removal_index":removal,"before_term":before.Term,"after_term":after.Term,"before_applied":before.Applied,"after_applied":after.Applied,"commit":after.Commit,"state":after.RaftState.String(),"self_in_config":eligible})
   // Complete the delayed work before shutdown; no result requires the delay to persist.
   conf:=n.ApplyConfChange(cc)
   if !early {n.Advance()}
   // Persist any resulting term/vote update and drop network messages under the
   // explicitly isolated suffix. No response is fabricated or fed back.
   final:=n.Status()
   if early && final.Term!=before.Term {
    select {case extra:=<-n.Ready():assurancePersist(t,s,extra);if len(extra.CommittedEntries)>0 {t.Fatal("unexpected new application work")};n.Advance();case <-ctx.Done():t.Fatal("missing campaign Ready")}
   }
   final=n.Status()
   assuranceEmit(map[string]interface{}{"event":"completion","early_advance":early,"node":1,"removal_index":removal,"applied":final.Applied,"voters":conf.Voters,"state":final.RaftState.String()})
  })
 }
}
