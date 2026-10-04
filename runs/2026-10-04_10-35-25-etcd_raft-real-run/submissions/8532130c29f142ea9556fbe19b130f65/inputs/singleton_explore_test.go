package raft
import("encoding/json";"fmt";"testing";pb "go.etcd.io/raft/v3/raftpb")
type assuranceRestart struct {
 t *testing.T;n *RawNode;s *MemoryStorage
 staged pb.HardState;durable pb.HardState;diskEntries []pb.Entry;snap pb.Snapshot
 applied uint64;value string;cs *pb.ConfState
 read *ReadState;served bool;phase string
}
func(d *assuranceRestart) emit(e string,v map[string]interface{}){v["event"]=e;v["phase"]=d.phase;b,err:=json.Marshal(v);if err!=nil{d.t.Fatal(err)};fmt.Println("CA_EVENT "+string(b))}
func(d *assuranceRestart) must(e error){if e!=nil{d.t.Fatal(e)}}
func(d *assuranceRestart) create(){n,e:=NewRawNode(&Config{ID:1,ElectionTick:10,HeartbeatTick:1,Storage:d.s,MaxSizePerMsg:4096,MaxCommittedSizePerReady:1,MaxInflightMsgs:16});d.must(e);d.n=n}
func(d *assuranceRestart) one(){
 if !d.n.HasReady(){d.t.Fatal("no Ready")};rd:=d.n.Ready()
 d.must(d.s.Append(rd.Entries));if !IsEmptyHardState(rd.HardState){d.staged=rd.HardState;d.must(d.s.SetHardState(rd.HardState))}
 // A write without MustSync is visible to Storage but may be lost on crash.
 // A sync flushes all earlier staged HardState and every appended entry.
 if rd.MustSync {
  d.durable=d.staged;lo,e:=d.s.FirstIndex();d.must(e);hi,e:=d.s.LastIndex();d.must(e)
  ents,e:=d.s.Entries(lo,hi+1,^uint64(0));d.must(e);d.diskEntries=append([]pb.Entry(nil),ents...)
 }
 d.emit("ready",map[string]interface{}{"must_sync":rd.MustSync,"commit":d.n.BasicStatus().Commit,"durable_commit":d.durable.Commit,"entries":len(rd.Entries),"committed_entries":len(rd.CommittedEntries)})
 for _,e:=range rd.CommittedEntries {
  if e.Index!=d.applied+1{d.t.Fatalf("application gap %d after %d",e.Index,d.applied)}
  if e.Type==pb.EntryConfChange{var c pb.ConfChange;d.must(c.Unmarshal(e.Data));d.cs=d.n.ApplyConfChange(c)}
  if len(e.Data)>0 && e.Type==pb.EntryNormal{d.value=string(e.Data)}
  d.applied=e.Index
  d.emit("applied",map[string]interface{}{"index":e.Index,"value":d.value})
 }
 for _,rs:=range rd.ReadStates{x:=rs;d.read=&x;d.emit("read_state",map[string]interface{}{"context":string(rs.RequestCtx),"index":rs.Index})}
 // Honor even the strict wording 'applied index is greater than ReadState'.
 if d.read!=nil && !d.served && d.applied>d.read.Index {
  d.served=true;d.emit("read_completed",map[string]interface{}{"context":string(d.read.RequestCtx),"read_index":d.read.Index,"applied":d.applied,"value":d.value})
 }
 if len(rd.Messages)>0{d.t.Fatalf("unexpected singleton network messages: %+v",rd.Messages)}
 d.n.Advance(rd)
}
func(d *assuranceRestart) drain(){for i:=0;i<100;i++{if !d.n.HasReady(){return};d.one()};d.t.Fatal("drain bound")}
func TestAssuranceSingletonRestartExplore(t *testing.T){
 d:=&assuranceRestart{t:t,s:NewMemoryStorage(),phase:"initial"};d.create();d.must(d.n.Bootstrap([]Peer{{ID:1}}));d.drain()
 snap,e:=d.s.CreateSnapshot(d.applied,d.cs,nil);d.must(e);d.snap=snap
 d.must(d.n.Campaign());d.drain()
 // Both commands are durably appended together; their later commit-only
 // HardState update need not be synchronous under the Ready contract.
 d.must(d.n.Propose([]byte("A")));d.must(d.n.Propose([]byte("B")));d.drain()
 if d.value!="B"{t.Fatal("write completion prerequisite")}
 d.emit("write_completed",map[string]interface{}{"value":d.value,"index":d.applied,"durable_commit":d.durable.Commit,"durable_last":d.diskEntries[len(d.diskEntries)-1].Index})
 // Crash loses volatile application state and non-synced writes, retaining
 // the actual durable snapshot, log entries and last synced HardState.
 s:=NewMemoryStorage();d.must(s.ApplySnapshot(d.snap));d.must(s.Append(d.diskEntries));d.must(s.SetHardState(d.durable));d.s=s;d.staged=d.durable;d.value="";d.applied=d.snap.Metadata.Index;d.phase="restarted";d.create();d.drain()
 d.must(d.n.Campaign())
 for i:=0;i<10 && d.n.BasicStatus().RaftState!=StateLeader;i++{d.one()}
 if d.n.BasicStatus().RaftState!=StateLeader{t.Fatal("restart election prerequisite")}
 d.emit("read_invoked",map[string]interface{}{"context":"after-restart","commit":d.n.BasicStatus().Commit,"applied":d.applied,"value":d.value,"term":d.n.BasicStatus().Term})
 d.n.ReadIndex([]byte("after-restart"));d.drain()
 d.emit("end",map[string]interface{}{"served":d.served,"value":d.value,"applied":d.applied})
}
