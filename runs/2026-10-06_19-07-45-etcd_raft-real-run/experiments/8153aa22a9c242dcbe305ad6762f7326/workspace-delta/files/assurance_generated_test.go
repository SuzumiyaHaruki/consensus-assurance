package raft

import (
 "encoding/json"
 "fmt"
 "testing"

 pb "go.etcd.io/raft/v3/raftpb"
)

// The single test goroutine owns all nodes, storage, queues and observations.
// No protocol fields are modified by this driver.
func TestAssuranceJointExitTransfer(t *testing.T) {
 for _, transfer := range []bool{false, true} {
  name := "control"
  if transfer { name = "transfer" }
  t.Run(name, func(t *testing.T) {
   nodes := map[uint64]*RawNode{}
   stores := map[uint64]*MemoryStorage{}
   applied := map[uint64]uint64{}
   var queue []pb.Message
   triggered := false
   dropTimeout := transfer
   dropped, delivered, readyBatches := 0, 0, 0
   var jointIndex uint64
   emit := func(phase string) {
    r := nodes[1].raft
    b, err := json.Marshal(map[string]interface{}{
     "scenario": name, "phase": phase, "node": uint64(1), "joint_index": jointIndex,
     "term": r.Term, "role": r.state.String(), "lead": r.lead,
     "transfer_target": r.leadTransferee, "auto_leave": r.trk.Config.AutoLeave,
     "configuration": r.trk.ConfState(), "last": r.raftLog.lastIndex(),
     "committed": r.raftLog.committed, "applied": r.raftLog.applied,
     "pending_conf": r.pendingConfIndex, "queued": len(queue),
     "dropped_timeout_now": dropped, "delivered": delivered, "ready_batches": readyBatches,
    })
    if err != nil { t.Fatal(err) }
    fmt.Println("CA_EVENT " + string(b))
   }
   for id := uint64(1); id <= 3; id++ {
    s := NewMemoryStorage()
    rn, err := NewRawNode(&Config{ID:id, ElectionTick:10, HeartbeatTick:1, Storage:s, MaxSizePerMsg:1<<20, MaxInflightMsgs:256, CheckQuorum:true})
    if err != nil { t.Fatal(err) }
    if err := rn.Bootstrap([]Peer{{ID:1},{ID:2},{ID:3}}); err != nil { t.Fatal(err) }
    nodes[id], stores[id] = rn, s
   }
   pump := func() {
    for iteration := 0; iteration < 10000; iteration++ {
     work := false
     for id := uint64(1); id <= 3; id++ {
      rn, s := nodes[id], stores[id]
      if !rn.HasReady() { continue }
      work = true
      readyBatches++
      rd := rn.Ready()
      if !IsEmptySnap(rd.Snapshot) { t.Fatal("unexpected snapshot in uncompacted test") }
      if err := s.Append(rd.Entries); err != nil { t.Fatal(err) }
      if !IsEmptyHardState(rd.HardState) {
       if err := s.SetHardState(rd.HardState); err != nil { t.Fatal(err) }
      }
      // Persistence precedes sending every message, including responses.
      queue = append(queue, rd.Messages...)
      for _, e := range rd.CommittedEntries {
       if e.Index != applied[id]+1 { t.Fatalf("node %d nonconsecutive apply %d after %d", id, e.Index, applied[id]) }
       switch e.Type {
       case pb.EntryConfChange:
        var cc pb.ConfChange
        if err := cc.Unmarshal(e.Data); err != nil { t.Fatal(err) }
        rn.ApplyConfChange(cc)
       case pb.EntryConfChangeV2:
        var cc pb.ConfChangeV2
        if err := cc.Unmarshal(e.Data); err != nil { t.Fatal(err) }
        rn.ApplyConfChange(cc)
        if id == 1 && cc.Transition == pb.ConfChangeTransitionJointImplicit && !triggered {
         triggered = true
         jointIndex = e.Index
         if transfer { rn.TransferLeader(2) }
         emit("joint_applied_before_advance")
        }
       }
       applied[id] = e.Index
      }
      rn.Advance(rd)
     }
     if len(queue) != 0 {
      work = true
      m := queue[0]
      queue = queue[1:]
      if dropTimeout && m.Type == pb.MsgTimeoutNow {
       dropped++
      } else {
       delivered++
       err := nodes[m.To].Step(m)
       // Late responses from a removed member are ordinary network inputs.
       if err != nil && err != ErrStepPeerNotFound { t.Fatal(err) }
      }
     }
     if !work { return }
    }
    t.Fatal("pump did not quiesce within construction bound")
   }
   pump()
   if err := nodes[1].Campaign(); err != nil { t.Fatal(err) }
   pump()
   if nodes[1].raft.state != StateLeader { t.Fatal("leader prerequisite not reached") }
   emit("elected")
   cc := pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit, Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode, NodeID:3}}}
   if err := nodes[1].ProposeConfChange(cc); err != nil { t.Fatal(err) }
   pump()
   if !triggered { t.Fatal("joint entry not applied") }
   emit("after_joint_completion")
   // No further network losses after the original TimeoutNow messages drain.
   dropTimeout = false
   for tick := 1; tick <= 100; tick++ {
    for id := uint64(1); id <= 3; id++ { nodes[id].Tick() }
    pump()
    if tick == 10 || tick == 20 || tick == 100 { emit(fmt.Sprintf("tick_%d",tick)) }
   }
   // A separately labelled diagnostic stimulus tests the later-entry retry path.
   if err := nodes[1].Propose([]byte("diagnostic-rescue")); err != nil { t.Fatal(err) }
   pump()
   emit("after_rescue_entry")
  })
 }
}
