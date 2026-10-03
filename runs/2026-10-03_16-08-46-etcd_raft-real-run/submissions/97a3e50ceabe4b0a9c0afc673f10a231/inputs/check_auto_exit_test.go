package raft

import (
 "encoding/json"
 "fmt"
 "reflect"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

// The driver owns transport and storage. All protocol transitions use RawNode
// methods; private fields are read only for exploration diagnostics.
type assuranceEnv struct {
 t *testing.T
 name string
 nodes map[uint64]*RawNode
 stores map[uint64]*MemoryStorage
 queue []pb.Message
 overlap bool
 injected bool
 dropped int
 jointIndex uint64
}
func (e *assuranceEnv) must(err error) { if err != nil { e.t.Fatal(err) } }
func (e *assuranceEnv) emit(kind string, fields map[string]interface{}) {
 fields["event"]=kind; fields["case"]=e.name
 b,err:=json.Marshal(fields);e.must(err);fmt.Println("CA_EVENT "+string(b))
}
func (e *assuranceEnv) enqueue(m pb.Message) {
 // Detach transport bytes before the source is advanced or handles more work.
 b,err:=m.Marshal();e.must(err); var copy pb.Message;e.must(copy.Unmarshal(b))
 e.queue=append(e.queue,copy)
}
func (e *assuranceEnv) pump() {
 for round:=0;round<10000;round++ {
  did:=false
  for id:=uint64(1);id<=3;id++ {
   n:=e.nodes[id];if !n.HasReady(){continue};did=true
   rd:=n.Ready()
   if !IsEmptySnap(rd.Snapshot){e.t.Fatal("unexpected snapshot in uncompacted history")}
   e.must(e.stores[id].Append(rd.Entries))
   if !IsEmptyHardState(rd.HardState){e.must(e.stores[id].SetHardState(rd.HardState))}
   for _,m:=range rd.Messages {e.enqueue(m)}
   for _,ent:=range rd.CommittedEntries {
    switch ent.Type {
    case pb.EntryConfChange:
     var cc pb.ConfChange;e.must(cc.Unmarshal(ent.Data));n.ApplyConfChange(cc)
    case pb.EntryConfChangeV2:
     var cc pb.ConfChangeV2;e.must(cc.Unmarshal(ent.Data));cs:=n.ApplyConfChange(cc)
     e.emit("configuration_applied",map[string]interface{}{"node":id,"index":ent.Index,"auto_leave":cs.AutoLeave,"outgoing":cs.VotersOutgoing})
     if id==1 && cs.AutoLeave && !e.injected {
      e.injected=true;e.jointIndex=ent.Index
      if e.overlap {n.TransferLeader(2)}
      s:=n.Status()
      e.emit("before_completion",map[string]interface{}{"index":ent.Index,"transfer":s.LeadTransferee,"commit":s.Commit,"applied":s.Applied})
     }
    }
   }
   // Applies every entry before acknowledging this Ready. Transfer is an
   // independent API operation between ApplyConfChange and Advance.
   n.Advance(rd)
  }
  if len(e.queue)>0 {
   did=true;q:=e.queue;e.queue=nil
   for _,m:=range q {
    if e.overlap && m.Type==pb.MsgTimeoutNow {
     e.dropped++;e.emit("network_drop",map[string]interface{}{"type":m.Type.String(),"from":m.From,"to":m.To});continue
    }
    if n:=e.nodes[m.To];n!=nil {err:=n.Step(m);if err==ErrStepPeerNotFound {e.emit("removed_peer_response",map[string]interface{}{"from":m.From,"to":m.To,"type":m.Type.String()})} else {e.must(err)}} else {e.t.Fatalf("unknown recipient %d",m.To)}
   }
  }
  if !did {return}
 }
 e.t.Fatal("driver did not drain within operation bound")
}
func (e *assuranceEnv) observation(phase string,tick int) {
 n:=e.nodes[1];s:=n.Status();last,err:=e.stores[1].LastIndex();e.must(err)
 ready:=false;for _,node:=range e.nodes {ready=ready||node.HasReady()}
 e.emit("observation",map[string]interface{}{"phase":phase,"ticks":tick,"term":s.Term,"state":s.RaftState.String(),"transfer":s.LeadTransferee,"commit":s.Commit,"applied":s.Applied,"last":last,"exported_auto_leave":s.Config.AutoLeave,"live_auto_leave":n.raft.trk.Config.AutoLeave,"outgoing":s.Config.Voters[1].Slice(),"joint_index":e.jointIndex,"queued":len(e.queue),"any_ready":ready,"dropped":e.dropped,"pending_conf_index":n.raft.pendingConfIndex,"election_elapsed":n.raft.electionElapsed,"heartbeat_elapsed":n.raft.heartbeatElapsed})
}
func TestAssuranceAutomaticExitCycle(t *testing.T) {
 for _,overlap:=range []bool{false,true} {
  name:="control";if overlap{name="transfer_overlap"}
  t.Run(name,func(t *testing.T){
   e:=&assuranceEnv{t:t,name:name,nodes:map[uint64]*RawNode{},stores:map[uint64]*MemoryStorage{},overlap:overlap}
   for id:=uint64(1);id<=3;id++ {
    st:=NewMemoryStorage();e.stores[id]=st
    n,err:=NewRawNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:st,MaxSizePerMsg:4096,MaxInflightMsgs:16,CheckQuorum:true,PreVote:true});e.must(err)
    e.nodes[id]=n;e.must(n.Bootstrap([]Peer{{ID:1},{ID:2},{ID:3}}))
   }
   e.pump();e.must(e.nodes[1].Campaign());e.pump()
   if e.nodes[1].Status().RaftState!=StateLeader {t.Fatal("campaign did not elect node 1")}
   // Actual committed membership change: remove node 3 through explicitly
   // selected implicit joint consensus, retaining the leader and transferee.
   e.must(e.nodes[1].ProposeConfChange(pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}}))
   e.pump();if !e.injected {t.Fatal("joint entry not applied on leader")};e.observation("drained",0)
   var cycleStart string
   startDrops:=0
   for tick:=1;tick<=30;tick++ {
    // The removed node is stopped only once the control leaves joint state.
    // In the overlap history all three nodes continue ticking and communicating.
    for id:=uint64(1);id<=3;id++ {if id==3&&len(e.nodes[1].Status().Config.Voters[1])==0 {continue};e.nodes[id].Tick()}
    e.pump();if tick%10==0 {e.observation("scheduled",tick)}
    if overlap && tick==20 {
     cycleStart=e.capture();startDrops=e.dropped
     n:=e.nodes[1];st:=n.Status()
     ready:=false;for _,nn:=range e.nodes {ready=ready||nn.HasReady()}
     e.emit("cycle_admitted",map[string]interface{}{"operation":"implicit-remove-3","leader":uint64(1),"joint_index":e.jointIndex,"live_auto_leave":n.raft.trk.AutoLeave,"outgoing_count":len(st.Config.Voters[1]),"transfer":st.LeadTransferee,"leader_state":st.RaftState.String(),"queues_empty":len(e.queue)==0&&!ready,"applied":st.Applied,"commit":st.Commit,"state":cycleStart})
    }
    if overlap && tick==30 {
     end:=e.capture();n:=e.nodes[1]
     e.emit("cycle_result",map[string]interface{}{"operation":"implicit-remove-3","leader":uint64(1),"joint_index":e.jointIndex,"repeat_cycle":cycleStart==end&&startDrops==e.dropped,"state_equal":cycleStart==end,"additional_drops":e.dropped-startDrops,"joint_pending":n.raft.trk.AutoLeave&&len(n.raft.trk.Voters[1])>0,"state_before":cycleStart,"state_after":end,"period_ticks":10})
    }
   }
   if overlap {
    // Diagnostic stimulus, not an assumed caller obligation or a violation oracle.
    e.must(e.nodes[1].Propose([]byte("diagnostic follow-up")));e.pump();e.observation("after_followup",30)
   }
  })
 }
}

// Capture all RawNode/raft/tracker/log and reachable MemoryStorage fields,
// including private queues, timers, applied/in-flight indexes, progress,
// configuration and persisted bytes. Do not call Status.Clone for this view.
// Exclusions are diagnostic log sinks and storage access counters, whose values
// are never read by protocol transitions. Slice capacity and allocation identity
// affect allocation only; nil versus non-nil and every live element are retained.
func assuranceValue(v reflect.Value) interface{} {
 if !v.IsValid(){return nil}
 switch v.Kind() {
 case reflect.Interface,reflect.Ptr:
  if v.IsNil(){return nil};return assuranceValue(v.Elem())
 case reflect.Struct:
  m:=map[string]interface{}{"$type":v.Type().String()}
  for i:=0;i<v.NumField();i++ {
   name:=v.Type().Field(i).Name
   if name=="logger"||name=="traceLogger" {continue}
   if v.Type()==reflect.TypeOf(MemoryStorage{})&&name=="callStats" {continue}
   m[name]=assuranceValue(v.Field(i))
  };return m
 case reflect.Map:
  if v.IsNil(){return nil};m:=map[string]interface{}{}
  it:=v.MapRange();for it.Next(){b,err:=json.Marshal(assuranceValue(it.Key()));if err!=nil{panic(err)};m[string(b)]=assuranceValue(it.Value())};return m
 case reflect.Slice,reflect.Array:
  if v.Kind()==reflect.Slice&&v.IsNil(){return nil}
  out:=make([]interface{},v.Len());for i:=range out{out[i]=assuranceValue(v.Index(i))};return out
 case reflect.String:return v.String()
 case reflect.Bool:return v.Bool()
 case reflect.Int,reflect.Int8,reflect.Int16,reflect.Int32,reflect.Int64:return v.Int()
 case reflect.Uint,reflect.Uint8,reflect.Uint16,reflect.Uint32,reflect.Uint64,reflect.Uintptr:return v.Uint()
 case reflect.Func:
  if v.IsNil(){return nil};return fmt.Sprintf("%s:%x",v.Type(),v.Pointer())
 default:panic(fmt.Sprintf("unhandled state kind %s (%s)",v.Kind(),v.Type()))
 }
}
func (e *assuranceEnv) capture() string {
 state:=map[string]interface{}{"nodes":assuranceValue(reflect.ValueOf(e.nodes)),"transport":assuranceValue(reflect.ValueOf(e.queue)),"schedule":"tick 1,2,3; drain Ready 1,2,3 then FIFO transport until quiescent; repeat", "overlap":e.overlap,"injected":e.injected,"joint_index":e.jointIndex}
 b,err:=json.Marshal(state);e.must(err);return string(b)
}
