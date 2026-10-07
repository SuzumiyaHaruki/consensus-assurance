package raft
import("encoding/json";"fmt";"testing"; pb "go.etcd.io/raft/v3/raftpb")
func assuranceEmit(v map[string]interface{}) {
 b, err := json.Marshal(v); if err != nil { panic(err) }; fmt.Println("CA_EVENT " + string(b))
}
func assuranceConfig(id uint64, s *MemoryStorage) *Config {
 return &Config{ID:id, ElectionTick:10, HeartbeatTick:1, Storage:s, Applied:1, MaxSizePerMsg:4096, MaxInflightMsgs:16}
}
func assurancePersist(t *testing.T, s *MemoryStorage, rd Ready) {
 t.Helper()
 if !IsEmptySnap(rd.Snapshot) { if err:=s.ApplySnapshot(rd.Snapshot); err!=nil {t.Fatal(err)} }
 if len(rd.Entries)>0 {if err:=s.Append(rd.Entries);err!=nil {t.Fatal(err)}}
 if !IsEmptyHardState(rd.HardState) {if err:=s.SetHardState(rd.HardState);err!=nil {t.Fatal(err)}}
}
func assuranceApplyRaw(t *testing.T, r *RawNode, entries []pb.Entry) {
 t.Helper()
 for _,e:=range entries {
  switch e.Type {
  case pb.EntryConfChange:
   var cc pb.ConfChange; if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)};r.ApplyConfChange(cc)
  case pb.EntryConfChangeV2:
   var cc pb.ConfChangeV2; if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)};r.ApplyConfChange(cc)
  }
 }
}

func TestAssuranceStatusAutoLeaveFidelity(t *testing.T){
 s:=NewMemoryStorage()
 if err:=s.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1}}}});err!=nil{t.Fatal(err)}
 if err:=s.SetHardState(pb.HardState{Term:1,Commit:1});err!=nil{t.Fatal(err)}
 r,err:=NewRawNode(assuranceConfig(1,s));if err!=nil{t.Fatal(err)}
 observed:=false
 drain:=func(){
  for round:=0;round<30;round++{
   if !r.HasReady(){return};rd:=r.Ready();assurancePersist(t,s,rd)
   for _,e:=range rd.CommittedEntries{
    if e.Type==pb.EntryConfChangeV2{
     var cc pb.ConfChangeV2;if err:=cc.Unmarshal(e.Data);err!=nil{t.Fatal(err)}
     cs:=r.ApplyConfChange(cc)
     if !cc.LeaveJoint(){
      // ApplyConfChange's return is the installed configuration, independently
      // observed before invoking the Status consumer. No protocol mutation intervenes.
      assuranceEmit(map[string]interface{}{"event":"installed","scenario":"implicit_status_copy","node":1,"entry_index":e.Index,"expected_auto_leave":cs.AutoLeave,"implicit":cc.Transition==pb.ConfChangeTransitionJointImplicit})
      status:=r.Status()
      assuranceEmit(map[string]interface{}{"event":"status_result","scenario":"implicit_status_copy","node":1,"entry_index":e.Index,"observed_auto_leave":status.Config.AutoLeave,"live_auto_leave":r.raft.trk.Config.AutoLeave,"outgoing_count":len(status.Config.Voters[1])})
      observed=true
     }
    }
   }
   // Remote messages target the learner and are dropped by the chosen transport;
   // the only voter is local and its durable self-responses are handled by Advance.
   r.Advance(rd)
  };t.Fatal("Ready work did not drain")
 }
 if err:=r.Campaign();err!=nil{t.Fatal(err)};drain()
 if r.BasicStatus().RaftState!=StateLeader{t.Fatal("no elected leader")}
 if err:=r.ProposeConfChange(pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeAddLearnerNode,NodeID:2}}});err!=nil{t.Fatal(err)};drain()
 if !observed{t.Fatal("joint entry not observed")}
 assuranceEmit(map[string]interface{}{"event":"cleanup","scenario":"implicit_status_copy","node":1,"has_ready":r.HasReady(),"applied":r.BasicStatus().Applied,"commit":r.BasicStatus().Commit,"live_auto_leave":r.raft.trk.Config.AutoLeave})
}
