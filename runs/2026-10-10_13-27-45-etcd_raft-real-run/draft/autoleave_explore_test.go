package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

// Exercise real Bootstrap, Campaign, proposal, persistence, and application paths.
// Only network MsgTimeoutNow packets are lost; no protocol state is assigned.
func TestAssuranceAutoLeaveTransfer(t *testing.T) {
 for _, transfer := range []bool{false, true} {
  t.Run(fmt.Sprintf("transfer_%v", transfer), func(t *testing.T) {
   nodes := map[uint64]*RawNode{}
   stores := map[uint64]*MemoryStorage{}
   appIndex := map[uint64]uint64{}
   var queue []pb.Message
   var jointIndex uint64
   started := false
   dropped := 0
   advances := 0
   emit := func(stage string) {
    r := nodes[1].raft
    event := map[string]interface{}{
     "scenario": fmt.Sprintf("transfer_%v", transfer), "stage": stage,
     "node": uint64(1), "term": r.Term, "role": r.state.String(),
     "leader": r.lead, "transferee": r.leadTransferee,
     "conf": r.trk.ConfState(), "joint_index": jointIndex,
     "commit": r.raftLog.committed, "raft_applied": r.raftLog.applied,
     "app_applied": appIndex[1], "last_index": r.raftLog.lastIndex(),
     "pending_conf_index": r.pendingConfIndex, "dropped_timeout_now": dropped,
     "advance_count": advances, "queue_length": len(queue),
    }
    b, err := json.Marshal(event); if err != nil { t.Fatal(err) }
    fmt.Println("CA_EVENT " + string(b))
   }
   for id := uint64(1); id <= 3; id++ {
    s := NewMemoryStorage()
    rn, err := NewRawNode(&Config{ID:id, ElectionTick:10, HeartbeatTick:1,
     Storage:s, MaxSizePerMsg:4096, MaxInflightMsgs:256, CheckQuorum:true})
    if err != nil { t.Fatal(err) }
    nodes[id], stores[id] = rn, s
    if err := rn.Bootstrap([]Peer{{ID:1},{ID:2},{ID:3}}); err != nil { t.Fatal(err) }
   }
   // Drain all Ready work and network messages before returning. Each Ready is
   // persisted and applied before Advance; message delivery is FIFO after loss.
   pump := func() {
    for iterations := 0; iterations < 10000; iterations++ {
     work := false
     for id := uint64(1); id <= 3; id++ {
      rn, s := nodes[id], stores[id]
      if !rn.HasReady() { continue }
      work = true
      rd := rn.Ready()
      if !IsEmptySnap(rd.Snapshot) { t.Fatal("unexpected snapshot") }
      if err := s.Append(rd.Entries); err != nil { t.Fatal(err) }
      if !IsEmptyHardState(rd.HardState) {
       if err := s.SetHardState(rd.HardState); err != nil { t.Fatal(err) }
      }
      queue = append(queue, rd.Messages...)
      for _, e := range rd.CommittedEntries {
       if e.Index != appIndex[id]+1 { t.Fatalf("node %d nonconsecutive application %d after %d", id,e.Index,appIndex[id]) }
       switch e.Type {
       case pb.EntryConfChange:
        var cc pb.ConfChange
        if err := cc.Unmarshal(e.Data); err != nil { t.Fatal(err) }
        rn.ApplyConfChange(cc)
       case pb.EntryConfChangeV2:
        var cc pb.ConfChangeV2
        if err := cc.Unmarshal(e.Data); err != nil { t.Fatal(err) }
        cs := rn.ApplyConfChange(cc)
        if id == 1 && len(cc.Changes) > 0 {
         jointIndex = e.Index
         if !cs.AutoLeave || len(cs.VotersOutgoing)==0 { t.Fatal("joint setup missing") }
         // This is a serial public API call while processing the committed
         // joint entry, before its Ready completion notification.
         if transfer && !started {
          started = true
          rn.TransferLeader(2)
          emit("transfer_started_before_advance")
         }
        }
       }
       appIndex[id] = e.Index
      }
      rn.Advance(rd)
      if id == 1 { advances++ }
     }
     if len(queue)>0 {
      work = true
      m := queue[0]; queue = queue[1:]
      if transfer && m.Type == pb.MsgTimeoutNow {
       dropped++
      } else if err := nodes[m.To].Step(m); err != nil {
       // The leader may legitimately ignore a response from removed node 3.
       if err != ErrStepPeerNotFound { t.Fatal(err) }
      }
     }
     if !work { return }
    }
    t.Fatal("pump did not quiesce")
   }
   pump()
   if err := nodes[1].Campaign(); err != nil { t.Fatal(err) }
   pump()
   if nodes[1].raft.state != StateLeader { t.Fatal("election failed") }
   emit("elected")
   cc := pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,
    Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}},
    Context:[]byte("remove-three-operation")}
   if err := nodes[1].ProposeConfChange(cc); err != nil { t.Fatal(err) }
   pump()
   if jointIndex==0 { t.Fatal("joint entry never applied") }
   emit("joint_ready_drained")
   // Deliver every heartbeat and response. Tick the live leader first and
   // drain before ticking followers, so stable authority remains observable.
   for tick:=1; tick<=30; tick++ {
    nodes[1].Tick(); pump()
    nodes[2].Tick(); nodes[3].Tick(); pump()
    if tick==10 || tick==11 || tick==30 { emit(fmt.Sprintf("after_tick_%d", tick)) }
   }
   emit("before_external_proposal")
   if err := nodes[1].Propose([]byte("resume-application-operation")); err != nil { t.Fatal(err) }
   pump()
   emit("after_external_proposal")
  })
 }
}
