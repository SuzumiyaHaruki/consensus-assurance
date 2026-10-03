package raft
import (
 "testing"
 "fmt"
 "encoding/json"
 pb "go.etcd.io/raft/v3/raftpb"
)
func TestAssuranceExploreRemovedRead(t *testing.T){
 for _,stepDown:=range []bool{false,true}{
  t.Run(fmt.Sprintf("stepdown_%v",stepDown),func(t *testing.T){
   must:=func(err error){if err!=nil{t.Fatal(err)}}
   emit:=func(event string,f map[string]interface{}){f["event"]=event;f["step_down"]=stepDown;b,err:=json.Marshal(f);must(err);fmt.Println("CA_EVENT "+string(b))}
   nodes:=map[uint64]*RawNode{};stores:=map[uint64]*MemoryStorage{};applied:=map[uint64]uint64{};values:=map[uint64]string{}
   isolated:=false
   for id:=uint64(1);id<=2;id++ {st:=NewMemoryStorage();stores[id]=st;n,err:=NewRawNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:st,MaxSizePerMsg:4096,MaxInflightMsgs:16,ReadOnlyOption:ReadOnlySafe,StepDownOnRemoval:stepDown});must(err);nodes[id]=n;must(n.Bootstrap([]Peer{{ID:1},{ID:2}}))}
   pump:=func(){
    for round:=0;round<1000;round++{
     did:=false;var msgs []pb.Message
     for id:=uint64(1);id<=2;id++{n:=nodes[id];if !n.HasReady(){continue};did=true;rd:=n.Ready();if !IsEmptySnap(rd.Snapshot){t.Fatal("unexpected snapshot")};must(stores[id].Append(rd.Entries));if !IsEmptyHardState(rd.HardState){must(stores[id].SetHardState(rd.HardState))}
      for _,m:=range rd.Messages{b,err:=m.Marshal();must(err);var cp pb.Message;must(cp.Unmarshal(b));msgs=append(msgs,cp)}
      for _,ent:=range rd.CommittedEntries{switch ent.Type{case pb.EntryConfChange:var cc pb.ConfChange;must(cc.Unmarshal(ent.Data));n.ApplyConfChange(cc);case pb.EntryNormal:if len(ent.Data)>0{values[id]=string(ent.Data)}};applied[id]=ent.Index}
      for _,rs:=range rd.ReadStates{emit("read_state",map[string]interface{}{"node":id,"index":rs.Index,"context":string(rs.RequestCtx),"app_applied":applied[id],"app_value":values[id],"role":n.BasicStatus().RaftState.String(),"term":n.BasicStatus().Term,"voters":n.Status().Config.Voters[0].Slice()})}
      n.Advance(rd)
     }
     for _,m:=range msgs{if isolated&&m.From!=m.To {emit("partition_drop",map[string]interface{}{"from":m.From,"to":m.To,"type":m.Type.String()});continue};err:=nodes[m.To].Step(m);if err!=ErrStepPeerNotFound{must(err)}}
     if !did{return}
    };t.Fatal("driver failed to drain")
   }
   pump();must(nodes[1].Campaign());pump();must(nodes[1].Propose([]byte("old")));pump()
   must(nodes[1].ProposeConfChange(pb.ConfChange{Type:pb.ConfChangeRemoveNode,NodeID:1}));pump()
   emit("removed",map[string]interface{}{"node1_role":nodes[1].BasicStatus().RaftState.String(),"node1_voters":nodes[1].Status().Config.Voters[0].Slice(),"node2_voters":nodes[2].Status().Config.Voters[0].Slice(),"applied1":applied[1],"applied2":applied[2]})
   isolated=true;must(nodes[2].Campaign());pump();must(nodes[2].Propose([]byte("new")));pump()
   emit("write_applied",map[string]interface{}{"node":2,"applied":applied[2],"value":values[2],"role":nodes[2].BasicStatus().RaftState.String(),"term":nodes[2].BasicStatus().Term})
   nodes[1].ReadIndex([]byte("read-after-new-write"));pump()
   emit("drained",map[string]interface{}{"ready1":nodes[1].HasReady(),"ready2":nodes[2].HasReady(),"applied1":applied[1],"value1":values[1]})
  })
 }
}
