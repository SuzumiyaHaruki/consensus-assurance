package raft

import (
 "encoding/json"
 "fmt"
 "testing"

 "github.com/lni/dragonboat/v3/config"
 pb "github.com/lni/dragonboat/v3/raftpb"
)

type assuranceReadNode struct {
 peer *Peer
 db *TestLogDB
 applied uint64
 ready []pb.ReadyToRead
}

type assuranceReadNetwork struct {
 t *testing.T
 nodes map[uint64]*assuranceReadNode
 queue []pb.Message
 sent []pb.Message
 phase string
 dropCtx pb.SystemCtx
 dropped int
}

func assuranceReadEvent(v map[string]interface{}) {
 b, err := json.Marshal(v)
 if err != nil { panic(err) }
 fmt.Println("CA_EVENT " + string(b))
}

func (n *assuranceReadNetwork) collect(id uint64) {
 x := n.nodes[id]
 if !x.peer.HasUpdate(true) { return }
 u := x.peer.GetUpdate(true, x.applied)
 // Complete storage work before exposing messages, including all ordinary replies.
 if err := x.db.Append(u.EntriesToSave); err != nil { n.t.Fatal(err) }
 if !pb.IsEmptyState(u.State) { x.db.SetState(u.State) }
 if !pb.IsEmptySnapshot(u.Snapshot) { n.t.Fatal("unexpected snapshot") }
 messages := append([]pb.Message(nil), u.Messages...)
 x.ready = append(x.ready, u.ReadyToReads...)
 for _, e := range u.CommittedEntries {
  if e.Type == pb.ConfigChangeEntry {
   var cc pb.ConfigChange
   if err := cc.Unmarshal(e.Cmd); err != nil { n.t.Fatal(err) }
   x.peer.ApplyConfigChange(cc)
  } else if len(e.Cmd) != 0 { n.t.Fatal("unexpected application command") }
  x.applied = e.Index
 }
 x.peer.Commit(u)
 x.peer.NotifyRaftLastApplied(x.applied)
 for _, m := range messages {
  n.sent = append(n.sent, m)
  drop := n.phase == "reads" && m.Type == pb.Heartbeat && m.Hint == n.dropCtx.Low && m.HintHigh == n.dropCtx.High
  assuranceReadEvent(map[string]interface{}{"event":"wire","phase":n.phase,"from":m.From,"to":m.To,"type":m.Type.String(),"term":m.Term,"low":m.Hint,"high":m.HintHigh,"dropped":drop})
  if drop { n.dropped++; continue }
  n.queue = append(n.queue, m)
 }
}

func (n *assuranceReadNetwork) step() {
 if len(n.queue) == 0 { n.t.Fatal("no message available") }
 m := n.queue[0]
 n.queue = n.queue[1:]
 n.nodes[m.To].peer.Handle(m)
 n.collect(m.To)
}

func (n *assuranceReadNetwork) drain() {
 for steps := 0; len(n.queue)>0; steps++ {
  if steps >= 1000 { n.t.Fatal("message drain bound exceeded") }
  n.step()
 }
}

func TestAssuranceReadPrefixIdentity(t *testing.T) {
 n := &assuranceReadNetwork{t:t,nodes:make(map[uint64]*assuranceReadNode),phase:"setup",dropCtx:pb.SystemCtx{Low:1001,High:101}}
 addresses := []PeerAddress{{NodeID:1,Address:"n1"},{NodeID:2,Address:"n2"},{NodeID:3,Address:"n3"}}
 for id:=uint64(1);id<=3;id++ {
  db := NewTestLogDB().(*TestLogDB)
  p := Launch(config.Config{ClusterID:77,NodeID:id,ElectionRTT:10,HeartbeatRTT:1,CheckQuorum:true},db,nil,addresses,true,true)
  n.nodes[id]=&assuranceReadNode{peer:p,db:db}
  n.collect(id)
 }
 n.drain()
 for tick:=0;tick<25 && !n.nodes[1].peer.raft.isLeader();tick++ {
  n.nodes[1].peer.Tick(); n.collect(1); n.drain()
 }
 leader:=n.nodes[1].peer.raft
 if !leader.isLeader() || !leader.hasCommittedEntryAtCurrentTerm() { t.Fatal("election/current-term commit prerequisite not reached") }
 term:=leader.term
 for id:=uint64(1);id<=3;id++ {
  r:=n.nodes[id].peer.raft
  if r.term!=term || r.leaderID!=1 || r.log.committed!=leader.log.committed || n.nodes[id].applied!=leader.log.committed { t.Fatalf("node %d not synchronized",id) }
 }
 if len(n.queue)!=0 { t.Fatal("setup queue not drained") }
 n.phase="reads"
 n.sent=nil
 contexts:=map[uint64]pb.SystemCtx{2:n.dropCtx,3:{Low:2001,High:202}}
 // Only the initial confirmation heartbeats are lost. No surviving message is reordered.
 n.nodes[2].peer.ReadIndex(contexts[2]); n.collect(2); n.drain()
 if n.dropped!=2 || len(leader.readIndex.pending)!=1 { t.Fatal("first pending read/loss prerequisite not reached") }
 n.nodes[3].peer.ReadIndex(contexts[3]); n.collect(3)
 if len(n.queue)!=1 || n.queue[0].Type!=pb.ReadIndex || n.queue[0].From!=3 || n.queue[0].To!=1 { t.Fatal("second forward prerequisite not reached") }
 n.step() // Register the second request; its real heartbeat messages remain queued.
 if len(leader.readIndex.pending)!=2 || len(leader.readIndex.queue)!=2 { t.Fatal("two pending reads prerequisite not reached") }
 for _,id:=range []uint64{2,3} {
  ctx:=contexts[id]
  status,ok:=leader.readIndex.pending[ctx]
  if !ok || status.from!=id || status.ctx!=ctx || len(status.confirmed)!=0 { t.Fatal("pending identity prerequisite mismatch") }
  expected,_:=json.Marshal([]pb.SystemCtx{ctx})
  assuranceReadEvent(map[string]interface{}{"event":"admitted","scenario":"remote_prefix","requester":id,"queued":ok,"current_term_committed":leader.hasCommittedEntryAtCurrentTerm(),"term":term,"expected_contexts":string(expected),"pending_count":len(leader.readIndex.pending),"sampled_index":status.index,"dropped_heartbeats":n.dropped})
 }
 n.drain()
 if leader.term!=term || !leader.isLeader() { t.Fatal("authority changed unexpectedly") }
 for _,id:=range []uint64{2,3} {
  ctx:=contexts[id]
  _,stillPending:=leader.readIndex.pending[ctx]
  actual:=make([]pb.SystemCtx,0)
  for _,m:=range n.sent {
   if m.Type==pb.ReadIndexResp && m.To==id {
    actual=append(actual,pb.SystemCtx{Low:m.Hint,High:m.HintHigh})
   }
  }
  encoded,_:=json.Marshal(actual)
  assuranceReadEvent(map[string]interface{}{"event":"publication","scenario":"remote_prefix","requester":id,"released":!stillPending,"term":leader.term,"actual_contexts":string(encoded),"response_count":len(actual),"leader_pending":len(leader.readIndex.pending),"queue_empty":len(n.queue)==0,"follower_ready":n.nodes[id].ready,"applied":n.nodes[id].applied})
 }
}
