package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssuranceDemotedSingletonReadExplore(t *testing.T) {
 for _,stepdown:=range []bool{false,true} {
  t.Run(fmt.Sprint(stepdown),func(t *testing.T){
   nodes:=map[uint64]*RawNode{};stores:=map[uint64]*MemoryStorage{}
   values:=map[uint64]string{1:"old",2:"old"}
   applied:=map[uint64]uint64{}
   readStates:=map[uint64][]ReadState{}
   for id:=uint64(1);id<=2;id++ {
    st:=NewMemoryStorage()
    rn,err:=NewRawNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:st,MaxSizePerMsg:0,MaxCommittedSizePerReady:4096,MaxInflightMsgs:256,ReadOnlyOption:ReadOnlySafe,StepDownOnRemoval:stepdown})
    if err!=nil {t.Fatal(err)}
    if err=rn.Bootstrap([]Peer{{ID:1},{ID:2}});err!=nil {t.Fatal(err)}
    nodes[id]=rn;stores[id]=st
   }
   var queue []pb.Message
   mode:="normal"
   prefix:=uint64(0)
   writeIndex:=uint64(0)
   drops:=0
   emit:=func(stage string,extra map[string]interface{}){
    r:=nodes[1].raft
    e:=map[string]interface{}{"event":stage,"stepdown":stepdown,"old_role":r.state.String(),"old_term":r.Term,"old_is_learner":r.isLearner,"old_voters":r.trk.Config.Voters[0].Slice(),"old_applied":applied[1],"new_applied":applied[2],"old_value":values[1],"new_value":values[2],"new_term":nodes[2].raft.Term,"new_role":nodes[2].raft.state.String(),"write_index":writeIndex,"prefix_index":prefix,"drops":drops,"read_count":len(readStates[1])}
    for k,v:=range extra {e[k]=v};b,err:=json.Marshal(e);if err!=nil {t.Fatal(err)};fmt.Println("CA_EVENT "+string(b))
   }
   pump:=func(){
    for rounds:=0;rounds<1000;rounds++ {
     active:=false
     for id:=uint64(1);id<=2;id++ {
      rn:=nodes[id];st:=stores[id]
      if !rn.HasReady(){continue};active=true;rd:=rn.Ready()
      if !IsEmptySnap(rd.Snapshot){t.Fatal("unexpected snapshot")}
      if err:=st.Append(rd.Entries);err!=nil {t.Fatal(err)}
      if !IsEmptyHardState(rd.HardState){if err:=st.SetHardState(rd.HardState);err!=nil {t.Fatal(err)}}
      queue=append(queue,rd.Messages...)
      for _,ent:=range rd.CommittedEntries {
       if ent.Index!=applied[id]+1 {t.Fatalf("nonconsecutive application on %d: %d after %d",id,ent.Index,applied[id])}
       switch ent.Type {
       case pb.EntryConfChange:
        var cc pb.ConfChange;if err:=cc.Unmarshal(ent.Data);err!=nil {t.Fatal(err)};rn.ApplyConfChange(cc)
       case pb.EntryConfChangeV2:
        var cc pb.ConfChangeV2;if err:=cc.Unmarshal(ent.Data);err!=nil {t.Fatal(err)};rn.ApplyConfChange(cc)
       case pb.EntryNormal:
        if len(ent.Data)>0 {values[id]=string(ent.Data);if id==2 && string(ent.Data)=="new" {writeIndex=ent.Index}}
       }
       applied[id]=ent.Index
      }
      for _,rs:=range rd.ReadStates {
       rs.RequestCtx=append([]byte(nil),rs.RequestCtx...)
       readStates[id]=append(readStates[id],rs)
      }
      rn.Advance(rd)
     }
     if len(queue)>0 {
      active=true;m:=queue[0];queue=queue[1:]
      drop:=mode=="isolate"
      if mode=="prefix" && m.From==2 && m.To==1 {
       // Drop actual generated data beyond the selected no-op prefix.
       for _,e:=range m.Entries {if e.Index>prefix {drop=true}}
       if m.Type==pb.MsgHeartbeat && m.Commit>prefix {drop=true}
      }
      if drop {drops++} else if err:=nodes[m.To].Step(m);err!=nil && err!=ErrStepPeerNotFound {t.Fatal(err)}
     }
     if !active{return}
    }
    t.Fatal("pump exceeded finite construction bound")
   }
   pump();if err:=nodes[1].Campaign();err!=nil {t.Fatal(err)};pump()
   if nodes[1].raft.state!=StateLeader {t.Fatal("initial leader missing")}
   cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeAddLearnerNode,NodeID:1}}}
   if err:=nodes[1].ProposeConfChange(cc);err!=nil {t.Fatal(err)};pump()
   for id:=uint64(1);id<=2;id++ {
    r:=nodes[id].raft
    if !r.trk.IsSingleton() || len(r.trk.Config.Voters[1])!=0 || r.trk.Progress[1]==nil || !r.trk.Progress[1].IsLearner {t.Fatal("demotion/finalization not reached")}
   }
   emit("demotion_applied",nil)
   mode="isolate"
   if err:=nodes[2].Campaign();err!=nil {t.Fatal(err)};pump()
   if nodes[2].raft.state!=StateLeader {t.Fatal("new singleton leader missing")}
   prefix=applied[2]
   if err:=nodes[2].Propose([]byte("new"));err!=nil {t.Fatal(err)};pump()
   if values[2]!="new" || writeIndex<=prefix {t.Fatal("write completion not reached")}
   emit("write_completed",nil)
   // The read invocation occurs after the write has completed application.
   nodes[1].ReadIndex([]byte("fresh-read-after-write"));pump()
   emit("read_barrier_received",nil)
   if len(readStates[1])>1 {t.Fatal("ambiguous local read result")}
   mode="prefix"
   for i:=0;i<5;i++ {nodes[2].Tick();pump()}
   if len(readStates[1])==1 {
    rs:=readStates[1][0]
    emit("read_consumption",map[string]interface{}{"read_index":rs.Index,"request_ctx":string(rs.RequestCtx),"strict_application_boundary":applied[1]>rs.Index,"observed_value":values[1]})
   } else {emit("no_read_barrier",nil)}
  })
 }
}
