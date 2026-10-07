package raft
import (
 "encoding/json"
 "fmt"
 "reflect"
 "sort"
 "strings"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)
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

// Encode values, not pointer addresses or hashes. Include all protocol fields,
// storage contents and RawNode completion state. The explicitly excluded fields
// are output-only logging and MemoryStorage instrumentation/synchronization.
func assuranceStateValue(v reflect.Value) string {
 if !v.IsValid(){return "invalid"}
 switch v.Kind(){
 case reflect.Interface,reflect.Ptr:
  if v.IsNil(){return "nil"};return v.Type().String()+"("+assuranceStateValue(v.Elem())+")"
 case reflect.Struct:
  var p []string
  for i:=0;i<v.NumField();i++ {
   name:=v.Type().Field(i).Name
   if name=="logger" || name=="traceLogger" {continue}
   if v.Type()==reflect.TypeOf(MemoryStorage{}) && (name=="Mutex" || name=="callStats"){continue}
   p=append(p,name+":"+assuranceStateValue(v.Field(i)))
  };return v.Type().String()+"{"+strings.Join(p,",")+"}"
 case reflect.Slice,reflect.Array:
  var p []string;for i:=0;i<v.Len();i++ {p=append(p,assuranceStateValue(v.Index(i)))}
  return v.Type().String()+"["+strings.Join(p,",")+"]"
 case reflect.Map:
  var p []string;for _,k:=range v.MapKeys(){p=append(p,assuranceStateValue(k)+":"+assuranceStateValue(v.MapIndex(k)))};sort.Strings(p);return v.Type().String()+"{"+strings.Join(p,",")+"}"
 case reflect.Bool:return fmt.Sprint(v.Bool())
 case reflect.String:return fmt.Sprintf("%q",v.String())
 case reflect.Int,reflect.Int8,reflect.Int16,reflect.Int32,reflect.Int64:return fmt.Sprint(v.Int())
 case reflect.Uint,reflect.Uint8,reflect.Uint16,reflect.Uint32,reflect.Uint64,reflect.Uintptr:return fmt.Sprint(v.Uint())
 case reflect.Func:return fmt.Sprintf("func:%x",v.Pointer())
 default:panic("unsupported state kind "+v.Kind().String())
 }
}
func TestAssuranceAutomaticJointExitContinuation(t *testing.T){
 const scenario="implicit_exit_transfer_timeout"
 rs:=map[uint64]*RawNode{};ss:=map[uint64]*MemoryStorage{}
 for id:=uint64(1);id<=3;id++ {
  s:=NewMemoryStorage();if err:=s.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1,2,3}}}});err!=nil {t.Fatal(err)}
  if err:=s.SetHardState(pb.HardState{Term:1,Commit:1});err!=nil {t.Fatal(err)}
  cfg:=assuranceConfig(id,s);cfg.CheckQuorum=true
  r,err:=NewRawNode(cfg);if err!=nil {t.Fatal(err)};rs[id]=r;ss[id]=s
 }
 injected:=false;dropTransfer:=false;dropped:=0;var jointIndex uint64;leaveProposals:=0;strictSuffix:=false;var suffixTerm uint64
 stableRoles:=func(){
  if !strictSuffix{return}
  for id:=uint64(1);id<=3;id++ {st:=rs[id].BasicStatus();want:=StateFollower;if id==1{want=StateLeader};if st.Term!=suffixTerm || st.RaftState!=want {t.Fatal("stable suffix lost fixed term or role")}}
 }
 pump:=func(){
  for round:=0;round<200;round++ {
   work:=false;var queue []pb.Message
   for id:=uint64(1);id<=3;id++ {
    r:=rs[id];if !r.HasReady(){continue};work=true;rd:=r.Ready();assurancePersist(t,ss[id],rd)
    if id==1 {for _,e:=range rd.Entries {if e.Type==pb.EntryConfChangeV2 {var cc pb.ConfChangeV2;if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)};if cc.LeaveJoint(){leaveProposals++}}}}
    queue=append(queue,rd.Messages...)
    for _,e:=range rd.CommittedEntries {
     assuranceApplyRaw(t,r,[]pb.Entry{e})
     if id==1 && e.Type==pb.EntryConfChangeV2 && !injected {
      var cc pb.ConfChangeV2;if err:=cc.Unmarshal(e.Data);err!=nil {t.Fatal(err)}
      if !cc.LeaveJoint(){
       jointIndex=e.Index;injected=true;dropTransfer=true;r.TransferLeader(2)
       if r.BasicStatus().LeadTransferee!=2 {t.Fatal("transfer was not admitted")}
       assuranceEmit(map[string]interface{}{"event":"transfer_admitted","scenario":scenario,"leader":1,"joint_index":jointIndex,"term":r.BasicStatus().Term,"applied_before_advance":r.BasicStatus().Applied})
      }
     }
    }
    r.Advance(rd);stableRoles()
   }
   for _,msg:=range queue {
    if dropTransfer && msg.Type==pb.MsgTimeoutNow {dropped++;continue}
    if err:=rs[msg.To].Step(msg);err!=nil && err!=ErrStepPeerNotFound {t.Fatal(err)};stableRoles()
   }
   if !work && len(queue)==0{return}
  };t.Fatal("Ready/network pump did not drain")
 }
 if err:=rs[1].Campaign();err!=nil {t.Fatal(err)};pump()
 if rs[1].BasicStatus().RaftState!=StateLeader {t.Fatal("prefix did not elect leader")}
 cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}}
 if err:=rs[1].ProposeConfChange(cc);err!=nil {t.Fatal(err)};pump()
 if !injected || dropped==0 {t.Fatal("transfer interleaving not reached")}
 if rs[1].BasicStatus().Applied<jointIndex {t.Fatal("joint entry not acknowledged applied")}
 for tick:=0;tick<10;tick++ {for id:=uint64(1);id<=3;id++ {rs[id].Tick()};pump()}
 if rs[1].BasicStatus().LeadTransferee!=0 || rs[1].BasicStatus().RaftState!=StateLeader {t.Fatal("transfer did not time out on original leader")}
 dropTransfer=false;suffixTerm=rs[1].BasicStatus().Term;strictSuffix=true;stableRoles()
 assuranceEmit(map[string]interface{}{"event":"admission","scenario":scenario,"leader":1,"joint_index":jointIndex,"term":suffixTerm,"applied":rs[1].BasicStatus().Applied,"transfer_clear":true,"completed_application":true,"dropped_timeout_messages":dropped,"policy":"ticks_all_deliver_all_no_new_proposals"})
 capture:=func()string{var parts []string;for id:=uint64(1);id<=3;id++ {if rs[id].HasReady(){t.Fatal("state capture with owed Ready")};parts=append(parts,assuranceStateValue(reflect.ValueOf(rs[id])))};return strings.Join(parts,"\n")}
 // Stabilize representation and periodic activity before recording two complete periods.
 for tick:=0;tick<20;tick++ {for id:=uint64(1);id<=3;id++ {rs[id].Tick();stableRoles()};pump()}
 start:=capture();startLeaves:=leaveProposals
 assuranceEmit(map[string]interface{}{"event":"cycle_start","scenario":scenario,"leader":1,"joint_index":jointIndex,"protocol_state":start})
 for tick:=0;tick<10;tick++ {for id:=uint64(1);id<=3;id++ {rs[id].Tick();stableRoles()};pump()}
 end:=capture();st:=rs[1].Status();joint:=len(rs[1].raft.trk.Config.Voters[1])>0;activeAutoLeave:=rs[1].raft.trk.Config.AutoLeave
 assuranceEmit(map[string]interface{}{"event":"active_result","scenario":scenario,"leader":1,"joint_index":jointIndex,"protocol_state":end,"cycle_equal":start==end,"period_ticks":10,"auto_leave":activeAutoLeave,"status_auto_leave":st.Config.AutoLeave,"joint":joint,"transfer_clear":st.LeadTransferee==0,"leave_proposals_in_cycle":leaveProposals-startLeaves,"leave_proposals_total":leaveProposals,"closed_joint_cycle":start==end && activeAutoLeave && joint && leaveProposals==startLeaves,"applied":st.Applied,"commit":st.Commit})
 // Diagnostic rescue is after the principal observation and does not settle it.
 strictSuffix=false
 if err:=rs[1].Propose([]byte("diagnostic rescue"));err!=nil {t.Fatal(err)};pump()
 final:=rs[1].Status()
 assuranceEmit(map[string]interface{}{"event":"rescue","scenario":scenario,"leader":1,"joint_index":jointIndex,"auto_leave":rs[1].raft.trk.Config.AutoLeave,"status_auto_leave":final.Config.AutoLeave,"joint":len(final.Config.Voters[1])>0,"leave_proposals_total":leaveProposals,"applied":final.Applied,"commit":final.Commit})
}
