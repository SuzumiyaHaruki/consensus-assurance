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
   if c.restrict && ((m.From<=3 && m.To>=4) || (m.From>=4 && m.To<=3)) {
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
func TestAssuranceConfigurationAgreement(t *testing.T) {
 for _,delayed:=range []bool{false,true} { t.Run(fmt.Sprintf("delayed-%t",delayed),func(t *testing.T) {
 ctx,cancel:=context.WithTimeout(context.Background(),30*time.Second);defer cancel()
 c:=&assuranceNodeNetwork{t:t,ctx:ctx}
 peers:=[]Peer{{ID:1},{ID:2},{ID:3},{ID:4},{ID:5}}
 for i:=1;i<=5;i++ {
  s:=NewMemoryStorage()
  n:=StartNode(&Config{ID:uint64(i),ElectionTick:10,HeartbeatTick:1,Storage:s,MaxInflightMsgs:16,MaxSizePerMsg:4096},peers)
  c.peers=append(c.peers,&assuranceNodePeer{n:n,s:s});defer n.Stop()
 }
 c.drain()
 if err:=c.peers[0].n.Campaign(ctx);err!=nil {t.Fatal(err)}
 c.drain()
 if c.peers[0].n.Status().RaftState!=StateLeader {t.Fatal("initial election not reached")}
 c.peers[0].freezeApply=delayed
 for _,removeID:=range []uint64{2,3} {
  if err:=c.peers[0].n.ProposeConfChange(ctx,pb.ConfChange{Type:pb.ConfChangeRemoveNode,NodeID:removeID});err!=nil {t.Fatal(err)}
  c.drain()
  for _,p:=range c.peers {
   st:=p.n.Status()
   assuranceNodeEvent(map[string]interface{}{"event":"membership_checkpoint","removed_proposal":removeID,"node":st.ID,"term":st.Term,"commit":st.Commit,"reported_applied":st.Applied,"config":st.Config,"deferred_batches":len(p.deferred)})
  }
 }
 // Nodes 2 and 3 remain running after applying removal; they receive only
 // actual protocol messages. No removed identity is reused or re-added.
 last,err:=c.peers[0].s.LastIndex();if err!=nil {t.Fatal(err)}
 target:=last+1
 assuranceNodeEvent(map[string]interface{}{"event":"comparison_admitted","scenario_id":t.Name(),"target_index":target,"history_ready":true,"delayed_application":delayed})
 c.restrict=true
 if err:=c.peers[0].n.Propose(ctx,[]byte("assurance/old-config-command"));err!=nil {t.Fatal(err)}
 c.drain()
 left:=c.peers[0].n.Status()
 assuranceNodeEvent(map[string]interface{}{"event":"old_commit","node":left.ID,"term":left.Term,"commit":left.Commit,"config":left.Config})
 if err:=c.peers[3].n.Campaign(ctx);err!=nil {t.Fatal(err)}
 c.drain()
 // Finish the deferred application FIFO without healing the partition.
 p:=c.peers[0]
 for _,batch:=range p.deferred {c.apply(p,batch)}
 p.deferred=nil;p.freezeApply=false
 c.drain()
 assuranceNodeEvent(map[string]interface{}{"event":"application_finished","node":uint64(1),"reported_applied":p.n.Status().Applied,"config":p.n.Status().Config})
 left=c.peers[0].n.Status()
 right:=c.peers[3].n.Status()
 le,err:=c.peers[0].s.Entries(target,target+1,^uint64(0));if err!=nil {t.Fatal(err)}
 re,err:=c.peers[3].s.Entries(target,target+1,^uint64(0));if err!=nil {t.Fatal(err)}
 if len(le)!=1 || len(re)!=1 {t.Fatal("missing observation entry")}
 equal:=le[0].Term==re[0].Term && le[0].Type==re[0].Type && string(le[0].Data)==string(re[0].Data)
 assuranceNodeEvent(map[string]interface{}{"event":"agreement_observed","scenario_id":t.Name(),"target_index":target,"completed":true,"both_committed":left.Commit>=target && right.Commit>=target,"entries_equal":equal,"left_entry":le[0],"right_entry":re[0],"left_commit":left.Commit,"right_commit":right.Commit,"left_config":left.Config,"right_config":right.Config,"left_term":left.Term,"right_term":right.Term,"held_messages":len(c.held),"deferred_batches":len(p.deferred)})
 }) }
}
