package raft

import (
 "encoding/json"
 "fmt"
 "testing"

 "github.com/lni/dragonboat/v3/config"
 pb "github.com/lni/dragonboat/v3/raftpb"
)

func TestAssuranceWitnessRecoveryExploration(t *testing.T) {
 const run = "witness-recovery"
 emit := func(v map[string]interface{}) {
  v["run"] = run
  b, err := json.Marshal(v)
  if err != nil { t.Fatal(err) }
  fmt.Println("CA_EVENT " + string(b))
 }
 type participant struct {
  p *Peer
  db *TestLogDB
  applied uint64
  ready []pb.ReadyToRead
 }
 nodes := make(map[uint64]*participant)
 addresses := []PeerAddress{{NodeID:1, Address:"n1:1234"}, {NodeID:2, Address:"n2:1234"}}
 for id := uint64(1); id <= 3; id++ {
  db := NewTestLogDB().(*TestLogDB)
  cfg := config.Config{ClusterID:1, NodeID:id, ElectionRTT:10, HeartbeatRTT:1, CheckQuorum:true}
  cfg.IsWitness = id == 3
  var p *Peer
  if id == 3 { p = Launch(cfg, db, nil, nil, false, true) } else { p = Launch(cfg, db, nil, append([]PeerAddress(nil), addresses...), true, true) }
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
   } // Application payloads are counted as applied only for this Raft-only exploration.
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
 phase := "setup"
 dropped := 0
 rejections := 0
 steps := 0
 pump := func(initial []pb.Message) {
  queue := append([]pb.Message(nil), initial...)
  for len(queue)>0 {
   steps++
   if steps>10000 { t.Fatal("message bound") }
   m:=queue[0]; queue=queue[1:]
   if (phase=="lag-full" && m.To==2 && m.From==1) || (phase=="leader-down" && (m.To==1 || m.From==1)) { dropped++; continue }
   if phase=="leader-down" && m.Type==pb.RequestVoteResp && m.From==3 && m.Reject { rejections++ }
   nodes[m.To].p.Handle(m)
   queue=append(queue,collect(m.To)...)
  }
 }
 for i:=0;i<30 && nodes[1].p.raft.state!=leader;i++ { nodes[1].p.Tick();pump(collect(1)) }
 if nodes[1].p.raft.state!=leader || !nodes[1].p.raft.hasCommittedEntryAtCurrentTerm() { t.Fatal("election failed") }
 // Commit and apply a real membership change before joining witness traffic.
 nodes[1].p.ProposeConfigChange(pb.ConfigChange{Type:pb.AddWitness,NodeID:3,Address:"n3:1234"},1)
 pump(collect(1))
 for i:=0;i<5;i++ {nodes[1].p.Tick();pump(collect(1))}
 for id:=uint64(1);id<=3;id++ {
  if len(nodes[id].p.raft.remotes)!=2 || len(nodes[id].p.raft.witnesses)!=1 {t.Fatal("membership not established")}
  if nodes[id].p.raft.log.committed!=nodes[1].p.raft.log.committed {t.Fatal("join not caught up")}
 }
 before:=nodes[1].p.raft.log.committed
 phase="lag-full"
 nodes[1].p.ProposeEntries([]pb.Entry{{Type:pb.ApplicationEntry,Cmd:[]byte("payload")}})
 pump(collect(1))
 idx:=nodes[1].p.raft.log.committed
 if idx!=before+1 || nodes[2].p.raft.log.lastIndex()!=before || nodes[3].p.raft.log.committed!=idx {t.Fatal("asymmetric commitment premise missing")}
 ents,err:=nodes[3].p.raft.log.entries(idx,1024)
 if err!=nil || len(ents)!=1 {t.Fatal("witness entry not observed")}
 emit(map[string]interface{}{"event":"committed","index":idx,"full2_last":nodes[2].p.raft.log.lastIndex(),"witness_type":ents[0].Type.String(),"witness_payload_bytes":len(ents[0].Cmd),"term":nodes[1].p.raft.term})
 phase="leader-down"
 for i:=0;i<100;i++ {
  nodes[2].p.Tick();pump(collect(2))
  nodes[3].p.Tick();pump(collect(3))
 }
 emit(map[string]interface{}{"event":"bounded_suffix","ticks_each":100,"full2_state":nodes[2].p.raft.state.String(),"witness_state":nodes[3].p.raft.state.String(),"vote_rejections":rejections,"full2_last":nodes[2].p.raft.log.lastIndex(),"witness_last":nodes[3].p.raft.log.lastIndex(),"full2_term":nodes[2].p.raft.term,"witness_term":nodes[3].p.raft.term,"dropped":dropped})
}
