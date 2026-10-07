package raft

import (
 "encoding/json"
 "fmt"
 "strings"
 "testing"

 "github.com/lni/dragonboat/v3/config"
 pb "github.com/lni/dragonboat/v3/raftpb"
)

type assurancePeer struct {
 p *Peer
 db ILogDB
 applied uint64
 ready []pb.ReadyToRead
}

type assuranceReadNetwork struct {
 t *testing.T
 nodes map[uint64]*assurancePeer
 queue []pb.Message
 responses []pb.Message
 dropLow uint64
 dropped int
 delivered int
}

func assuranceEvent(v map[string]interface{}) {
 b, err := json.Marshal(v)
 if err != nil { panic(err) }
 fmt.Println("CA_EVENT " + string(b))
}

// Complete the caller's update handoff before any outgoing message is delivered.
// The abstract application consumes only bootstrap config entries and the election noop.
func (n *assuranceReadNetwork) harvest(id uint64) {
 a := n.nodes[id]
 u := a.p.GetUpdate(true, a.applied)
 if err := a.db.Append(u.EntriesToSave); err != nil { n.t.Fatal(err) }
 if !pb.IsEmptyState(u.State) { a.db.SetState(u.State) }
 msgs := append([]pb.Message(nil), u.Messages...)
 a.ready = append(a.ready, u.ReadyToReads...)
 entries := append([]pb.Entry(nil), u.CommittedEntries...)
 a.p.Commit(u)
 for _, e := range entries {
  if e.Type == pb.ConfigChangeEntry {
   var cc pb.ConfigChange
   if err := cc.Unmarshal(e.Cmd); err != nil { n.t.Fatal(err) }
   a.p.ApplyConfigChange(cc)
  } else if len(e.Cmd) != 0 { n.t.Fatal("unexpected application payload") }
  a.applied = e.Index
 }
 a.p.NotifyRaftLastApplied(a.applied)
 for _, m := range msgs {
  if m.Type == pb.ReadIndexResp {
   n.responses = append(n.responses, m)
   assuranceEvent(map[string]interface{}{"event":"wire_response", "from":m.From, "to":m.To, "term":m.Term, "low":m.Hint, "high":m.HintHigh, "index":m.LogIndex})
  }
  // This fixed policy models failed sends, not reordered successful delivery.
  if m.Type == pb.Heartbeat && m.Hint == n.dropLow && n.dropLow != 0 {
   n.dropped++
   assuranceEvent(map[string]interface{}{"event":"lost_heartbeat", "from":m.From, "to":m.To, "term":m.Term, "low":m.Hint, "high":m.HintHigh})
   continue
  }
  n.queue = append(n.queue, m)
 }
}

func (n *assuranceReadNetwork) one() pb.Message {
 if len(n.queue)==0 { n.t.Fatal("no queued message") }
 m:=n.queue[0]
 n.queue=n.queue[1:]
 a,ok:=n.nodes[m.To]
 if !ok { n.t.Fatalf("unknown destination %d",m.To) }
 n.delivered++
 if n.delivered>1000 { n.t.Fatal("unexpected message loop") }
 a.p.Handle(m)
 n.harvest(m.To)
 return m
}
func (n *assuranceReadNetwork) drain() { for len(n.queue)>0 { n.one() } }

func TestAssuranceRemoteReadIdentity(t *testing.T) {
 n:= &assuranceReadNetwork{t:t,nodes:make(map[uint64]*assurancePeer)}
 peers:=[]PeerAddress{{NodeID:1,Address:"localhost:10001"},{NodeID:2,Address:"localhost:10002"},{NodeID:3,Address:"localhost:10003"}}
 for id:=uint64(1);id<=3;id++ {
  db:=NewTestLogDB()
  cfg:=config.Config{ClusterID:1,NodeID:id,ElectionRTT:10,HeartbeatRTT:1,CheckQuorum:true}
  p:=Launch(cfg,db,nil,append([]PeerAddress(nil),peers...),true,true)
  n.nodes[id]=&assurancePeer{p:p,db:db}
 }
 for id:=uint64(1);id<=3;id++ { n.harvest(id) }
 n.drain()
 // Only node 1's clock advances until it campaigns; no private election bypass.
 for i:=0;i<30 && !n.nodes[1].p.raft.isLeader();i++ {
  n.nodes[1].p.Tick();n.harvest(1);n.drain()
 }
 leader:=n.nodes[1].p.raft
 if !leader.isLeader() || !leader.hasCommittedEntryAtCurrentTerm() { t.Fatal("leader/current-term commitment prerequisite not attained") }
 for id:=uint64(1);id<=3;id++ {
  r:=n.nodes[id].p.raft
  if r.term!=leader.term || r.leaderID!=1 || n.nodes[id].applied<leader.log.committed { t.Fatalf("node %d not caught up",id) }
 }
 term:=leader.term
 ctxA:=pb.SystemCtx{Low:1101,High:30}
 ctxB:=pb.SystemCtx{Low:2202,High:30}
 n.dropLow=ctxA.Low
 n.nodes[2].p.ReadIndex(ctxA);n.harvest(2);n.drain()
 if n.dropped!=2 { t.Fatalf("earlier loss policy dropped %d heartbeats",n.dropped) }
 if len(leader.readIndex.pending)!=1 { t.Fatal("first remote read not pending") }
 n.nodes[3].p.ReadIndex(ctxB);n.harvest(3)
 // Deliver the real forwarded ReadIndex before delivering its generated heartbeats.
 m:=n.one()
 if m.Type!=pb.ReadIndex || m.From!=3 || m.To!=1 { t.Fatal("unexpected forwarded request") }
 if len(leader.readIndex.pending)!=2 || len(leader.readIndex.queue)!=2 { t.Fatal("overlapping prefix not established") }
 contexts:=map[uint64]pb.SystemCtx{2:ctxA,3:ctxB}
 for _,origin:=range []uint64{2,3} {
  ctx:=contexts[origin]
  s,ok:=leader.readIndex.pending[ctx]
  if !ok || s.from!=origin || s.ctx!=ctx { t.Fatal("pending request identity not attained") }
  assuranceEvent(map[string]interface{}{"event":"admitted", "scenario":"remote_prefix", "origin":origin, "request_context":fmt.Sprintf("%d:%d",s.ctx.Low,s.ctx.High), "expected_response":fmt.Sprintf("%d:%d:%d",s.from,s.ctx.Low,s.ctx.High), "pending":true, "term":term, "current_term_committed":leader.hasCommittedEntryAtCurrentTerm(), "overlap_count":len(leader.readIndex.pending), "lost_earlier_heartbeats":n.dropped})
 }
 // All subsequent messages are real target output, delivered in queue order.
 n.drain()
 if leader.term!=term || !leader.isLeader() { t.Fatal("authority changed") }
 for _,origin:=range []uint64{2,3} {
  ctx:=contexts[origin]
  _,pending:=leader.readIndex.pending[ctx]
  sigs:=[]string{}
  for _,resp:=range n.responses {
   if resp.To==origin { sigs=append(sigs,fmt.Sprintf("%d:%d:%d",resp.To,resp.Hint,resp.HintHigh)) }
  }
  ready:=[]string{}
  for _,v:=range n.nodes[origin].ready { ready=append(ready,fmt.Sprintf("%d:%d",v.SystemCtx.Low,v.SystemCtx.High)) }
  assuranceEvent(map[string]interface{}{"event":"result", "scenario":"remote_prefix", "origin":origin, "released":!pending, "response_signature":strings.Join(sigs,","), "response_count":len(sigs), "ready_contexts":strings.Join(ready,","), "remaining_pending":len(leader.readIndex.pending), "remaining_queue":len(n.queue), "term":leader.term})
 }
 // No goroutines, files, network connections, or caller updates remain outstanding.
}
