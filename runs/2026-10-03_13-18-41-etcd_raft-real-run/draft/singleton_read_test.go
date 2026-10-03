package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssuranceSingletonReadEligibility(t *testing.T) {
 type replica struct {
  rn *RawNode
  store *MemoryStorage
  applied uint64
  value string
  writeIndex uint64
  incoming int
 }
 nodes := map[uint64]*replica{}
 emit := func(e map[string]interface{}) {
  b, err := json.Marshal(e); if err != nil { t.Fatal(err) }
  fmt.Println("CA_EVENT " + string(b))
 }
 for _, id := range []uint64{1,2} {
  st := NewMemoryStorage()
  // Common initial snapshot is the declared bootstrap state. Subsequent
  // election, commitment, configuration change and application all execute.
  if err := st.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{
   Index:1, Term:1, ConfState:pb.ConfState{Voters:[]uint64{1,2}},
  }}); err != nil {t.Fatal(err)}
  if err := st.SetHardState(pb.HardState{Term:1,Commit:1}); err != nil {t.Fatal(err)}
  rn, err := NewRawNode(&Config{ID:id, ElectionTick:10, HeartbeatTick:1,
   Storage:st, Applied:1, MaxSizePerMsg:4096, MaxInflightMsgs:256,
   ReadOnlyOption:ReadOnlySafe, StepDownOnRemoval:false})
  if err != nil {t.Fatal(err)}
  nodes[id]= &replica{rn:rn,store:st,applied:1,value:"old"}
 }
 isolated := false
 var queue []pb.Message
 admissionIncoming := map[string]int{}
 results := map[string]int{}
 // This pump drains bounded work independently of any read result. It persists
 // and applies every accepted Ready, then Advances; no early-Advance shortcut.
 pump := func() {
  for round:=0; round<200; round++ {
   work:=false
   for _, id := range []uint64{1,2} {
    n:=nodes[id]
    if !n.rn.HasReady() {continue}
    work=true
    rd:=n.rn.Ready()
    if !IsEmptySnap(rd.Snapshot) {t.Fatal("unexpected runtime snapshot")}
    if err:=n.store.Append(rd.Entries); err!=nil {t.Fatal(err)}
    if !IsEmptyHardState(rd.HardState) {if err:=n.store.SetHardState(rd.HardState);err!=nil {t.Fatal(err)}}
    for _, e:=range rd.CommittedEntries {
     if e.Index!=n.applied+1 {t.Fatalf("node %d nonconsecutive apply %d after %d",id,e.Index,n.applied)}
     switch e.Type {
     case pb.EntryConfChange:
      var cc pb.ConfChange
      if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)}
      cs:=n.rn.ApplyConfChange(cc)
      emit(map[string]interface{}{"event":"configuration_applied","node":id,"index":e.Index,"voters":cs.Voters,"learners":cs.Learners})
     case pb.EntryNormal:
      if len(e.Data)>0 {n.value=string(e.Data);n.writeIndex=e.Index}
     default:t.Fatalf("unexpected entry type %v",e.Type)
     }
     n.applied=e.Index
    }
    for _, rs:=range rd.ReadStates {
     request:=string(rs.RequestCtx)
     s:=n.rn.Status()
     voters:=s.Config.Voters.IDs()
     _,member:=voters[id]
     soleLocal:=len(s.Config.Voters[0])==1 && len(s.Config.Voters[1])==0 && member
     count, admitted:=admissionIncoming[request]
     results[request]++
     emit(map[string]interface{}{"event":"read_result","run":"demotion","node":id,"request":request,
      "read_index":rs.Index,"applied":n.applied,"value":n.value,"term":s.Term,"role":s.RaftState.String(),
      "local_is_sole_voter":soleLocal,"incoming_since_admission":n.incoming-count,"admission_known":admitted,
      "response_number":results[request],"result_emitted":true})
    }
    queue=append(queue,rd.Messages...)
    n.rn.Advance(rd)
   }
   if len(queue)>0 {
    work=true
    msgs:=queue;queue=nil
    for _, msg:=range msgs {
     if isolated && msg.From!=msg.To {
      emit(map[string]interface{}{"event":"message_dropped","from":msg.From,"to":msg.To,"message_type":msg.Type.String()})
      continue
     }
     n:=nodes[msg.To];if n==nil {t.Fatalf("unknown recipient %d",msg.To)}
     n.incoming++
     if err:=n.rn.Step(msg);err!=nil {t.Fatal(err)}
    }
   }
   if !work {return}
  }
  t.Fatal("work bound exceeded")
 }
 if err:=nodes[1].rn.Campaign();err!=nil {t.Fatal(err)}
 pump()
 if nodes[1].rn.Status().RaftState!=StateLeader {t.Fatal("initial leader not elected")}
 if err:=nodes[1].rn.ProposeConfChange(pb.ConfChange{Type:pb.ConfChangeAddLearnerNode,NodeID:1});err!=nil {t.Fatal(err)}
 pump()
 for _,id:=range []uint64{1,2} {
  s:=nodes[id].rn.Status()
  _,voter2:=s.Config.Voters[0][2];_,learner1:=s.Config.Learners[1]
  if len(s.Config.Voters[0])!=1 || len(s.Config.Voters[1])!=0 || !voter2 || !learner1 {t.Fatalf("demotion not installed on %d: %+v",id,s.Config)}
  emit(map[string]interface{}{"event":"demotion_complete","node":id,"role":s.RaftState.String(),"applied":nodes[id].applied,"term":s.Term})
 }
 isolated=true
 if err:=nodes[2].rn.Campaign();err!=nil {t.Fatal(err)}
 pump()
 if nodes[2].rn.Status().RaftState!=StateLeader {t.Fatal("remaining voter not elected")}
 if err:=nodes[2].rn.Propose([]byte("new"));err!=nil {t.Fatal(err)}
 pump()
 if nodes[2].value!="new" || nodes[2].writeIndex==0 {t.Fatal("new write did not apply")}
 emit(map[string]interface{}{"event":"write_completed","node":uint64(2),"index":nodes[2].writeIndex,"value":nodes[2].value})
 // Each invocation has a new context. Both the suspect learner and the valid
 // current singleton voter are observed; no returned state is suppressed.
 for _,id:=range []uint64{1,2} {
  n:=nodes[id];request:=fmt.Sprintf("fresh-read-%d",id)
  admissionIncoming[request]=n.incoming
  s:=n.rn.Status()
  emit(map[string]interface{}{"event":"read_admitted","run":"demotion","node":id,"request":request,
   "safe_mode":true,"isolated":isolated,"role":s.RaftState.String(),"term":s.Term,
   "write_index":nodes[2].writeIndex,"applied":n.applied})
  n.rn.ReadIndex([]byte(request))
  pump()
  emit(map[string]interface{}{"event":"read_window_closed","run":"demotion","node":id,"request":request,
   "results":results[request],"incoming_since_admission":n.incoming-admissionIncoming[request],"applied":n.applied})
 }
}
