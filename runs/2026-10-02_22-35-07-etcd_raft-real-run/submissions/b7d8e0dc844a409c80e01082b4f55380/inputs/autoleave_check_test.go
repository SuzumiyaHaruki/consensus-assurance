package raft

import (
 "encoding/json"
 "fmt"
 "reflect"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

// The driver serializes all RawNode operations and fully persists each Ready
// before delivering its messages. It applies only Ready.CommittedEntries.
type assuranceExitCluster struct {
 t *testing.T
 nodes map[uint64]*RawNode
 stores map[uint64]*MemoryStorage
 queue []pb.Message
 scenario string
 transfer bool
 hooked bool
 isolated bool
 jointIndex uint64
 exitEntries int
 heartbeats int
}

func assuranceExitEmit(v map[string]any) {
 b, err := json.Marshal(v); if err != nil { panic(err) }
 fmt.Println("CA_EVENT " + string(b))
}

func assuranceExitNew(t *testing.T, scenario string, transfer bool) *assuranceExitCluster {
 c := &assuranceExitCluster{t:t,nodes:map[uint64]*RawNode{},stores:map[uint64]*MemoryStorage{},scenario:scenario,transfer:transfer}
 for _, id := range []uint64{1,2,3} {
  s := NewMemoryStorage()
  // A common empty application snapshot supplies an explicit initial voter
  // configuration, as recommended by NewRawNode. No existing work is pending.
  if err := s.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1,2,3}}}}); err != nil { t.Fatal(err) }
  if err := s.SetHardState(pb.HardState{Term:1,Commit:1}); err != nil { t.Fatal(err) }
  n, err := NewRawNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:s,Applied:1,MaxSizePerMsg:4096,MaxInflightMsgs:256,CheckQuorum:true})
  if err != nil { t.Fatal(err) }
  c.nodes[id]=n; c.stores[id]=s
 }
 return c
}

func (c *assuranceExitCluster) pump() {
 for round:=0; round<1000; round++ {
  worked:=false
  for _, id := range []uint64{1,2,3} {
   if c.isolated && id==3 { continue }
   n:=c.nodes[id]
   if !n.HasReady() { continue }
   worked=true
   rd:=n.Ready()
   s:=c.stores[id]
   if !IsEmptySnap(rd.Snapshot) { if err:=s.ApplySnapshot(rd.Snapshot);err!=nil {c.t.Fatal(err)} }
   if err:=s.Append(rd.Entries);err!=nil {c.t.Fatal(err)}
   if !IsEmptyHardState(rd.HardState) {if err:=s.SetHardState(rd.HardState);err!=nil {c.t.Fatal(err)}}
   if id==1 { for _, e:=range rd.Entries {if e.Type==pb.EntryConfChangeV2 {var cc pb.ConfChangeV2;if err:=cc.Unmarshal(e.Data);err!=nil {c.t.Fatal(err)};if cc.LeaveJoint(){c.exitEntries++}}} }
   for _, e:=range rd.CommittedEntries {
    if e.Type==pb.EntryConfChangeV2 {
     var cc pb.ConfChangeV2
     if err:=cc.Unmarshal(e.Data);err!=nil {c.t.Fatal(err)}
     if id==1 && !cc.LeaveJoint() && !c.hooked {
      c.hooked=true; c.jointIndex=e.Index
      // Fault begins after actual commitment and before ordered application.
      // Node 3 is unavailable; nodes 1 and 2 remain a majority of both sets.
      c.isolated=true
      if c.transfer { n.TransferLeader(3) }
      assuranceExitEmit(map[string]any{"event":"joint_committed","scenario":c.scenario,"joint_index":e.Index,"term":n.BasicStatus().Term,"transfer_target":n.raft.leadTransferee})
     }
     n.ApplyConfChange(cc)
    } else if e.Type==pb.EntryConfChange {
     var cc pb.ConfChange;if err:=cc.Unmarshal(e.Data);err!=nil {c.t.Fatal(err)};n.ApplyConfChange(cc)
    }
   }
   c.queue=append(c.queue,rd.Messages...)
   n.Advance(rd)
  }
  if len(c.queue)>0 {
   worked=true
   msgs:=c.queue;c.queue=nil
   for _, m:=range msgs {
    if c.isolated && (m.To==3 || m.From==3) {continue}
    n:=c.nodes[m.To];if n==nil {continue} // learner 4 is unavailable
    if m.Type==pb.MsgHeartbeatResp && m.From==2 && m.To==1 {c.heartbeats++}
    if err:=n.Step(m);err!=nil {c.t.Fatal(err)}
   }
  }
  if !worked {return}
 }
 c.t.Fatal("driver did not drain within 1000 rounds")
}

func (c *assuranceExitCluster) observe(stage string) {
 n:=c.nodes[1];r:=n.raft
 assuranceExitEmit(map[string]any{"event":stage,"scenario":c.scenario,"joint_index":c.jointIndex,"term":r.Term,"role":r.state.String(),"transfer_target":r.leadTransferee,"commit":r.raftLog.committed,"applied":r.raftLog.applied,"last_index":r.raftLog.lastIndex(),"auto_leave":r.trk.AutoLeave,"outgoing":len(r.trk.Voters[1]),"exit_entries":c.exitEntries,"heartbeat_responses":c.heartbeats,"queue":len(c.queue),"has_ready":n.HasReady()})
}

// Snapshot every RawNode protocol field recursively, including private tracker
// fields and stored log contents. Reflection only reads primitive values; it
// neither obtains writable access nor calls Interface on private fields.
// Logger sinks, function pointers (determined by role), and storage call counters
// are omitted because they do not choose the next protocol transition.
func assuranceExitValue(v reflect.Value) any {
 if !v.IsValid() { return nil }
 switch v.Kind() {
 case reflect.Interface, reflect.Pointer:
  if v.IsNil() { return nil }; return assuranceExitValue(v.Elem())
 case reflect.Struct:
  out:=map[string]any{}
  for i:=0;i<v.NumField();i++ { name:=v.Type().Field(i).Name
   if name=="logger" || name=="traceLogger" || name=="tick" || name=="step" || name=="callStats" {continue}
   out[name]=assuranceExitValue(v.Field(i))
  };return out
 case reflect.Map:
  if v.IsNil(){return nil};out:=map[string]any{};it:=v.MapRange()
  for it.Next(){k:=it.Key();var key string
   if k.Kind()==reflect.String {key=k.String()} else {key=fmt.Sprint(k.Uint())}
   out[key]=assuranceExitValue(it.Value())
  };return out
 case reflect.Slice,reflect.Array:
  if v.Kind()==reflect.Slice && v.IsNil(){return nil}
  out:=make([]any,v.Len());for i:=range out {out[i]=assuranceExitValue(v.Index(i))};return out
 case reflect.Bool:return v.Bool()
 case reflect.String:return v.String()
 case reflect.Int,reflect.Int8,reflect.Int16,reflect.Int32,reflect.Int64:return v.Int()
 case reflect.Uint,reflect.Uint8,reflect.Uint16,reflect.Uint32,reflect.Uint64,reflect.Uintptr:return v.Uint()
 default:panic(fmt.Sprintf("unsupported observation kind %s",v.Kind()))
 }
}
func (c *assuranceExitCluster) protocolState() string {
 state:=map[string]any{}
 for _,id:=range []uint64{1,2,3}{state[fmt.Sprint(id)]=assuranceExitValue(reflect.ValueOf(c.nodes[id]))}
 b,err:=json.Marshal(state);if err!=nil{c.t.Fatal(err)};return string(b)
}
func (c *assuranceExitCluster) drained() bool {
 if len(c.queue)!=0{return false}
 for _,id:=range []uint64{1,2}{n:=c.nodes[id];r:=n.raft
  if n.HasReady() || len(n.stepsOnAdvance)!=0 || r.raftLog.applied!=r.raftLog.committed || r.raftLog.applying!=r.raftLog.applied || r.raftLog.lastIndex()!=r.raftLog.committed {return false}
 }
 return true
}
func (c *assuranceExitCluster) liveQuorum() bool {
 for _,set:=range c.nodes[1].raft.trk.Voters {
  if len(set)==0{continue};live:=0
  for id:=range set{if id==1 || id==2{live++}}
  if live<len(set)/2+1{return false}
 };return true
}

func TestAssuranceAutoLeaveContinuation(t *testing.T) {
 for _, transfer:=range []bool{false,true} {
  name:="control";if transfer {name="transfer_timeout"}
  t.Run(name,func(t *testing.T){
   c:=assuranceExitNew(t,name,transfer)
   if err:=c.nodes[1].Campaign();err!=nil {t.Fatal(err)};c.pump()
   if c.nodes[1].BasicStatus().RaftState!=StateLeader {t.Fatal("campaign did not elect node 1")}
   cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeAddLearnerNode,NodeID:4}}}
   if err:=c.nodes[1].ProposeConfChange(cc);err!=nil {t.Fatal(err)};c.pump()
   if !c.hooked {t.Fatal("joint entry was not committed and applied")}
   c.observe("after_apply")
   var cycleState string
   var cycleHeartbeats int
   var cycleDrained bool
   for tick:=1;tick<=30;tick++ {
    c.nodes[1].Tick();c.nodes[2].Tick();c.pump()
    if tick==10 {c.observe("after_transfer_timeout")}
    if tick==20 {
     cycleState=c.protocolState();cycleHeartbeats=c.heartbeats;cycleDrained=c.drained()
     assuranceExitEmit(map[string]any{"event":"cycle_start","scenario":name,"joint_index":c.jointIndex,"protocol_state":cycleState,"drained":cycleDrained,"live_quorum":c.liveQuorum(),"transfer_target":c.nodes[1].raft.leadTransferee})
    }
    if tick==30 {
     r:=c.nodes[1].raft;endState:=c.protocolState()
     repeated:=cycleState==endState
     closed:=repeated && cycleDrained && c.drained() && c.liveQuorum() && c.heartbeats-cycleHeartbeats==10 && r.state==StateLeader && r.leadTransferee==0
     // This is a recurring-state witness, not a thirty-tick deadline.
     stranded:=closed && r.trk.AutoLeave && len(r.trk.Voters[1])>0 && r.raftLog.applied>=r.pendingConfIndex && c.exitEntries==0
     assuranceExitEmit(map[string]any{"event":"cycle_result","scenario":name,"joint_index":c.jointIndex,"protocol_state":endState,"repeated":repeated,"closed_cycle":closed,"stranded_cycle":stranded,"drained":c.drained(),"live_quorum":c.liveQuorum(),"heartbeat_delta":c.heartbeats-cycleHeartbeats,"auto_leave":r.trk.AutoLeave,"outgoing":len(r.trk.Voters[1]),"exit_entries":c.exitEntries,"role":r.state.String(),"term":r.Term,"transfer_target":r.leadTransferee,"applied":r.raftLog.applied,"commit":r.raftLog.committed,"last_index":r.raftLog.lastIndex(),"pending_conf_index":r.pendingConfIndex})
    }
   }
   // Recovery probe comes strictly after all observations of the idle history.
   if err:=c.nodes[1].Propose([]byte("wake-after-observation"));err!=nil {t.Fatal(err)};c.pump()
   c.observe("after_new_proposal")
  })
 }
}
