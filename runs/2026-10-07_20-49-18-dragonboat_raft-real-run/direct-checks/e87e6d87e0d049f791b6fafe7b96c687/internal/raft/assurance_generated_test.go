package raft

import (
 "encoding/json"
 "fmt"
 "strings"
 "testing"

 "github.com/lni/dragonboat/v3/config"
 pb "github.com/lni/dragonboat/v3/raftpb"
)

func TestAssuranceRemoteReadPrefixContext(t *testing.T) {
 const run = "remote-prefix-loss"
 emit := func(v map[string]interface{}) {
  v["run"] = run
  b, err := json.Marshal(v)
  if err != nil { t.Fatal(err) }
  fmt.Println("CA_EVENT " + string(b))
 }
 contextText := func(c pb.SystemCtx) string { return fmt.Sprintf("%d/%d", c.Low, c.High) }
 type participant struct {
  p *Peer
  db *TestLogDB
  applied uint64
  ready []pb.ReadyToRead
 }
 nodes := make(map[uint64]*participant)
 addresses := []PeerAddress{{NodeID:1, Address:"n1:1234"}, {NodeID:2, Address:"n2:1234"}, {NodeID:3, Address:"n3:1234"}}
 for id := uint64(1); id <= 3; id++ {
  db := NewTestLogDB().(*TestLogDB)
  cfg := config.Config{ClusterID:1, NodeID:id, ElectionRTT:10, HeartbeatRTT:1, CheckQuorum:true}
  p := Launch(cfg, db, nil, append([]PeerAddress(nil), addresses...), true, true)
  nodes[id] = &participant{p:p, db:db}
 }
 // The synchronous driver owns all participants and observations. Each update
 // is saved and applied before messages are delivered; no crash is injected.
 collect := func(id uint64) []pb.Message {
  n := nodes[id]
  ud := n.p.GetUpdate(true, n.applied)
  if !pb.IsEmptySnapshot(ud.Snapshot) { t.Fatal("unexpected snapshot") }
  if err := n.db.Append(ud.EntriesToSave); err != nil { t.Fatal(err) }
  if !pb.IsEmptyState(ud.State) { n.db.SetState(ud.State) }
  for _, e := range ud.CommittedEntries {
   if e.Index != n.applied+1 { t.Fatalf("noncontiguous application %d after %d", e.Index, n.applied) }
   if e.Type == pb.ConfigChangeEntry {
    var cc pb.ConfigChange
    if err := cc.Unmarshal(e.Cmd); err != nil { t.Fatal(err) }
    n.p.ApplyConfigChange(cc)
   } else if !e.IsEmpty() { t.Fatal("unexpected application command") }
   n.applied = e.Index
  }
  out := append([]pb.Message(nil), ud.Messages...)
  n.ready = append(n.ready, ud.ReadyToReads...)
  n.p.Commit(ud)
  n.p.NotifyRaftLastApplied(n.applied)
  return out
 }
 for id := uint64(1); id <= 3; id++ {
  if len(collect(id)) != 0 { t.Fatal("unexpected bootstrap messages") }
 }
 first := pb.SystemCtx{Low:101, High:1001}
 second := pb.SystemCtx{Low:202, High:2002}
 requested := map[uint64]pb.SystemCtx{2:first, 3:second}
 captured := make(map[uint64]pb.SystemCtx)
 released := make(map[uint64]bool)
 replies := make(map[uint64][]pb.Message)
 phase := "setup"
 dropped := 0
 delivered := 0
 pump := func(initial []pb.Message) {
  queue := append([]pb.Message(nil), initial...)
  for len(queue) != 0 {
   if delivered > 1000 { t.Fatal("driver message bound reached") }
   m := queue[0]
   queue = queue[1:]
   // Fixed loss policy: all leader heartbeats carrying the first context
   // are discarded. Remaining messages keep generation order.
   if m.Type == pb.Heartbeat && m.From == 1 && m.Hint == first.Low && m.HintHigh == first.High {
    dropped++
    emit(map[string]interface{}{"event":"dropped", "from":m.From, "to":m.To, "context":contextText(first)})
    continue
   }
   n, ok := nodes[m.To]
   if !ok { t.Fatal("unknown destination") }
   before := make(map[pb.SystemCtx]readStatus)
   if phase == "second" && m.To == 1 && m.Type == pb.HeartbeatResp {
    for c, s := range n.p.raft.readIndex.pending { before[c] = *s }
   }
   if m.Type == pb.ReadIndexResp { replies[m.To] = append(replies[m.To], m) }
   n.p.Handle(m)
   delivered++
   if len(before) != 0 {
    for _, origin := range []uint64{2,3} {
     c, found := captured[origin]
     old, wasPending := before[c]
     _, stillPending := n.p.raft.readIndex.pending[c]
     if found && wasPending && !stillPending {
      if old.from != origin || old.ctx != c || n.p.raft.state != leader || m.Term != n.p.raft.term { t.Fatal("invalid release premise") }
      released[origin] = true
      emit(map[string]interface{}{"event":"released", "operation":fmt.Sprintf("read-on-%d",origin), "request_node":origin, "expected_context":contextText(old.ctx), "term":n.p.raft.term, "reply_from":m.From, "confirmation_context":contextText(pb.SystemCtx{Low:m.Hint,High:m.HintHigh}), "policy":"drop-first-heartbeats", "prefix_size":len(before), "current_term_committed":n.p.raft.hasCommittedEntryAtCurrentTerm()})
     }
    }
   }
   queue = append(queue, collect(m.To)...)
  }
 }
 // Acquire authority through the public tick entry and real vote messages.
 for i:=0; i<30 && nodes[1].p.raft.state != leader; i++ {
  nodes[1].p.Tick()
  pump(collect(1))
 }
 if nodes[1].p.raft.state != leader || !nodes[1].p.raft.hasCommittedEntryAtCurrentTerm() { t.Fatal("leader/current-term commitment not reached") }
 term := nodes[1].p.raft.term
 for id:=uint64(1); id<=3; id++ {
  if nodes[id].applied != nodes[1].p.raft.log.committed || nodes[id].p.raft.term != term { t.Fatal("initial application/term not reached") }
 }
 emit(map[string]interface{}{"event":"setup", "term":term, "committed":nodes[1].p.raft.log.committed, "members":3})
 for _, id := range []uint64{2,3} {
  if id == 2 { phase="first" } else { phase="second" }
  nodes[id].p.ReadIndex(requested[id])
  // Capture leader admission before delivering any generated heartbeat.
  forward := collect(id)
  if len(forward)!=1 || forward[0].Type!=pb.ReadIndex || forward[0].To!=1 { t.Fatal("missing forwarded read") }
  nodes[1].p.Handle(forward[0])
  s, ok := nodes[1].p.raft.readIndex.pending[requested[id]]
  if !ok || s.from!=id || s.ctx!=requested[id] { t.Fatal("read not admitted") }
  captured[id]=s.ctx
  emit(map[string]interface{}{"event":"admitted", "operation":fmt.Sprintf("read-on-%d",id), "request_node":id, "context":contextText(s.ctx), "index":s.index})
  pump(collect(1))
 }
 if dropped != 2 { t.Fatalf("expected first broadcast loss, got %d",dropped) }
 if len(nodes[1].p.raft.readIndex.pending)!=0 || len(nodes[1].p.raft.readIndex.queue)!=0 { t.Fatal("prefix not fully released") }
 for _, id := range []uint64{2,3} {
  if !released[id] { t.Fatal("missing release") }
  wire := []string{}
  for _, m := range replies[id] { wire=append(wire,contextText(pb.SystemCtx{Low:m.Hint,High:m.HintHigh})) }
  ready := []string{}
  for _, r := range nodes[id].ready { ready=append(ready,contextText(r.SystemCtx)) }
  emit(map[string]interface{}{"event":"result", "operation":fmt.Sprintf("read-on-%d",id), "request_node":id, "policy":"drop-first-heartbeats", "completed":true, "reply_contexts":strings.Join(wire,","), "reply_count":len(wire), "ready_contexts":strings.Join(ready,","), "ready_count":len(ready), "term":nodes[id].p.raft.term, "applied":nodes[id].applied})
 }
 // No workers or external resources exist. Every generated non-dropped
 // message has been dispatched and every update committed before results.
}
