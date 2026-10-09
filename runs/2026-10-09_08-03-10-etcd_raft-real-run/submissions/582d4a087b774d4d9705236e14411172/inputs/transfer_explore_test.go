package raft

import (
 "encoding/json"
 "fmt"
 "reflect"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

func assuranceEmit(v map[string]any) { b, err := json.Marshal(v); if err != nil { panic(err) }; fmt.Println("CA_EVENT " + string(b)) }

// Capture state structurally, without changing it. Storage is sampled separately;
// logger objects are excluded. Function addresses retain dispatch identity.
func assuranceValue(v reflect.Value) any {
 if !v.IsValid() { return nil }
 switch v.Kind() {
 case reflect.Pointer, reflect.Interface:
  if v.IsNil() { return nil }; return assuranceValue(v.Elem())
 case reflect.Struct:
  out := map[string]any{}
  for i:=0;i<v.NumField();i++ { name:=v.Type().Field(i).Name; if name=="logger" || name=="traceLogger" || name=="storage" { continue }; out[name]=assuranceValue(v.Field(i)) }; return out
 case reflect.Map:
  if v.IsNil() { return nil }; out:=map[string]any{}; it:=v.MapRange(); for it.Next() { out[fmt.Sprint(assuranceValue(it.Key()))]=assuranceValue(it.Value()) }; return out
 case reflect.Slice, reflect.Array:
  if v.Kind()==reflect.Slice && v.IsNil() { return nil }; out:=make([]any,v.Len()); for i:=range out { out[i]=assuranceValue(v.Index(i)) }; return out
 case reflect.Bool: return v.Bool()
 case reflect.String: return v.String()
 case reflect.Int,reflect.Int8,reflect.Int16,reflect.Int32,reflect.Int64: return v.Int()
 case reflect.Uint,reflect.Uint8,reflect.Uint16,reflect.Uint32,reflect.Uint64,reflect.Uintptr: return v.Uint()
 case reflect.Func: return v.Pointer()
 default: panic(fmt.Sprintf("uncaptured state kind %s",v.Kind()))
 }
}

func TestAssuranceTransferExplore(t *testing.T) {
 ns:=map[uint64]*RawNode{}; stores:=map[uint64]*MemoryStorage{}
 must:=func(err error) { t.Helper(); if err!=nil { t.Fatal(err) } }
 for id:=uint64(1);id<=3;id++ {
  s:=NewMemoryStorage(); stores[id]=s
  n,err:=NewRawNode(&Config{ID:id,ElectionTick:10,HeartbeatTick:1,Storage:s,MaxSizePerMsg:4096,MaxInflightMsgs:16,CheckQuorum:true}); must(err); ns[id]=n
  must(n.Bootstrap([]Peer{{ID:1},{ID:2},{ID:3}}))
 }
 var queue []pb.Message
 overlap:=false; injected:=false; dropTimeout:=false; dropped:=0
 var jointIndex uint64
 drain:=func(){}
 drain=func() {
  for round:=0;round<10000;round++ {
   progress:=false
   for id:=uint64(1);id<=3;id++ {
    n:=ns[id]; s:=stores[id]; if !n.HasReady() { continue }; progress=true
    rd:=n.Ready()
    if !IsEmptySnap(rd.Snapshot) { must(s.ApplySnapshot(rd.Snapshot)) }
    if !IsEmptyHardState(rd.HardState) { must(s.SetHardState(rd.HardState)) }
    must(s.Append(rd.Entries))
    // Persist first, enqueue outbound traffic, then apply and advance. The
    // driver is single-threaded; transport dispatch occurs outside this loop.
    for _,m:=range rd.Messages {
     if dropTimeout && m.Type==pb.MsgTimeoutNow { dropped++; assuranceEmit(map[string]any{"kind":"dropped_timeout","from":m.From,"to":m.To,"term":m.Term}); continue }
     queue=append(queue,m)
    }
    for _,e:=range rd.CommittedEntries {
     switch e.Type {
     case pb.EntryConfChange:
      var cc pb.ConfChange; must(cc.Unmarshal(e.Data)); n.ApplyConfChange(cc)
     case pb.EntryConfChangeV2:
      var cc pb.ConfChangeV2; must(cc.Unmarshal(e.Data))
      if id==1 && overlap && !injected && len(cc.Changes)>0 {
       jointIndex=e.Index; dropTimeout=true; n.TransferLeader(2); injected=true
       assuranceEmit(map[string]any{"kind":"overlap","index":e.Index,"commit":n.raft.raftLog.committed,"applied":n.raft.raftLog.applied,"transfer":n.raft.leadTransferee,"term":n.raft.Term})
       if n.raft.leadTransferee!=2 { t.Fatal("transfer not admitted") }
      }
      cs:=n.ApplyConfChange(cc)
      assuranceEmit(map[string]any{"kind":"configuration_applied","node":id,"index":e.Index,"auto_leave":cs.AutoLeave,"outgoing":cs.VotersOutgoing})
     }
    }
    n.Advance(rd)
   }
   if len(queue)>0 {
    m:=queue[0]; queue=queue[1:]; progress=true
    must(ns[m.To].Step(m))
   }
   if !progress { return }
  }
  t.Fatal("driver failed to drain")
 }
 drain(); must(ns[1].Campaign()); drain()
 if ns[1].raft.state!=StateLeader { t.Fatal("campaign failed") }
 overlap=true
 must(ns[1].ProposeConfChange(pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointImplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:3}}}))
 drain()
 if !injected || dropped==0 { t.Fatal("overlap or actual dropped transfer stimulus missing") }
 tick:=func(){for id:=uint64(1);id<=3;id++ { ns[id].Tick() };drain()}
 for i:=0;i<10;i++ { tick() }
 if ns[1].raft.leadTransferee!=0 || ns[1].raft.state!=StateLeader { t.Fatal("same-leader abort not reached") }
 dropTimeout=false
 snapshot:=func() string {
  out:=map[string]any{}
  for id:=uint64(1);id<=3;id++ {
   n:=ns[id]; if n.HasReady() { t.Fatal("undrained Ready") }
   s:=stores[id]; hs,cs,err:=s.InitialState(); must(err); first,err:=s.FirstIndex();must(err);last,err:=s.LastIndex();must(err); entries,err:=s.Entries(first,last+1,^uint64(0));must(err); snap,err:=s.Snapshot();must(err)
   out[fmt.Sprint(id)]=map[string]any{"rawnode":assuranceValue(reflect.ValueOf(n)),"storage":map[string]any{"hard":hs,"conf":cs,"entries":entries,"snapshot":snap,"first":first,"last":last}}
  }
  out["queue"]=queue; out["dropTimeout"]=dropTimeout;out["injected"]=injected;out["overlap"]=overlap
  data,err:=json.Marshal(out);must(err);return string(data)
 }
 // Allow one period after transport restoration before comparing boundaries.
 for i:=0;i<10;i++ { tick() }
 before:=snapshot()
 for i:=0;i<10;i++ { tick() }
 after:=snapshot()
 r:=ns[1].raft
 assuranceEmit(map[string]any{"kind":"post_abort","joint_index":jointIndex,"term":r.Term,"leader":r.lead,"state":r.state.String(),"applied":r.raftLog.applied,"commit":r.raftLog.committed,"last":r.raftLog.lastIndex(),"auto_leave":r.trk.AutoLeave,"transfer":r.leadTransferee,"empty_queue":len(queue)==0,"cycle_equal":before==after,"cycle_ticks":10,"before":before,"after":after})
 // A fresh proposal is a diagnostic stimulus, not required caller completion.
 must(ns[1].Propose([]byte("diagnostic application trigger")));drain()
 assuranceEmit(map[string]any{"kind":"rescue","auto_leave":ns[1].raft.trk.AutoLeave,"last":ns[1].raft.raftLog.lastIndex(),"applied":ns[1].raft.raftLog.applied})
}
