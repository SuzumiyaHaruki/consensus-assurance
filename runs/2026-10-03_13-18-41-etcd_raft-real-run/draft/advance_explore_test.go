package raft

import (
 "context"
 "encoding/json"
 "fmt"
 "testing"
 "time"
 pb "go.etcd.io/raft/v3/raftpb"
)

// The restart image substitutes the preceding producer history. This exploration
// measures public API consumption, not a complete multi-node safety history.
func TestAssuranceAdvanceCampaignExploration(t *testing.T) {
 for _, early := range []bool{false, true} {
  name := "configuration_before_advance"
  if early { name = "advance_before_configuration" }
  t.Run(name, func(t *testing.T) {
   ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
   defer cancel()
   store := NewMemoryStorage()
   snap := pb.Snapshot{Metadata: pb.SnapshotMetadata{
    Index: 1, Term: 1, ConfState: pb.ConfState{Voters: []uint64{1,2,3}},
   }}
   if err := store.ApplySnapshot(snap); err != nil { t.Fatal(err) }
   cc := pb.ConfChange{Type: pb.ConfChangeRemoveNode, NodeID: 2}
   data, err := cc.Marshal()
   if err != nil { t.Fatal(err) }
   ent := pb.Entry{Index: 2, Term: 1, Type: pb.EntryConfChange, Data: data}
   if err := store.Append([]pb.Entry{ent}); err != nil { t.Fatal(err) }
   if err := store.SetHardState(pb.HardState{Term:1, Commit:2}); err != nil { t.Fatal(err) }
   n := RestartNode(&Config{ID:2, ElectionTick:10, HeartbeatTick:1,
    Storage:store, Applied:1, MaxSizePerMsg:4096, MaxInflightMsgs:256})
   defer n.Stop()
   observe := func(stage string) {
    s := n.Status()
    _, voter := s.Config.Voters.IDs()[2]
    event := map[string]interface{}{"scenario":name,"stage":stage,
     "node":s.ID,"term":s.Term,"commit":s.Commit,"applied":s.Applied,
     "state":s.RaftState.String(),"self_voter":voter}
    b, err := json.Marshal(event)
    if err != nil { t.Fatal(err) }
    fmt.Println("CA_EVENT " + string(b))
   }
   var rd Ready
   select {
   case rd = <-n.Ready():
   case <-ctx.Done(): t.Fatal("initial Ready not received",ctx.Err())
   }
   if len(rd.CommittedEntries)!=1 || rd.CommittedEntries[0].Index!=2 || rd.CommittedEntries[0].Type!=pb.EntryConfChange {
    t.Fatalf("unexpected restart Ready: %+v",rd)
   }
   // Persist all batch state before Advance. MemoryStorage models completed
   // persistence without introducing a crash; no messages are transmitted.
   if len(rd.Entries)>0 { if err := store.Append(rd.Entries); err != nil {t.Fatal(err)} }
   if !IsEmptyHardState(rd.HardState) { if err := store.SetHardState(rd.HardState); err != nil {t.Fatal(err)} }
   if !IsEmptySnap(rd.Snapshot) { if err := store.ApplySnapshot(rd.Snapshot); err != nil {t.Fatal(err)} }
   observe("ready_received_persisted")
   if err := n.Campaign(ctx); err != nil {t.Fatal(err)}
   observe("campaign_before_application_accounting")
   if !early { n.ApplyConfChange(cc) }
   n.Advance()
   observe("advance_completed")
   if err := n.Campaign(ctx); err != nil {t.Fatal(err)}
   observe("campaign_after_advance")
   if early { n.ApplyConfChange(cc) }
   observe("configuration_callback_completed")
   // No second Ready is accepted, no votes are delivered, and no leader or
   // system-level safety conclusion is asserted by this exploration.
  })
 }
}
