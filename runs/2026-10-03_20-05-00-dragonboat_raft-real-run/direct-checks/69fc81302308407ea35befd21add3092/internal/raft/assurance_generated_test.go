package raft

import (
 "encoding/json"
 "fmt"
 "testing"

 "github.com/lni/dragonboat/v3/config"
 pb "github.com/lni/dragonboat/v3/raftpb"
)

func assuranceEmit(v map[string]interface{}) {
 b, err := json.Marshal(v)
 if err != nil { panic(err) }
 fmt.Println("CA_EVENT " + string(b))
}
func assuranceCtx(c pb.SystemCtx) string { return fmt.Sprintf("%d:%d", c.High, c.Low) }

type assuranceCluster struct {
 t *testing.T
 scenario string
 peers map[uint64]*Peer
 stores map[uint64]*TestLogDB
 applied map[uint64]uint64
 active bool
 results map[uint64]int
}

// The in-memory store substitutes crash-free persistence. No target handler,
// quorum, pending status, term, vote or response is modified by the driver.
func (c *assuranceCluster) harvest(id uint64) []pb.Message {
 p := c.peers[id]
 if !p.HasUpdate(true) { return nil }
 ud := p.GetUpdate(true, c.applied[id])
 db := c.stores[id]
 if !pb.IsEmptyState(ud.State) { db.SetState(ud.State) }
 if err := db.Append(ud.EntriesToSave); err != nil { c.t.Fatal(err) }
 if !pb.IsEmptySnapshot(ud.Snapshot) { c.t.Fatal("unexpected snapshot in uncompacted prefix") }
 for _, e := range ud.CommittedEntries {
  if e.Type == pb.ConfigChangeEntry {
   var cc pb.ConfigChange
   if err := cc.Unmarshal(e.Cmd); err != nil { c.t.Fatal(err) }
   p.ApplyConfigChange(cc)
  }
  // Only bootstrap configurations and election no-op entries are present.
  if e.Type != pb.ConfigChangeEntry && len(e.Cmd) != 0 { c.t.Fatal("unexpected application payload") }
  c.applied[id] = e.Index
 }
 for _, v := range ud.ReadyToReads {
  if !c.active { c.t.Fatal("read result before any read invocation") }
  c.results[id]++
  assuranceEmit(map[string]interface{}{"event":"read_result", "scenario":c.scenario, "origin":id, "observed":true, "context":assuranceCtx(v.SystemCtx), "index":v.Index, "applied":c.applied[id], "term":p.raft.term})
 }
 // Copy outgoing descriptors before Commit releases the peer's output queue.
 msgs := append([]pb.Message(nil), ud.Messages...)
 p.Commit(ud)
 p.NotifyRaftLastApplied(c.applied[id])
 return msgs
}
func (c *assuranceCluster) pump(queue []pb.Message) {
 for steps:=0; len(queue)>0; steps++ {
  if steps>1000 { c.t.Fatal("network did not drain") }
  m:=queue[0]; queue=queue[1:]
  p,ok:=c.peers[m.To]; if !ok { c.t.Fatalf("unknown destination %d",m.To) }
  if c.active { assuranceEmit(map[string]interface{}{"event":"wire", "scenario":c.scenario,"from":m.From,"to":m.To,"type":m.Type.String(),"term":m.Term,"low":m.Hint,"high":m.HintHigh}) }
  p.Handle(m)
  queue=append(queue,c.harvest(m.To)...)
 }
}
func assuranceNew(t *testing.T, scenario string) *assuranceCluster {
 c:=&assuranceCluster{t:t,scenario:scenario,peers:make(map[uint64]*Peer),stores:make(map[uint64]*TestLogDB),applied:make(map[uint64]uint64),results:make(map[uint64]int)}
 for id:=uint64(1);id<=3;id++ {
  db:=NewTestLogDB().(*TestLogDB); c.stores[id]=db
  cfg:=config.Config{ClusterID:1,NodeID:id,ElectionRTT:10,HeartbeatRTT:1}
  c.peers[id]=Launch(cfg,db,nil,[]PeerAddress{{NodeID:1},{NodeID:2},{NodeID:3}},true,true)
  c.pump(c.harvest(id))
 }
 for i:=0;i<100 && !c.peers[1].raft.isLeader();i++ { c.peers[1].Tick(); c.pump(c.harvest(1)) }
 if !c.peers[1].raft.isLeader() { t.Fatal("leader not elected") }
 // The winning vote generated a no-op and replication; pump drained it.
 if !c.peers[1].raft.hasCommittedEntryAtCurrentTerm() { t.Fatal("current term not committed") }
 for id:=uint64(1);id<=3;id++ {
  if c.peers[id].raft.leaderID!=1 || c.peers[id].raft.term!=c.peers[1].raft.term || c.applied[id]!=c.peers[1].raft.log.committed { t.Fatal("prefix not synchronized") }
 }
 c.active=true
 assuranceEmit(map[string]interface{}{"event":"prefix", "scenario":scenario,"leader":1,"term":c.peers[1].raft.term,"commit":c.peers[1].raft.log.committed})
 return c
}

// Each origin has exactly one invocation in each fresh scenario, allowing
// result correlation by scenario+origin independently of the compared context.
func (c *assuranceCluster) admit(origin uint64, ctx pb.SystemCtx) []pb.Message {
 c.peers[origin].ReadIndex(ctx)
 forwarded:=c.harvest(origin)
 if len(forwarded)!=1 || forwarded[0].Type!=pb.ReadIndex || forwarded[0].To!=1 || forwarded[0].From!=origin { c.t.Fatal("unexpected forwarding") }
 c.peers[1].Handle(forwarded[0])
 s,ok:=c.peers[1].raft.readIndex.pending[ctx]
 if !ok || s.from!=origin { c.t.Fatal("read was not admitted") }
 assuranceEmit(map[string]interface{}{"event":"read_admitted","scenario":c.scenario,"origin":origin,"context":assuranceCtx(ctx),"index":s.index,"term":c.peers[1].raft.term})
 return c.harvest(1)
}
func TestAssuranceReadContext(t *testing.T) {
 for _,scenario:=range []string{"serial_control","overlap"} {
  t.Run(scenario,func(t *testing.T){
   c:=assuranceNew(t,scenario)
   earlier:=c.admit(2,pb.SystemCtx{Low:201,High:901})
   if scenario=="serial_control" { c.pump(earlier); earlier=nil }
   later:=c.admit(3,pb.SystemCtx{Low:302,High:902})
   c.pump(later)
   // Deliver all held traffic even after the later confirmation. Termination
   // is queue exhaustion, never the presence or absence of a mismatch.
   c.pump(earlier)
   assuranceEmit(map[string]interface{}{"event":"drained","scenario":scenario,"pending":len(c.peers[1].raft.readIndex.pending),"origin2_results":c.results[2],"origin3_results":c.results[3]})
  })
 }
}
