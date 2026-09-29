package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

type assurancePeer struct { rn *RawNode; storage *MemoryStorage }
type assuranceNetwork struct { t *testing.T; peers map[uint64]*assurancePeer; wire []pb.Message; reads map[uint64][]ReadState; delivered []pb.Message }
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
func TestAssuranceReadContextReplay(t *testing.T) {
 n:=&assuranceNetwork{t:t,peers:map[uint64]*assurancePeer{},reads:map[uint64][]ReadState{}}
 for _,id:=range []uint64{1,2} {
  storage:=NewMemoryStorage()
  n.must(storage.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1,2}}}}))
  n.must(storage.SetHardState(pb.HardState{Term:1,Commit:1}))
  rn,err:=NewRawNode(&Config{ID:id,Storage:storage,Applied:1,ElectionTick:10,HeartbeatTick:1,MaxSizePerMsg:4096,MaxInflightMsgs:16,AsyncStorageWrites:true,ReadOnlyOption:ReadOnlySafe})
  n.must(err); n.peers[id]=&assurancePeer{rn:rn,storage:storage}
 }
 n.must(n.peers[1].rn.Campaign()); n.drain()
 if n.peers[1].rn.BasicStatus().RaftState!=StateLeader { t.Fatal("missing elected leader") }
 oldCtx:=[]byte("assurance-read-original")
 freshCtx:=[]byte("assurance-read-fresh")
 count:=func(ctx []byte) int { count:=0; for _,r:=range n.reads[1] { if string(r.RequestCtx)==string(ctx) { count++ } }; return count }
 n.peers[1].rn.ReadIndex(oldCtx); n.drain()
 var stale pb.Message; found:=false
 for _,m:=range n.delivered {
  if m.Type==pb.MsgHeartbeatResp && m.From==2 && m.To==1 && string(m.Context)==string(oldCtx) { stale=m; found=true; break }
 }
 if !found || count(oldCtx)!=1 { t.Fatal("old reply producer/completed read not established") }
 currentTerm:=n.peers[1].rn.BasicStatus().Term
 base:=func(event string) map[string]interface{} { return map[string]interface{}{"event":event,"operation":"fresh-read-replay","leader":uint64(1),"follower":uint64(2),"term":currentTerm,"fresh_context":string(freshCtx)} }
 e:=base("old_completed"); e["old_context"]=string(oldCtx);e["old_read_count"]=count(oldCtx);e["reply_context"]=string(stale.Context);e["reply_term"]=stale.Term;assuranceEmit(e)
 n.peers[1].rn.ReadIndex(freshCtx)
 e=base("admitted");e["prior_context"]=string(oldCtx);e["contexts_distinct"]=string(oldCtx)!=string(freshCtx);assuranceEmit(e)
 // Accept the fresh request's Ready but leave its heartbeat in the wire queue.
 for turns:=0;n.peers[1].rn.HasReady();turns++ {
  if turns>=20 { t.Fatal("leader Ready did not settle before replay") }
  n.process(1,n.peers[1].rn.Ready())
 }
 freshRepliesBefore:=0
 for _,m:=range n.delivered { if m.Type==pb.MsgHeartbeatResp && string(m.Context)==string(freshCtx) { freshRepliesBefore++ } }
 // Deliver an exact previously produced reply, without altering its term/context.
 n.must(n.peers[1].rn.Step(stale))
 for turns:=0;n.peers[1].rn.HasReady();turns++ {
  if turns>=20 { t.Fatal("leader Ready did not settle after replay") }
  n.process(1,n.peers[1].rn.Ready())
 }
 before:=count(freshCtx)
 e=base("stale_processed");e["replayed_context"]=string(stale.Context);e["replayed_term"]=stale.Term;e["fresh_replies_before"]=freshRepliesBefore;e["fresh_read_count"]=before;assuranceEmit(e)
 // Finish the permitted fresh-heartbeat path regardless of the pre-quorum result.
 n.drain()
 freshRepliesAfter:=0
 for _,m:=range n.delivered { if m.Type==pb.MsgHeartbeatResp && m.From==2 && m.To==1 && string(m.Context)==string(freshCtx) { freshRepliesAfter++ } }
 freshCount:=count(freshCtx)
 readIndex:=uint64(0)
 for _,r:=range n.reads[1] { if string(r.RequestCtx)==string(freshCtx) { readIndex=r.Index } }
 e=base("completed");e["prequorum_fresh_reads"]=before;e["fresh_replies_before"]=freshRepliesBefore;e["fresh_replies_after"]=freshRepliesAfter;e["final_fresh_reads"]=freshCount;e["read_index"]=readIndex;e["final_term"]=n.peers[1].rn.BasicStatus().Term;e["old_read_count"]=count(oldCtx)
 if freshCount==0 || freshRepliesAfter==0 { e["event"]="completion_gap" }
 assuranceEmit(e)
}
