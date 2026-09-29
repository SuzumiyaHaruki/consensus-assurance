package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

// This exploration uses MemoryStorage as an ordered, noncrashing storage model.
// It does not measure disk durability or claim crash-recovery correctness.
func TestAssuranceAsyncCompletionAcrossTerm(t *testing.T) {
 nodes := map[uint64]*RawNode{}
 stores := map[uint64]*MemoryStorage{}
 for id := uint64(1); id <= 3; id++ {
  s := NewMemoryStorage()
  if err := s.ApplySnapshot(pb.Snapshot{Metadata: pb.SnapshotMetadata{Index: 1, Term: 1, ConfState: pb.ConfState{Voters: []uint64{1,2,3}}}}); err != nil { t.Fatal(err) }
  if err := s.SetHardState(pb.HardState{Term: 1, Commit: 1}); err != nil { t.Fatal(err) }
  rn, err := NewRawNode(&Config{ID:id, ElectionTick:10, HeartbeatTick:1, Storage:s, Applied:1, AsyncStorageWrites:true, MaxSizePerMsg:4096, MaxInflightMsgs:16})
  if err != nil { t.Fatal(err) }
  nodes[id], stores[id] = rn, s
 }
 emit := func(stage string, extra map[string]interface{}) {
  r := nodes[3].raft
  event := map[string]interface{}{"stage":stage, "node":3, "term":r.Term, "commit":r.raftLog.committed, "applied":r.raftLog.applied, "unstable_offset":r.raftLog.unstable.offset, "last_index":r.raftLog.lastIndex()}
  for k,v := range extra { event[k]=v }
  data,err := json.Marshal(event); if err != nil { t.Fatal(err) }; fmt.Println("CA_EVENT "+string(data))
 }
 var queue []pb.Message
 var held []pb.Message
 hold := false
 pump := func() {
  for steps := 0; ; steps++ {
   if steps >= 10000 { t.Fatal("exploration pump exceeded finite scheduling bound") }
   work := false
   for id:=uint64(1); id<=3; id++ {
    rn := nodes[id]
    if !rn.HasReady() { continue }
    work = true
    rd := rn.Ready()
    for _,m := range rd.Messages {
     switch m.Type {
     case pb.MsgStorageAppend:
      s := stores[id]
      if m.Snapshot != nil { if err := s.ApplySnapshot(*m.Snapshot); err != nil { t.Fatal(err) } }
      if err := s.Append(m.Entries); err != nil { t.Fatal(err) }
      st := pb.HardState{Term:m.Term,Vote:m.Vote,Commit:m.Commit}
      if !IsEmptyHardState(st) { if err:=s.SetHardState(st); err!=nil { t.Fatal(err) } }
      for _,resp := range m.Responses {
       if hold && id==3 && resp.Type==pb.MsgStorageAppendResp {
        held=append(held,resp)
        emit("completion_held",map[string]interface{}{"response_term":resp.Term,"response_index":resp.Index,"response_log_term":resp.LogTerm,"append_entries":len(m.Entries)})
       } else { queue=append(queue,resp) }
      }
     case pb.MsgStorageApply:
      // Apply all delivered entries to the model in order before acknowledging.
      // This history proposes only normal entries and performs no reconfiguration.
      for _,e := range m.Entries { if e.Type!=pb.EntryNormal { t.Fatal("unexpected configuration entry") } }
      queue=append(queue,m.Responses...)
     default:
      queue=append(queue,m)
     }
    }
   }
   if len(queue)>0 {
    m:=queue[0]; queue=queue[1:]
    if rn:=nodes[m.To]; rn!=nil { if err:=rn.Step(m);err!=nil {t.Fatal(err)} } else {t.Fatalf("unknown destination %d",m.To)}
    continue
   }
   if !work { return }
  }
 }
 if err:=nodes[1].Campaign();err!=nil {t.Fatal(err)}
 pump()
 if nodes[1].raft.state!=StateLeader {t.Fatal("first campaign did not elect node 1")}
 emit("initial_leader",map[string]interface{}{"leader":1})
 hold=true
 if err:=nodes[1].Propose([]byte("completion-probe"));err!=nil {t.Fatal(err)}
 pump()
 if len(held)==0 {t.Fatal("no old completion produced")}
 oldTerm:=nodes[3].raft.Term
 emit("old_term_drained_except_completions",map[string]interface{}{"held":len(held)})
 if err:=nodes[2].Campaign();err!=nil {t.Fatal(err)}
 pump()
 if nodes[2].raft.state!=StateLeader {t.Fatal("second campaign did not elect node 2")}
 emit("new_term_drained_except_completions",map[string]interface{}{"held":len(held),"old_term":oldTerm})
 // Responses are delivered in their original append-worker production order.
 // Their delay spans a real election; neither critical state nor messages are fabricated.
 pending:=held;held=nil;hold=false
 for i,m:=range pending {
  before:=nodes[3].raft.raftLog.unstable.offset
  if err:=nodes[3].Step(m);err!=nil {t.Fatal(err)}
  emit("completion_delivered",map[string]interface{}{"ordinal":i,"response_term":m.Term,"response_index":m.Index,"response_log_term":m.LogTerm,"offset_before":before})
 }
 pump()
 emit("final",map[string]interface{}{"remaining_held":len(held),"leader":2})
}
