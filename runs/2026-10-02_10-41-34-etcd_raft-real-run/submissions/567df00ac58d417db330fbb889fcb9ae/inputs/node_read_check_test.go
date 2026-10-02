package raft

import (
 "context"
 "encoding/json"
 "fmt"
 "testing"
 "time"
 pb "go.etcd.io/raft/v3/raftpb"
)

type assuranceNodePeer struct {
 n Node
 s *MemoryStorage
 deferred [][]pb.Entry
 freezeApply bool
 reads []ReadState
}
type assuranceNodeNetwork struct {
 t *testing.T
 ctx context.Context
 peers []*assuranceNodePeer
 messages []pb.Message
 held []pb.Message
 restrict bool
}
func assuranceNodeEvent(v map[string]interface{}) {
 b,err:=json.Marshal(v); if err!=nil {panic(err)}
 fmt.Println("CA_EVENT "+string(b))
}
func (c *assuranceNodeNetwork) apply(p *assuranceNodePeer, entries []pb.Entry) {
 for _,e:=range entries {
  switch e.Type {
  case pb.EntryConfChange:
   var cc pb.ConfChange; if err:=cc.Unmarshal(e.Data);err!=nil {c.t.Fatal(err)}
   cs:=p.n.ApplyConfChange(cc)
   assuranceNodeEvent(map[string]interface{}{"event":"config_applied","node":p.n.Status().ID,"index":e.Index,"conf":cs})
  case pb.EntryConfChangeV2:
   var cc pb.ConfChangeV2; if err:=cc.Unmarshal(e.Data);err!=nil {c.t.Fatal(err)}
   p.n.ApplyConfChange(cc)
  }
 }
}
func (c *assuranceNodeNetwork) ready(p *assuranceNodePeer, rd Ready) {
 if !IsEmptySnap(rd.Snapshot) {c.t.Fatal("unexpected snapshot in this exploration")}
 if err:=p.s.Append(rd.Entries);err!=nil {c.t.Fatal(err)}
 if !IsEmptyHardState(rd.HardState) {if err:=p.s.SetHardState(rd.HardState);err!=nil {c.t.Fatal(err)}}
 c.messages=append(c.messages,rd.Messages...)
 if len(rd.CommittedEntries)>0 {
  if p.freezeApply || len(p.deferred)>0 {
   p.deferred=append(p.deferred,rd.CommittedEntries)
  } else {c.apply(p,rd.CommittedEntries)}
 }
 for _,rs:=range rd.ReadStates {
  p.reads=append(p.reads,rs)
  assuranceNodeEvent(map[string]interface{}{"event":"read_state","node":p.n.Status().ID,"request":string(rs.RequestCtx),"index":rs.Index})
 }
 // Node/doc.go permit this after persistence, before deferred application.
 p.n.Advance()
 p.n.Status()
}
func (c *assuranceNodeNetwork) drain() {
 for round:=0;round<300;round++ {
  work:=false
  for _,p:=range c.peers {
   p.n.Status()
   select {
   case rd:=<-p.n.Ready(): c.ready(p,rd);work=true
   case <-time.After(5*time.Millisecond):
   }
  }
  msgs:=c.messages;c.messages=nil
  for _,m:=range msgs {
   work=true
   if c.restrict && m.Type==pb.MsgApp && m.From==2 && (m.To==1 || m.To==4) {
    c.held=append(c.held,m);continue
   }
   if m.To<1 || m.To>uint64(len(c.peers)) {c.t.Fatalf("bad destination %d",m.To)}
   p:=c.peers[m.To-1]
   if err:=p.n.Step(c.ctx,m);err!=nil {c.t.Fatal(err)}
   p.n.Status()
  }
  if !work {return}
 }
 c.t.Fatal("driver drain budget exhausted")
}
func (c *assuranceNodeNetwork) status(label string) {
 s:=c.peers[1].n.Status()
 assuranceNodeEvent(map[string]interface{}{"event":"checkpoint","phase":label,"node":s.ID,"term":s.Term,"state":s.RaftState.String(),"commit":s.Commit,"reported_applied":s.Applied,"config":s.Config,"progress":s.Progress,"deferred_batches":len(c.peers[1].deferred),"read_count":len(c.peers[1].reads),"held_messages":len(c.held)})
}
func TestAssuranceFirstCommitReadRelease(t *testing.T) {
 for _,activationFirst:=range []bool{true,false} {
  label:="append_reply_first";if activationFirst {label="config_activation_first"}
  t.Run(label,func(t *testing.T) {
   ctx,cancel:=context.WithTimeout(context.Background(),30*time.Second);defer cancel()
   c:=&assuranceNodeNetwork{t:t,ctx:ctx}
   peers:=[]Peer{{ID:1},{ID:2},{ID:3},{ID:4}}
   for i:=1;i<=4;i++ {
    s:=NewMemoryStorage()
    n:=StartNode(&Config{ID:uint64(i),ElectionTick:10,HeartbeatTick:1,Storage:s,MaxInflightMsgs:16,MaxSizePerMsg:4096},peers)
    c.peers=append(c.peers,&assuranceNodePeer{n:n,s:s})
    defer n.Stop()
   }
   c.drain()
   if err:=c.peers[0].n.Campaign(ctx);err!=nil {t.Fatal(err)}
   c.drain()
   if c.peers[0].n.Status().RaftState!=StateLeader {t.Fatal("initial election not reached")}
   p:=c.peers[1];p.freezeApply=true
   if err:=c.peers[0].n.ProposeConfChange(ctx,pb.ConfChange{Type:pb.ConfChangeRemoveNode,NodeID:4});err!=nil {t.Fatal(err)}
   c.drain()
   if len(p.deferred)==0 {t.Fatal("no configuration batch was deferred")}
   c.restrict=true
   if err:=p.n.Campaign(ctx);err!=nil {t.Fatal(err)}
   c.drain()
   before:=p.n.Status()
   if before.RaftState!=StateLeader {t.Fatal("second election not reached")}
   beforeCommitTerm,err:=p.s.Term(before.Commit);if err!=nil {t.Fatal(err)}
   if beforeCommitTerm==before.Term {t.Fatal("current term committed before intended trigger")}
   request:=[]byte("assurance/first-commit/"+label)
   if err:=p.n.ReadIndex(ctx,request);err!=nil {t.Fatal(err)}
   p.n.Status()
   assuranceNodeEvent(map[string]interface{}{"event":"read_admitted","operation_id":label,"request":string(request),"leader":before.ID,"leader_term":before.Term,"commit_before":before.Commit,"commit_term_before":beforeCommitTerm,"current_term_committed_before":beforeCommitTerm==before.Term,"leader_state":before.RaftState.String(),"voter_count_before":len(before.Config.Voters[0]),"read_call_returned":true})
   c.drain()
   if !activationFirst {
    // The control first delivers actual withheld appends; an old-config quorum
    // can then commit via the ordinary append-response consumer.
    c.restrict=false;c.messages=append(c.messages,c.held...);c.held=nil
    c.drain()
   }
   for _,batch:=range p.deferred {c.apply(p,batch)}
   p.deferred=nil;p.freezeApply=false
   after:=p.n.Status()
   afterCommitTerm,err:=p.s.Term(after.Commit);if err!=nil {t.Fatal(err)}
   // Stop is an observation barrier: after it returns no owner goroutine can
   // mutate the private pending queue. We do not modify any target state.
   p.n.Stop()
   r:=p.n.(*node).rn.raft
   waiting:=false
   pendingContexts:=[]string{}
   for _,m:=range r.pendingReadIndexMessages {
    if len(m.Entries)==1 {
     pendingContexts=append(pendingContexts,string(m.Entries[0].Data))
     if string(m.Entries[0].Data)==string(request) {waiting=true}
    }
   }
   assuranceNodeEvent(map[string]interface{}{"event":"release_observed","operation_id":label,"request":string(request),"transition_returned":true,"leader":after.ID,"leader_term":after.Term,"leader_state":after.RaftState.String(),"commit_after":after.Commit,"commit_term_after":afterCommitTerm,"current_term_committed":afterCommitTerm==after.Term,"voter_count_after":len(after.Config.Voters[0]),"waiting_for_first_commit":waiting,"pending_contexts":pendingContexts,"held_messages":len(c.held),"reported_applied":after.Applied,"deferred_batches":len(p.deferred)})
  })
 }
}
