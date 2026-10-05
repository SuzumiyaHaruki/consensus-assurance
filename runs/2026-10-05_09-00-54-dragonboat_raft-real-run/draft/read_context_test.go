package raft

import (
 "encoding/json"
 "fmt"
 "testing"

 "github.com/lni/dragonboat/v3/config"
 pb "github.com/lni/dragonboat/v3/raftpb"
)

func assuranceContext(c pb.SystemCtx) string { return fmt.Sprintf("%d:%d", c.Low, c.High) }
func assuranceEvent(t *testing.T, e map[string]interface{}) {
 t.Helper()
 b, err := json.Marshal(e)
 if err != nil { t.Fatal(err) }
 fmt.Println("CA_EVENT " + string(b))
}

// This driver replaces storage, application scheduling and transport only.
// All elections, forwarding, confirmation and response handling use Peer APIs.
func TestAssuranceRemoteReadContext(t *testing.T) {
 const scenario = "prefix_release"
 peers := map[uint64]*Peer{}
 dbs := map[uint64]*TestLogDB{}
 applied := map[uint64]uint64{}
 expected := map[uint64]pb.SystemCtx{2: {Low: 1101, High: 30}, 3: {Low: 2202, High: 30}}
 addresses := []PeerAddress{{NodeID: 1, Address: "n1:1234"}, {NodeID: 2, Address: "n2:1234"}, {NodeID: 3, Address: "n3:1234"}}
 queue := []pb.Message{}
 dropFirst := false
 observed := false
 dropped := 0
 wireCount := map[uint64]int{}
 readyCount := map[uint64]int{}
 releaseCount := map[uint64]int{}
 var term uint64

 for id := uint64(1); id <= 3; id++ {
  dbs[id] = NewTestLogDB().(*TestLogDB)
  peers[id] = Launch(config.Config{NodeID: id, ClusterID: 1, ElectionRTT: 10, HeartbeatRTT: 1, CheckQuorum: true}, dbs[id], nil, append([]PeerAddress(nil), addresses...), true, true)
 }
 // Peer and TestLogDB allocate no background workers or external resources.
 // No production state is mutated by the driver outside documented APIs.
 flush := func(id uint64) {
  p := peers[id]
  ud := p.GetUpdate(true, applied[id])
  if !pb.IsEmptySnapshot(ud.Snapshot) { t.Fatal("unexpected snapshot") }
  if err := dbs[id].Append(ud.EntriesToSave); err != nil { t.Fatal(err) }
  if !pb.IsEmptyState(ud.State) { dbs[id].SetState(ud.State) }
  for _, e := range ud.CommittedEntries {
   if e.Index != applied[id]+1 { t.Fatalf("application gap at node %d", id) }
   if e.Type == pb.ConfigChangeEntry {
    var cc pb.ConfigChange
    if err := cc.Unmarshal(e.Cmd); err != nil { t.Fatal(err) }
    if !cc.Initialize || cc.Type != pb.AddNode { t.Fatal("unexpected configuration change") }
    p.ApplyConfigChange(cc)
   } else if len(e.Cmd) != 0 { t.Fatal("unexpected application payload") }
   applied[id] = e.Index
  }
  for _, rr := range ud.ReadyToReads {
   if observed {
    readyCount[id]++
    assuranceEvent(t, map[string]interface{}{"event":"ready", "scenario":scenario, "origin":id, "context":assuranceContext(rr.SystemCtx), "index":rr.Index, "applied":applied[id], "term":p.raft.term})
   } else { t.Fatal("readiness before requests") }
  }
  for _, m := range ud.Messages {
   if observed && m.Type == pb.ReadIndexResp {
    wireCount[m.To]++
    assuranceEvent(t, map[string]interface{}{"event":"wire", "scenario":scenario, "origin":m.To, "from":m.From, "context":assuranceContext(pb.SystemCtx{Low:m.Hint, High:m.HintHigh}), "term":m.Term, "index":m.LogIndex})
   }
   if dropFirst && m.Type == pb.Heartbeat && m.Hint == expected[2].Low && m.HintHigh == expected[2].High {
    dropped++
    assuranceEvent(t, map[string]interface{}{"event":"loss", "scenario":scenario, "from":m.From, "to":m.To, "context":assuranceContext(expected[2])})
    continue
   }
   // Copy message entry storage before acknowledging its update.
   m.Entries = append([]pb.Entry(nil), m.Entries...)
   queue = append(queue, m)
  }
  p.Commit(ud)
  p.NotifyRaftLastApplied(applied[id])
 }
 deliver := func() {
  if len(queue)==0 { t.Fatal("empty delivery queue") }
  m := queue[0]
  queue = queue[1:]
  p := peers[m.To]
  before := map[uint64]bool{}
  if observed && m.To==1 && m.Type==pb.HeartbeatResp {
   for origin, ctx := range expected { _, before[origin] = p.raft.readIndex.pending[ctx] }
  }
  p.Handle(m)
  for origin, existed := range before {
   _, remains := p.raft.readIndex.pending[expected[origin]]
   if existed && !remains {
    if !p.raft.isLeader() || p.raft.term!=term { t.Fatal("authority changed during confirmation") }
    releaseCount[origin]++
    assuranceEvent(t, map[string]interface{}{"event":"released", "scenario":scenario, "origin":origin, "removed":true, "term":p.raft.term, "response_from":m.From, "confirming_context":assuranceContext(pb.SystemCtx{Low:m.Hint, High:m.HintHigh})})
   }
  }
  flush(m.To)
 }
 drain := func() {
  for steps:=0; len(queue)>0; steps++ {
   if steps>=500 { t.Fatal("message drain bound reached") }
   deliver()
  }
 }
 for id:=uint64(1); id<=3; id++ { flush(id) }
 drain()
 for ticks:=0; !peers[1].raft.isLeader() && ticks<50; ticks++ {
  peers[1].Tick()
  flush(1)
  drain()
 }
 if !peers[1].raft.isLeader() || !peers[1].raft.hasCommittedEntryAtCurrentTerm() { t.Fatal("current-term committed leader not reached") }
 term=peers[1].raft.term
 for id:=uint64(1); id<=3; id++ {
  p:=peers[id]
  if p.raft.term!=term || p.raft.leaderID!=1 || applied[id]!=p.raft.log.committed || p.raft.numVotingMembers()!=3 { t.Fatalf("prefix incomplete at node %d",id) }
 }
 observed=true
 dropFirst=true
 peers[2].ReadIndex(expected[2])
 flush(2)
 drain()
 dropFirst=false
 if dropped!=2 || len(peers[1].raft.readIndex.pending)!=1 { t.Fatal("first pending request / first round loss not established") }
 peers[3].ReadIndex(expected[3])
 flush(3)
 if len(queue)!=1 || queue[0].Type!=pb.ReadIndex || queue[0].From!=3 || queue[0].To!=1 { t.Fatal("second forwarded request not reached") }
 deliver()
 if len(peers[1].raft.readIndex.pending)!=2 || len(peers[1].raft.readIndex.queue)!=2 { t.Fatal("coexisting requests not reached") }
 for _, origin:=range []uint64{2,3} {
  ctx:=expected[origin]
  status,ok:=peers[1].raft.readIndex.pending[ctx]
  if !ok || status.from!=origin || status.ctx!=ctx { t.Fatal("leader admission differs from caller request") }
  assuranceEvent(t,map[string]interface{}{"event":"admitted", "scenario":scenario, "origin":origin, "expected_context":assuranceContext(ctx), "term":term, "leader":uint64(1), "pending_count":len(peers[1].raft.readIndex.pending), "current_term_committed":peers[1].raft.hasCommittedEntryAtCurrentTerm(), "first_round_drops":dropped})
 }
 drain()
 // End after finite queue exhaustion, independently of whether contexts match.
 for _, origin:=range []uint64{2,3} {
  assuranceEvent(t,map[string]interface{}{"event":"diagnostic", "scenario":scenario, "origin":origin, "wire_count":wireCount[origin], "ready_count":readyCount[origin], "release_count":releaseCount[origin], "leader_pending":len(peers[1].raft.readIndex.pending), "remaining_messages":len(queue)})
 }
}
