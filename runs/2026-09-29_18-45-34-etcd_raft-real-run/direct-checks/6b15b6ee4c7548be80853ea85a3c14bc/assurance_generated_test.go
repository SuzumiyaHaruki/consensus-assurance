package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

type assurancePeer struct { rn *RawNode; storage *MemoryStorage }
type assuranceNetwork struct { t *testing.T; peers map[uint64]*assurancePeer; wire []pb.Message }
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
 for _,m:=range rd.Messages {
  switch m.Type {
  case pb.MsgStorageAppend:
   n.appendWork(id,m); n.wire=append(n.wire,m.Responses...)
  case pb.MsgStorageApply:
   // This harness has a no-op application; each batch finishes synchronously.
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
   p:=n.peers[m.To]; if p==nil { n.t.Fatalf("unknown destination %d",m.To) }; n.must(p.rn.Step(m))
  }
  if !work { return }
 }
 n.t.Fatal("schedule failed to quiesce within 500 transitions")
}
func (n *assuranceNetwork) stored(id,index,term uint64,data []byte) bool {
 es,err:=n.peers[id].storage.Entries(index,index+1,^uint64(0))
 return err==nil && len(es)==1 && es[0].Term==term && string(es[0].Data)==string(data)
}
type assuranceObservation struct {
 phase string; rd Ready; pending bool; direct,nested,appendCount,appendEntries int
 delivered int; allBacked bool
}
func TestAssuranceAsyncDuplicateAppend(t *testing.T) {
 n:=&assuranceNetwork{t:t,peers:map[uint64]*assurancePeer{}}
 for _,id:=range []uint64{1,2} {
  s:=NewMemoryStorage()
  // Publicly supported manual bootstrap from a shared compacted prefix.
  n.must(s.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1,2}}}}))
  n.must(s.SetHardState(pb.HardState{Term:1,Commit:1}))
  rn,err:=NewRawNode(&Config{ID:id,Storage:s,Applied:1,ElectionTick:10,HeartbeatTick:1,MaxSizePerMsg:4096,MaxInflightMsgs:16,AsyncStorageWrites:true})
  n.must(err); n.peers[id]=&assurancePeer{rn:rn,storage:s}
 }
 n.must(n.peers[1].rn.Campaign()); n.drain()
 if n.peers[1].rn.BasicStatus().RaftState!=StateLeader { t.Fatal("producer did not become leader") }
 data:=[]byte("assurance-duplicate-append")
 n.must(n.peers[1].rn.Propose(data))
 // Process only the leader until its actual append message is captured.
 if !n.peers[1].rn.HasReady() { t.Fatal("proposal produced no Ready") }
 n.process(1,n.peers[1].rn.Ready())
 var app pb.Message; found:=false
 for i,m:=range n.wire {
  if m.Type==pb.MsgApp && m.From==1 && m.To==2 && len(m.Entries)>0 && string(m.Entries[len(m.Entries)-1].Data)==string(data) {
   app=m; n.wire=append(n.wire[:i],n.wire[i+1:]...); found=true; break
  }
 }
 if !found { t.Fatal("no actual leader append for proposal") }
 target:=app.Entries[len(app.Entries)-1]
 base:=func(event,phase string) map[string]interface{} { return map[string]interface{}{"event":event,"scenario":"duplicate_pending","phase":phase,"leader":app.From,"follower":app.To,"entry_index":target.Index,"entry_term":target.Term,"message_term":app.Term} }
 matches:=func(m pb.Message) bool { return m.Type==pb.MsgAppResp && !m.Reject && m.From==app.To && m.To==app.From && m.Term==app.Term && m.Index==target.Index }
 capture:=func(phase string) *assuranceObservation {
  e:=base("produced",phase); e["payload"]=string(target.Data); e["previous_index"]=app.Index; assuranceEmit(e)
  n.must(n.peers[2].rn.Step(app))
  o:=&assuranceObservation{phase:phase,pending:!n.stored(2,target.Index,target.Term,target.Data),allBacked:true}
  e=base("admitted",phase); e["pending_storage"]=o.pending; e["producer_term"]=app.Term; assuranceEmit(e)
  if !n.peers[2].rn.HasReady() { t.Fatal("accepted append has no Ready") }
  o.rd=n.peers[2].rn.Ready()
  for _,m:=range o.rd.Messages {
   if matches(m) { o.direct++ }
   if m.Type==pb.MsgStorageAppend {
    o.appendCount++; o.appendEntries+=len(m.Entries)
    for _,r:=range m.Responses { if matches(r) { o.nested++ } }
   }
  }
  e=base("ready_observed",phase); e["pending_storage"]=o.pending; e["direct_acks"]=o.direct; e["nested_acks"]=o.nested; e["append_work_count"]=o.appendCount; e["append_entries"]=o.appendEntries; assuranceEmit(e)
  return o
 }
 // The first Ready accepts entries without executing its local storage work.
 first:=capture("original")
 duplicate:=capture("duplicate")
 publish:=func(o *assuranceObservation,m pb.Message) {
  if matches(m) {
   backed:=n.stored(2,target.Index,target.Term,target.Data)
   o.delivered++; o.allBacked=o.allBacked&&backed
   e:=base("ack_published",o.phase); e["stored"]=backed; e["ack_index"]=m.Index; e["ack_term"]=m.Term; assuranceEmit(e)
  }
  n.wire=append(n.wire,m)
 }
 // Immediate messages are legally publishable before local work. Do this even
 // if the measured routing is wrong, so the schedule does not assume the oracle.
 for _,o:=range []*assuranceObservation{first,duplicate} {
  for _,m:=range o.rd.Messages { if !IsLocalMsgTarget(m.To) { publish(o,m) } }
 }
 finish:=func(o *assuranceObservation) {
  for _,m:=range o.rd.Messages {
   if m.Type==pb.MsgStorageAppend {
    n.appendWork(2,m)
    for _,r:=range m.Responses { publish(o,r) }
   } else if m.Type==pb.MsgStorageApply {
    for _,r:=range m.Responses { publish(o,r) }
   }
  }
 }
 // All same-target work completes in Ready order, including response-only work.
 finish(first); finish(duplicate); n.drain()
 // A permitted control repeats the identical append after storage completion.
 control:=capture("stored_retry")
 for _,m:=range control.rd.Messages { if !IsLocalMsgTarget(m.To) { publish(control,m) } }
 finish(control); n.drain()
 for _,o:=range []*assuranceObservation{first,duplicate,control} {
  e:=base("completed",o.phase)
  e["pending_storage"]=o.pending; e["direct_acks"]=o.direct; e["nested_acks"]=o.nested; e["append_work_count"]=o.appendCount; e["append_entries"]=o.appendEntries
  e["published_acks"]=o.delivered; e["all_published_backed"]=o.allBacked; e["stored_at_end"]=n.stored(2,target.Index,target.Term,target.Data)
  e["leader_commit"]=n.peers[1].rn.BasicStatus().Commit; e["follower_commit"]=n.peers[2].rn.BasicStatus().Commit
  if o.delivered==0 || !n.stored(2,target.Index,target.Term,target.Data) { e["event"]="completion_gap" }
  assuranceEmit(e)
 }
}
