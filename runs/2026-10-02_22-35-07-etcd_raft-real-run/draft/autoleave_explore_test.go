package raft

import (
 "encoding/json"
 "fmt"
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
      assuranceExitEmit(map[string]any{"event":"joint_committed","scenario":c.scenario,"index":e.Index,"term":n.BasicStatus().Term,"transfer_target":n.raft.leadTransferee})
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

func TestAssuranceAutoLeaveExplore(t *testing.T) {
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
   for tick:=1;tick<=30;tick++ {
    c.nodes[1].Tick();c.nodes[2].Tick();c.pump()
    if tick==10 || tick==20 || tick==30 {c.observe(fmt.Sprintf("after_%d_ticks",tick))}
   }
   // Recovery probe comes strictly after all observations of the idle history.
   if err:=c.nodes[1].Propose([]byte("wake-after-observation"));err!=nil {t.Fatal(err)};c.pump()
   c.observe("after_new_proposal")
  })
 }
}
