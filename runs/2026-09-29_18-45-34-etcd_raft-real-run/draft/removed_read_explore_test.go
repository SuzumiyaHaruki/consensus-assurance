package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

type assurancePeer struct { rn *RawNode; storage *MemoryStorage }
type assuranceNetwork struct { t *testing.T; peers map[uint64]*assurancePeer; wire []pb.Message; reads map[uint64][]ReadState; delivered []pb.Message; applied map[uint64][]pb.Entry }
func assuranceEmit(v map[string]interface{}) { b,err:=json.Marshal(v); if err!=nil { panic(err) }; fmt.Println("CA_EVENT "+string(b)) }
func (n *assuranceNetwork) must(err error) { n.t.Helper(); if err!=nil { n.t.Fatal(err) } }
func (n *assuranceNetwork) appendWork(id uint64,m pb.Message) {
 p:=n.peers[id]
 if m.Snapshot!=nil { n.must(p.storage.ApplySnapshot(*m.Snapshot)) }
 n.must(p.storage.Append(m.Entries))
 hs:=pb.HardState{Term:m.Term,Vote:m.Vote,Commit:m.Commit}
 if !IsEmptyHardState(hs) { n.must(p.storage.SetHardState(hs)) }
}
func (n *assuranceNetwork) process(id uint64,rd Ready) {
 n.reads[id]=append(n.reads[id],rd.ReadStates...)
 for _,m:=range rd.Messages {
  switch m.Type {
  case pb.MsgStorageAppend:
   n.appendWork(id,m); n.wire=append(n.wire,m.Responses...)
  case pb.MsgStorageApply:
   // Apply configuration entries through the public callback before completion.
   for _,e:=range m.Entries {
    if e.Type==pb.EntryConfChange { var cc pb.ConfChange; n.must(cc.Unmarshal(e.Data)); n.peers[id].rn.ApplyConfChange(cc) }
    if e.Type==pb.EntryConfChangeV2 { var cc pb.ConfChangeV2; n.must(cc.Unmarshal(e.Data)); n.peers[id].rn.ApplyConfChange(cc) }
    n.applied[id]=append(n.applied[id],e)
   }
   n.wire=append(n.wire,m.Responses...)
  default: n.wire=append(n.wire,m)
  }
 }
}
func (n *assuranceNetwork) drain() {
 for turn:=0;turn<500;turn++ {
  work:=false
  for _,id:=range []uint64{1,2} { p:=n.peers[id]; if p.rn.HasReady() { work=true; n.process(id,p.rn.Ready()) } }
  if len(n.wire)>0 {
   work=true; m:=n.wire[0]; n.wire=n.wire[1:]
   n.delivered=append(n.delivered,m)
   p:=n.peers[m.To]; if p==nil { n.t.Fatalf("unknown destination %d",m.To) }; n.must(p.rn.Step(m))
  }
  if !work { return }
 }
 n.t.Fatal("schedule failed to quiesce within 500 transitions")
}
func (n *assuranceNetwork) stored(id,index,term uint64,data []byte) bool {
 last,err:=n.peers[id].storage.LastIndex()
 n.must(err)
 if index>last { return false }
 es,err:=n.peers[id].storage.Entries(index,index+1,^uint64(0))
 return err==nil && len(es)==1 && es[0].Term==term && string(es[0].Data)==string(data)
}
func TestAssuranceRemovedLeaderRead(t *testing.T) {
 for _,stepDown:=range []bool{false,true} {
  t.Run(fmt.Sprint(stepDown),func(t *testing.T){
   n:=&assuranceNetwork{t:t,peers:map[uint64]*assurancePeer{},reads:map[uint64][]ReadState{},applied:map[uint64][]pb.Entry{}}
   for _,id:=range []uint64{1,2} {
    storage:=NewMemoryStorage()
    n.must(storage.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1,2}}}}))
    n.must(storage.SetHardState(pb.HardState{Term:1,Commit:1}))
    rn,err:=NewRawNode(&Config{ID:id,Storage:storage,Applied:1,ElectionTick:10,HeartbeatTick:1,MaxSizePerMsg:4096,MaxInflightMsgs:16,AsyncStorageWrites:true,ReadOnlyOption:ReadOnlySafe,StepDownOnRemoval:stepDown})
    n.must(err);n.peers[id]=&assurancePeer{rn:rn,storage:storage}
   }
   n.must(n.peers[1].rn.Campaign());n.drain()
   n.must(n.peers[1].rn.ProposeConfChange(pb.ConfChange{Type:pb.ConfChangeRemoveNode,NodeID:1}));n.drain()
   for _,id:=range []uint64{1,2} {
    st:=n.peers[id].rn.Status()
    if len(st.Config.Voters[0])!=1 {t.Fatal("not singleton after committed removal")}
    if _,ok:=st.Config.Voters[0][2];!ok {t.Fatal("remaining voter mismatch")}
   }
   n.must(n.peers[2].rn.Campaign());n.drain()
   if n.peers[2].rn.BasicStatus().RaftState!=StateLeader {t.Fatal("remaining voter did not become leader")}
   payload:=[]byte("post-removal-write")
   n.must(n.peers[2].rn.Propose(payload));n.drain()
   writeIndex:=uint64(0)
   for _,e:=range n.applied[2] {if string(e.Data)==string(payload){writeIndex=e.Index}}
   if writeIndex==0 {t.Fatal("write application did not complete")}
   before:=n.peers[1].rn.BasicStatus()
   assuranceEmit(map[string]interface{}{"event":"before_read","step_down":stepDown,"write_index":writeIndex,"removed_role":before.RaftState.String(),"removed_term":before.Term,"remaining_term":n.peers[2].rn.BasicStatus().Term,"removed_commit":before.Commit})
   n.peers[1].rn.ReadIndex([]byte("removed-read"));n.drain()
   count:=0;readIndex:=uint64(0)
   for _,r:=range n.reads[1] {if string(r.RequestCtx)=="removed-read" {count++;readIndex=r.Index}}
   assuranceEmit(map[string]interface{}{"event":"after_read","step_down":stepDown,"write_index":writeIndex,"read_count":count,"read_index":readIndex,"removed_role":n.peers[1].rn.BasicStatus().RaftState.String()})
  })
 }
}
