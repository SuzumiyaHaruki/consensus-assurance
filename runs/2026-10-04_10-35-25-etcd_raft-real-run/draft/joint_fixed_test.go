package raft

import (
 "encoding/json"
 "fmt"
 "reflect"
 "sort"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

// This driver uses RawNode methods to mutate protocol state. Private fields are
// read only for diagnostics; MemoryStorage substitutes crash-free persistence.
type assuranceCluster struct {
 t *testing.T
 nodes map[uint64]*RawNode
 stores map[uint64]*MemoryStorage
 queue []pb.Message
 overlap bool
 armed bool
 injected bool
 dropping bool
 dropped int
 applied map[uint64]uint64
 confIndex uint64
 name string
}
func (c *assuranceCluster) event(kind string, fields map[string]interface{}) {
 fields["event"]=kind; fields["case"]=c.name; fields["operation"]="implicit-remove-3"
 b,err:=json.Marshal(fields); if err!=nil {c.t.Fatal(err)}
 fmt.Println("CA_EVENT "+string(b))
}
func (c *assuranceCluster) must(err error) {if err!=nil {c.t.Fatal(err)}}
func (c *assuranceCluster) pump() {
 for round:=0;round<10000;round++ {
  worked:=false
  for id:=uint64(1);id<=3;id++ {
   n:=c.nodes[id];if !n.HasReady(){continue};worked=true
   rd:=n.Ready();s:=c.stores[id]
   if !IsEmptySnap(rd.Snapshot){c.must(s.ApplySnapshot(rd.Snapshot));c.applied[id]=rd.Snapshot.Metadata.Index}
   c.must(s.Append(rd.Entries))
   if !IsEmptyHardState(rd.HardState){c.must(s.SetHardState(rd.HardState))}
   // Messages are queued only after this batch has been persisted.
   c.queue=append(c.queue,rd.Messages...)
   for _,e:=range rd.CommittedEntries {
    if e.Index!=c.applied[id]+1 {c.t.Fatalf("application gap node %d: %d after %d",id,e.Index,c.applied[id])}
    switch e.Type {
    case pb.EntryConfChange:
     var cc pb.ConfChange;c.must(cc.Unmarshal(e.Data));n.ApplyConfChange(cc)
    case pb.EntryConfChangeV2:
     var cc pb.ConfChangeV2;c.must(cc.Unmarshal(e.Data));cs:=n.ApplyConfChange(cc)
     if c.armed && id==1 && len(cc.Changes)>0 {
      c.confIndex=e.Index
      c.event("joint_applied",map[string]interface{}{"node":id,"index":e.Index,"term":n.BasicStatus().Term,"auto_leave":cs.AutoLeave,"outgoing":cs.VotersOutgoing,"commit":n.BasicStatus().Commit})
      if c.overlap && !c.injected {
       n.TransferLeader(2);c.injected=true
       c.event("transfer_started",map[string]interface{}{"transferee":n.BasicStatus().LeadTransferee,"index":e.Index})
      }
     }
    }
    c.applied[id]=e.Index
   }
   n.Advance(rd)
  }
  if len(c.queue)>0 {
   worked=true;m:=c.queue[0];c.queue=c.queue[1:]
   if c.dropping && m.Type==pb.MsgTimeoutNow {
    c.dropped++;c.event("network_drop",map[string]interface{}{"type":m.Type.String(),"from":m.From,"to":m.To,"term":m.Term})
   } else {
    err:=c.nodes[m.To].Step(m)
    if err!=nil && err!=ErrStepPeerNotFound {c.t.Fatal(err)}
   }
  }
  if !worked {return}
 }
 c.t.Fatal("pump exceeded independent work bound")
}
func (c *assuranceCluster) tick() {
 for id:=uint64(1);id<=3;id++ {c.nodes[id].Tick()}
 c.pump()
}
func (c *assuranceCluster) observe(phase string) {
 n:=c.nodes[1];s:=n.Status();r:=n.raft
 li,err:=c.stores[1].LastIndex();c.must(err)
 c.event("observation",map[string]interface{}{
  "phase":phase,"term":s.Term,"role":s.RaftState.String(),"leader":s.Lead,"transferee":s.LeadTransferee,
  "auto_leave":r.trk.Config.AutoLeave,"status_auto_leave":s.Config.AutoLeave,"outgoing_count":len(s.Config.Voters[1]),"commit":s.Commit,"applied":s.Applied,
  "last_index":r.raftLog.lastIndex(),"stored_last":li,"conf_index":c.confIndex,"pending_conf_index":r.pendingConfIndex,
  "queue":len(c.queue),"has_ready":n.HasReady(),"steps_on_advance":len(n.stepsOnAdvance),"messages":len(r.msgs),"after_append":len(r.msgsAfterAppend),
  "unstable_entries":len(r.raftLog.unstable.entries),"snapshot_pending":r.raftLog.hasNextOrInProgressSnapshot(),"applying":r.raftLog.applying,
  "application_bytes":r.raftLog.applyingEntsSize,"election_elapsed":r.electionElapsed,"heartbeat_elapsed":r.heartbeatElapsed,"dropped":c.dropped})
}
func TestAssuranceJointExitFixed(t *testing.T) {
 for _,overlap:=range []bool{false,true} {
  name:="control";if overlap{name="transfer_overlap"}
  t.Run(name,func(t *testing.T){
   c:=&assuranceCluster{t:t,nodes:map[uint64]*RawNode{},stores:map[uint64]*MemoryStorage{},applied:map[uint64]uint64{},overlap:overlap,dropping:overlap,name:name}
   for id:=uint64(1);id<=3;id++ {
    s:=NewMemoryStorage();n,err:=NewRawNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:s,MaxSizePerMsg:4096,MaxInflightMsgs:16,CheckQuorum:true});c.must(err)
    c.nodes[id]=n;c.stores[id]=s;c.must(n.Bootstrap([]Peer{{ID:1},{ID:2},{ID:3}}))
   }
   c.pump();c.must(c.nodes[1].Campaign());c.pump()
   if c.nodes[1].BasicStatus().RaftState!=StateLeader {t.Fatal("election prerequisite failed")}
   c.observe("elected")
   c.armed=true
   c.must(c.nodes[1].ProposeConfChange(pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}}))
   c.pump();c.observe("after_application")
   for i:=0;i<10;i++ {c.tick()}
   c.dropping=false;c.observe("after_timeout")
   // Warm up a full reliable period, then compare two whole service periods.
   for i:=0;i<10;i++ {c.tick()}
   first:=c.snapshot()
   for i:=0;i<10;i++ {c.tick()}
   second:=c.snapshot()
   for i:=0;i<10;i++ {c.tick()}
   third:=c.snapshot()
   c.event("state_cycle",map[string]interface{}{"first":first,"second":second,"third":third,"period_ticks":10})
   c.observe("after_reliable_suffix")
   live:=c.nodes[1].raft
   c.event("cycle_result",map[string]interface{}{
    "recurrent":first==second && second==third,
    "joint_active":len(live.trk.Config.Voters[1])>0,
    "live_auto_leave":live.trk.Config.AutoLeave,
    "outgoing_count":len(live.trk.Config.Voters[1]),
    "conf_index":c.confIndex,"term":live.Term,"transferee":live.leadTransferee,
    "leader":live.lead,"role":live.state.String(),"queue":len(c.queue),
   })
   c.must(c.nodes[1].Propose([]byte("later independent client work")));c.pump()
   c.observe("after_rescue")
  })
 }
}

// Capture every RawNode field recursively, including unexported protocol,
// progress, inflight, log, timer and pending-response fields. Copy values now;
// retaining pointers would compare future state to itself. No protocol field is
// rewritten. Omitted fields are logging sinks, a single-threaded storage mutex
// and MemoryStorage read-call counters, none of which determine transitions.
func assuranceValue(v reflect.Value) interface{} {
 if !v.IsValid(){return nil}
 switch v.Kind(){
 case reflect.Interface,reflect.Pointer:
  if v.IsNil(){return nil};return assuranceValue(v.Elem())
 case reflect.Struct:
  out:=map[string]interface{}{}
  for i:=0;i<v.NumField();i++ {
   name:=v.Type().Field(i).Name
   if name=="logger" || name=="traceLogger" || name=="Mutex" || name=="callStats" {continue}
   out[name]=assuranceValue(v.Field(i))
  };return out
 case reflect.Map:
  if v.IsNil(){return nil}
  keys:=v.MapKeys();sort.Slice(keys,func(i,j int)bool{return fmt.Sprint(assuranceValue(keys[i]))<fmt.Sprint(assuranceValue(keys[j]))})
  out:=make([]interface{},0,len(keys))
  for _,k:=range keys {out=append(out,[]interface{}{assuranceValue(k),assuranceValue(v.MapIndex(k))})};return out
 case reflect.Slice,reflect.Array:
  if v.Kind()==reflect.Slice && v.IsNil(){return nil}
  out:=make([]interface{},v.Len());for i:=range out {out[i]=assuranceValue(v.Index(i))};return out
 case reflect.String:return v.String()
 case reflect.Bool:return v.Bool()
 case reflect.Int,reflect.Int8,reflect.Int16,reflect.Int32,reflect.Int64:return v.Int()
 case reflect.Uint,reflect.Uint8,reflect.Uint16,reflect.Uint32,reflect.Uint64,reflect.Uintptr:return v.Uint()
 case reflect.Func:return fmt.Sprintf("function:%x",v.Pointer())
 default:panic("unsupported state kind "+v.Kind().String())
 }
}
func(c *assuranceCluster) snapshot() string {
 state:=map[string]interface{}{"nodes":assuranceValue(reflect.ValueOf(c.nodes)),"queue":assuranceValue(reflect.ValueOf(c.queue)),"caller_applied":assuranceValue(reflect.ValueOf(c.applied)),"dropping":c.dropping,"injected":c.injected,"armed":c.armed,"conf_index":c.confIndex}
 b,err:=json.Marshal(state);c.must(err);return string(b)
}
