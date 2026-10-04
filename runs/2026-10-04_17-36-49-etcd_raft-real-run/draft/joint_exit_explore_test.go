package raft

import (
 "encoding/json"
 "fmt"
 "testing"

 pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssuranceJointExitTransferExploration(t *testing.T) {
 for _, overlap := range []bool{false, true} {
  t.Run(fmt.Sprintf("overlap_%v", overlap), func(t *testing.T) {
   nodes := map[uint64]*RawNode{}
   stores := map[uint64]*MemoryStorage{}
   ids := []uint64{1,2,3}
   emit := func(phase string, fields map[string]interface{}) {
    fields["phase"] = phase
    fields["overlap"] = overlap
    data, err := json.Marshal(fields)
    if err != nil { t.Fatal(err) }
    fmt.Println("CA_EVENT " + string(data))
   }
   must := func(err error) { if err != nil { t.Fatal(err) } }
   // An agreed initial snapshot is the explicit starting state. MemoryStorage
   // substitutes completed durable writes; this exploration includes no crash.
   for _, id := range ids {
    s := NewMemoryStorage()
    must(s.ApplySnapshot(pb.Snapshot{Metadata: pb.SnapshotMetadata{
     Index:1, Term:1, ConfState:pb.ConfState{Voters:[]uint64{1,2,3}},
    }}))
    must(s.SetHardState(pb.HardState{Term:1, Commit:1}))
    rn, err := NewRawNode(&Config{ID:id, Storage:s, Applied:1,
     ElectionTick:10, HeartbeatTick:1, MaxSizePerMsg:4096,
     MaxInflightMsgs:256, CheckQuorum:true, PreVote:true})
    must(err)
    nodes[id], stores[id] = rn, s
   }
   // RawNode owns no goroutine and has no Stop method. All calls below are
   // serialized; all Ready batches complete before another batch is accepted.
   var queue []pb.Message
   var transferStarted bool
   var timeoutDrops int
   var configIndex uint64
   var appliedConfigs int
   var readyCount, messageCount int
   observe := func(phase string) {
    states := []map[string]interface{}{}
    for _, id := range ids {
     rn := nodes[id]; r := rn.raft
     states = append(states,map[string]interface{}{
      "id":id,"term":r.Term,"role":r.state.String(),"lead":r.lead,
      "commit":r.raftLog.committed,"applied":r.raftLog.applied,
      "applying":r.raftLog.applying,"last":r.raftLog.lastIndex(),
      "auto_leave":r.trk.AutoLeave,"conf":r.trk.ConfState(),
      "transfer":r.leadTransferee,"pending_conf":r.pendingConfIndex,
      "election_elapsed":r.electionElapsed,"heartbeat_elapsed":r.heartbeatElapsed,
      "has_ready":rn.HasReady(),"unstable_count":len(r.raftLog.unstable.entries),
      "steps_on_advance":len(rn.stepsOnAdvance),"msgs":len(r.msgs),
      "msgs_after_append":len(r.msgsAfterAppend),
     })
    }
    emit(phase,map[string]interface{}{"states":states,"queue":len(queue),
     "timeout_drops":timeoutDrops,"config_index":configIndex,
     "applied_configs":appliedConfigs,"ready_count":readyCount,"message_count":messageCount})
   }
   pump := func() {
    for iteration:=0;iteration<10000;iteration++ {
     work:=false
     for _, id:=range ids {
      rn:=nodes[id]
      if !rn.HasReady() { continue }
      work=true;readyCount++
      rd:=rn.Ready()
      if !IsEmptySnap(rd.Snapshot) { must(stores[id].ApplySnapshot(rd.Snapshot)) }
      must(stores[id].Append(rd.Entries))
      if !IsEmptyHardState(rd.HardState) { must(stores[id].SetHardState(rd.HardState)) }
      // Persist before making any messages deliverable.
      queue=append(queue,rd.Messages...)
      for _, ent:=range rd.CommittedEntries {
       if ent.Type==pb.EntryConfChangeV2 {
        var cc pb.ConfChangeV2
        must(cc.Unmarshal(ent.Data))
        if len(cc.Changes)>0 && id==1 {
         configIndex=ent.Index
         if overlap {
          if transferStarted { t.Fatal("second initial joint application") }
          if rn.raft.state!=StateLeader || rn.raft.trk.Progress[2].Match!=rn.raft.raftLog.lastIndex() {
           t.Fatal("transfer prerequisite not reached: target must be caught up")
          }
          transferStarted=true
          rn.TransferLeader(2)
          emit("transfer_started",map[string]interface{}{"term":rn.raft.Term,
           "index":ent.Index,"target_match":rn.raft.trk.Progress[2].Match,
           "transfer":rn.raft.leadTransferee})
         }
        }
        cs:=rn.ApplyConfChange(cc)
        appliedConfigs++
        emit("configuration_applied",map[string]interface{}{"node":id,"index":ent.Index,
         "term":ent.Term,"leave_joint":cc.LeaveJoint(),"conf":cs})
       }
      }
      rn.Advance(rd)
     }
     if len(queue)>0 {
      work=true
      m:=queue[0];queue=queue[1:];messageCount++
      // A single network loss. Every subsequent emitted message is delivered.
      if overlap && m.Type==pb.MsgTimeoutNow && timeoutDrops==0 {
       timeoutDrops++
       emit("network_drop",map[string]interface{}{"type":m.Type.String(),"from":m.From,"to":m.To,"term":m.Term})
      } else {
       dst:=nodes[m.To]
       if dst==nil { t.Fatalf("unexpected destination %d",m.To) }
       err:=dst.Step(m)
       if err!=nil && err!=ErrStepPeerNotFound { t.Fatal(err) }
      }
     }
     if !work { return }
    }
    t.Fatal("pump did not drain within diagnostic bound")
   }
   must(nodes[1].Campaign());pump()
   if nodes[1].raft.state!=StateLeader || nodes[1].raft.raftLog.applied!=nodes[1].raft.raftLog.lastIndex() {
    t.Fatal("initial leader and applied-prefix prerequisites not reached")
   }
   observe("initial_election_drained")
   must(nodes[1].ProposeConfChange(pb.ConfChangeV2{
    Transition:pb.ConfChangeTransitionJointImplicit,
    Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}},
   }))
   pump();observe("joint_application_drained")
   if configIndex==0 || (overlap && (!transferStarted || timeoutDrops!=1)) {
    t.Fatal("selected scenario prerequisites not reached")
   }
   // All nodes are ticked. Reliable delivery is restored before the first tick.
   for tick:=1;tick<=40;tick++ {
    for _,id:=range ids { nodes[id].Tick() }
    pump()
    if tick%10==0 { observe(fmt.Sprintf("after_%d_ticks",tick)) }
   }
   observe("before_diagnostic_proposal")
   // This additional client operation is a diagnostic stimulus, not assumed
   // part of the implementation-owned automatic-exit obligation.
   must(nodes[1].Propose([]byte("diagnostic-after-observation")))
   pump();observe("after_diagnostic_proposal")
  })
 }
}
