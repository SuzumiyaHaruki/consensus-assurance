package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 "github.com/lni/dragonboat/v3/config"
 pb "github.com/lni/dragonboat/v3/raftpb"
)

type assuranceReadNet struct {
 t *testing.T
 peers map[uint64]*Peer
 dbs map[uint64]*TestLogDB
 applied map[uint64]uint64
}
func assuranceEvent(v map[string]interface{}) { b,e:=json.Marshal(v); if e!=nil {panic(e)}; fmt.Println("CA_EVENT "+string(b)) }
func assuranceCtx(c pb.SystemCtx) string { return fmt.Sprintf("%d/%d",c.Low,c.High) }
func (n *assuranceReadNet) collect(id uint64) []pb.Message {
 p:=n.peers[id]
 u:=p.GetUpdate(true,n.applied[id])
 if !pb.IsEmptySnapshot(u.Snapshot) {n.t.Fatal("unexpected snapshot")}
 // The driver substitutes volatile storage only in this no-crash history.
 // Persist all state and entries before making any outgoing message deliverable.
 if err:=n.dbs[id].Append(u.EntriesToSave);err!=nil {n.t.Fatal(err)}
 if !pb.IsEmptyState(u.State) {n.dbs[id].SetState(u.State)}
 msgs:=append([]pb.Message(nil),u.Messages...)
 for i:=range msgs {msgs[i].Entries=append([]pb.Entry(nil),msgs[i].Entries...)}
 for _,e:=range u.CommittedEntries {
  if e.Type==pb.ConfigChangeEntry {var cc pb.ConfigChange; if err:=cc.Unmarshal(e.Cmd);err!=nil {n.t.Fatal(err)};p.ApplyConfigChange(cc)}
  n.applied[id]=e.Index
 }
 p.Commit(u)
 p.NotifyRaftLastApplied(n.applied[id])
 return msgs
}
func (n *assuranceReadNet) deliver(m pb.Message) []pb.Message {
 p,ok:=n.peers[m.To];if !ok {n.t.Fatalf("unknown destination %d",m.To)}
 p.Handle(m)
 return n.collect(m.To)
}
func (n *assuranceReadNet) drain(ms []pb.Message) {
 for i:=0;len(ms)>0;i++ {if i>1000 {n.t.Fatal("message drain exceeded bound")};m:=ms[0];ms=ms[1:];ms=append(ms,n.deliver(m)...)}
}
func assuranceNewReadNet(t *testing.T) *assuranceReadNet {
 n:=&assuranceReadNet{t:t,peers:map[uint64]*Peer{},dbs:map[uint64]*TestLogDB{},applied:map[uint64]uint64{}}
 addresses:=[]PeerAddress{{NodeID:1,Address:"n1"},{NodeID:2,Address:"n2"},{NodeID:3,Address:"n3"}}
 for id:=uint64(1);id<=3;id++ {db:=NewTestLogDB().(*TestLogDB);n.dbs[id]=db;n.peers[id]=Launch(config.Config{NodeID:id,ClusterID:1,ElectionRTT:10,HeartbeatRTT:1},db,nil,append([]PeerAddress(nil),addresses...),true,true)}
 for id:=uint64(1);id<=3;id++ {n.drain(n.collect(id))}
 for i:=0;i<40 && !n.peers[1].raft.isLeader();i++ {n.peers[1].Tick();n.drain(n.collect(1))}
 for id:=uint64(1);id<=3;id++ {
  r:=n.peers[id].raft
  if r.leaderID!=1 || r.log.committed!=n.applied[id] || r.log.committed<=3 {t.Fatalf("setup not ready at %d",id)}
 }
 if !n.peers[1].raft.hasCommittedEntryAtCurrentTerm(){t.Fatal("no current-term commitment")}
 assuranceEvent(map[string]interface{}{"event":"setup","leader":1,"term":n.peers[1].raft.term,"committed":n.peers[1].raft.log.committed})
 return n
}
func (n *assuranceReadNet) issue(id uint64,c pb.SystemCtx) []pb.Message {
 n.peers[id].ReadIndex(c)
 out:=n.collect(id)
 if len(out)!=1 || out[0].Type!=pb.ReadIndex || out[0].To!=1 {n.t.Fatalf("unexpected forwarding: %+v",out)}
 return n.deliver(out[0])
}
func (n *assuranceReadNet) admit(scenario string,id uint64,c pb.SystemCtx) {
 s,ok:=n.peers[1].raft.readIndex.pending[c]
 if !ok || s.from!=id || s.ctx!=c {n.t.Fatal("request not admitted as issued")}
 assuranceEvent(map[string]interface{}{"event":"admitted","scenario":scenario,"requester":id,"expected_context":assuranceCtx(c),"admitted":true,"index":s.index})
}
func (n *assuranceReadNet) confirm(ms []pb.Message,c pb.SystemCtx) []pb.Message {
 // Deliver an actual generated heartbeat and its actual response. Other
 // heartbeat traffic remains delayed; no response fields are fabricated.
 for _,m:=range ms {
  if m.Type==pb.Heartbeat && m.To==2 && m.Hint==c.Low && m.HintHigh==c.High {
   rs:=n.deliver(m)
   for _,r:=range rs {if r.Type==pb.HeartbeatResp && r.To==1 && r.Hint==c.Low && r.HintHigh==c.High {return n.deliver(r)}}
   n.t.Fatal("no matching generated heartbeat response")
  }
 }
 n.t.Fatal("no matching generated heartbeat");return nil
}
func (n *assuranceReadNet) observe(scenario string,ms []pb.Message) {
 for _,m:=range ms {
  if m.Type!=pb.ReadIndexResp {n.t.Fatalf("unexpected release output: %+v",m)}
  assuranceEvent(map[string]interface{}{"event":"response","scenario":scenario,"requester":m.To,"observed":true,"context":assuranceCtx(pb.SystemCtx{Low:m.Hint,High:m.HintHigh}),"index":m.LogIndex})
  p:=n.peers[m.To];p.Handle(m)
  u:=p.GetUpdate(true,n.applied[m.To])
  for _,rr:=range u.ReadyToReads {assuranceEvent(map[string]interface{}{"event":"ready","scenario":scenario,"requester":m.To,"context":assuranceCtx(rr.SystemCtx),"index":rr.Index})}
  n.collect(m.To)
 }
 assuranceEvent(map[string]interface{}{"event":"suffix","scenario":scenario,"pending":len(n.peers[1].raft.readIndex.pending),"responses":len(ms)})
}
func TestAssuranceForwardedReadContexts(t *testing.T) {
 n:=assuranceNewReadNet(t)
 c:=pb.SystemCtx{Low:101,High:1001}
 one:=n.issue(2,c);n.admit("single",2,c);n.observe("single",n.confirm(one,c))
 a:=pb.SystemCtx{Low:201,High:2001};b:=pb.SystemCtx{Low:202,High:2002}
 delayed:=n.issue(2,a);n.admit("overlap",2,a)
 later:=n.issue(3,b);n.admit("overlap",3,b)
 // End observation after processing one later-context quorum acknowledgement,
 // independently of whether the compared identities match.
 n.observe("overlap",n.confirm(later,b))
 // Retain the delayed message count. No claim of global quiescence or an
 // infinite stall is made; undelivered messages are explicit schedule inputs.
 assuranceEvent(map[string]interface{}{"event":"delayed","count":len(delayed)+len(later)-1})
}
