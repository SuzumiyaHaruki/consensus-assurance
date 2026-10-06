package raft

import (
 "context"
 "encoding/hex"
 "encoding/json"
 "fmt"
 "testing"
 "time"
 pb "go.etcd.io/raft/v3/raftpb"
)
type earlyCluster struct {
 t *testing.T
 ctx context.Context
 nodes map[uint64]Node
 stores map[uint64]*MemoryStorage
 pending map[uint64][]pb.Entry
 seen map[uint64]map[uint64]pb.Entry
 hold map[uint64]bool
 partition bool
 dropped int
}
func earlyEmit(event string,m map[string]interface{}) {m["event"]=event;b,e:=json.Marshal(m);if e!=nil{panic(e)};fmt.Println("CA_EVENT "+string(b))}
func newEarly(t *testing.T)*earlyCluster {
 ctx,cancel:=context.WithTimeout(context.Background(),15*time.Second);t.Cleanup(cancel)
 c:=&earlyCluster{t:t,ctx:ctx,nodes:map[uint64]Node{},stores:map[uint64]*MemoryStorage{},pending:map[uint64][]pb.Entry{},seen:map[uint64]map[uint64]pb.Entry{},hold:map[uint64]bool{}}
 for id:=uint64(1);id<=3;id++ {
  s:=NewMemoryStorage();if e:=s.ApplySnapshot(pb.Snapshot{Metadata:pb.SnapshotMetadata{Index:1,Term:1,ConfState:pb.ConfState{Voters:[]uint64{1,2,3}}}});e!=nil{t.Fatal(e)}
  if e:=s.SetHardState(pb.HardState{Term:1,Commit:1});e!=nil{t.Fatal(e)}
  n:=RestartNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:s,Applied:1,MaxSizePerMsg:4096,MaxInflightMsgs:16})
  c.nodes[id]=n;c.stores[id]=s;c.seen[id]=map[uint64]pb.Entry{}
  t.Cleanup(n.Stop)
 }
 return c
}
func(c *earlyCluster)apply(id uint64,ents []pb.Entry){
 for _,e:=range ents {
  if e.Type==pb.EntryConfChange {var cc pb.ConfChange;if err:=cc.Unmarshal(e.Data);err!=nil{c.t.Fatal(err)};cs:=c.nodes[id].ApplyConfChange(cc);earlyEmit("actual_config_applied",map[string]interface{}{"node":id,"index":e.Index,"voters":cs.Voters})}
 }
}
func(c *earlyCluster)ready(id uint64,rd Ready){
 s:=c.stores[id]
 if !IsEmptySnap(rd.Snapshot){if e:=s.ApplySnapshot(rd.Snapshot);e!=nil{c.t.Fatal(e)}}
 if e:=s.Append(rd.Entries);e!=nil{c.t.Fatal(e)}
 if !IsEmptyHardState(rd.HardState){if e:=s.SetHardState(rd.HardState);e!=nil{c.t.Fatal(e)}}
 for _,m:=range rd.Messages {
  if c.partition && ((m.From==1)!=(m.To==1)){c.dropped++;continue}
  if e:=c.nodes[m.To].Step(c.ctx,m);e!=nil{c.t.Fatal(e)}
 }
 for _,e:=range rd.CommittedEntries {c.seen[id][e.Index]=e;earlyEmit("committed_delivery",map[string]interface{}{"node":id,"index":e.Index,"term":e.Term,"type":e.Type.String(),"data":hex.EncodeToString(e.Data),"application_held":c.hold[id]})}
 if c.hold[id] {c.pending[id]=append(c.pending[id],rd.CommittedEntries...)} else {c.apply(id,rd.CommittedEntries)}
 // Exercise the Node interface's documented early-Advance optimization.
 // All actual application remains ordered; later batches are queued, not applied.
 c.nodes[id].Advance()
 _=c.nodes[id].Status() // serial barrier after Advance processing, not elapsed time
}
func(c *earlyCluster)pumpUntil(label string,pred func()bool){
 for !pred(){
  select {
  case rd:=<-c.nodes[1].Ready():c.ready(1,rd)
  case rd:=<-c.nodes[2].Ready():c.ready(2,rd)
  case rd:=<-c.nodes[3].Ready():c.ready(3,rd)
  case <-c.ctx.Done():c.t.Fatalf("setup/completion not reached: %s: %v",label,c.ctx.Err())
  }
 }
}
func(c *earlyCluster)deliveredAll(index uint64)bool {for id:=uint64(1);id<=3;id++{if _,ok:=c.seen[id][index];!ok{return false}};return true}
func TestAssuranceEarlyAdvanceExplore(t *testing.T){
 c:=newEarly(t)
 if e:=c.nodes[1].Campaign(c.ctx);e!=nil{t.Fatal(e)}
 c.pumpUntil("initial leader commit",func()bool{return c.deliveredAll(2)})
 for id:=uint64(1);id<=3;id++{c.hold[id]=true}
 if e:=c.nodes[1].ProposeConfChange(c.ctx,pb.ConfChange{Type:pb.ConfChangeRemoveNode,NodeID:3});e!=nil{t.Fatal(e)}
 c.pumpUntil("first configuration committed and early advanced",func()bool{return c.deliveredAll(3)})
 for id:=uint64(1);id<=3;id++ {s:=c.nodes[id].Status();earlyEmit("first_advance_boundary",map[string]interface{}{"node":id,"commit":s.Commit,"reported_applied":s.Applied,"voters":s.Config.Voters.String(),"pending_application":len(c.pending[id])})}
 if e:=c.nodes[1].ProposeConfChange(c.ctx,pb.ConfChange{Type:pb.ConfChangeRemoveNode,NodeID:2});e!=nil{t.Fatal(e)}
 c.pumpUntil("second configuration delivered",func()bool{return c.deliveredAll(4)})
 // Finish leader 1's application in original log order before isolated proposal.
 c.apply(1,c.pending[1]);c.pending[1]=nil;c.hold[1]=false
 c.partition=true
 if e:=c.nodes[1].Propose(c.ctx,[]byte("left-command"));e!=nil{t.Fatal(e)}
 c.pumpUntil("left committed entry 5",func()bool{_,ok:=c.seen[1][5];return ok})
 if e:=c.nodes[3].Campaign(c.ctx);e!=nil{t.Fatal(e)}
 c.pumpUntil("right committed entry 5",func()bool{_,a:=c.seen[2][5];_,b:=c.seen[3][5];return a&&b})
 a,b:=c.seen[1][5],c.seen[3][5]
 earlyEmit("comparison",map[string]interface{}{"index":5,"left_term":a.Term,"right_term":b.Term,"left_type":a.Type.String(),"right_type":b.Type.String(),"left_data":hex.EncodeToString(a.Data),"right_data":hex.EncodeToString(b.Data),"left_commit":c.nodes[1].Status().Commit,"right_commit":c.nodes[3].Status().Commit,"dropped":c.dropped})
 // Complete all delayed application, in order, independently of the comparison.
 for _,id:=range []uint64{2,3}{c.apply(id,c.pending[id]);c.pending[id]=nil;c.hold[id]=false}
 earlyEmit("application_drained",map[string]interface{}{"pending_1":len(c.pending[1]),"pending_2":len(c.pending[2]),"pending_3":len(c.pending[3])})
}
