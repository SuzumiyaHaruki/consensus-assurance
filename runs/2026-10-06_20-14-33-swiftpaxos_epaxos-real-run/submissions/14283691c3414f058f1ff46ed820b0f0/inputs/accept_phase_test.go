package epaxos

import (
 "bufio"
 "bytes"
 "encoding/json"
 "fmt"
 "sync"
 "reflect"
 "testing"

 "github.com/imdea-software/swiftpaxos/dlog"
 "github.com/imdea-software/swiftpaxos/replica"
 "github.com/imdea-software/swiftpaxos/replica/defs"
 fastrpc "github.com/imdea-software/swiftpaxos/rpc"
 "github.com/imdea-software/swiftpaxos/state"
)

// Initialize the fields used by this bounded, single-threaded handler prefix.
// No protocol state is seeded beyond the constructor's empty-instance state.
func assuranceReportReplica(id int32) (*Replica, []*bytes.Buffer) {
 const n = 5
 out := make([]*bytes.Buffer, n)
 base := &replica.Replica{
  Logger: dlog.New("", false), N:n, F:2, Id:id,
  Thrifty:true, Dreply:true, State:state.InitState(),
  Alive:make([]bool,n), PreferredPeerOrder:make([]int32,n),
  PeerWriters:make([]*bufio.Writer,n), RPC:fastrpc.NewTableId(defs.RPC_TABLE),
  ProposeChan:make(chan *defs.GPropose, 8), Stats:&defs.Stats{M:make(map[string]int)},
 }
 r := &Replica{Replica:base, InstanceSpace:make([][]*Instance,n),
  crtInstance:make([]int32,n), CommittedUpTo:make([]int32,n), ExecedUpTo:make([]int32,n),
  conflicts:make([]map[state.Key]*InstPair,n), maxSeqPerKey:make(map[state.Key]int32),
  latestCPInstance:-1, maxRecvBallot:-1, clientMutex:new(sync.Mutex),
  instancesToRecover:make(chan *instanceId,8),
 }
 for i:=0;i<n;i++ {
  r.InstanceSpace[i]=make([]*Instance,16)
  r.crtInstance[i]=-1; r.CommittedUpTo[i]=-1; r.ExecedUpTo[i]=-1
  r.conflicts[i]=make(map[state.Key]*InstPair)
  r.Alive[i]=true; out[i]=new(bytes.Buffer); r.PeerWriters[i]=bufio.NewWriter(out[i])
 }
 // Origin 1 solicits peers 0 and 2, the two non-self members of its fast quorum.
 order:=[]int32{0,2,3,4}
 if id!=1 {order=nil; for i:=int32(0);i<n;i++ {if i!=id {order=append(order,i)}}}
 copy(r.PreferredPeerOrder,order)
 r.prepareRPC=r.RPC.Register(new(Prepare),make(chan fastrpc.Serializable,8))
 r.prepareReplyRPC=r.RPC.Register(new(PrepareReply),make(chan fastrpc.Serializable,8))
 r.preAcceptRPC=r.RPC.Register(new(PreAccept),make(chan fastrpc.Serializable,8))
 r.preAcceptReplyRPC=r.RPC.Register(new(PreAcceptReply),make(chan fastrpc.Serializable,8))
 r.acceptRPC=r.RPC.Register(new(Accept),make(chan fastrpc.Serializable,8))
 r.acceptReplyRPC=r.RPC.Register(new(AcceptReply),make(chan fastrpc.Serializable,8))
 r.commitRPC=r.RPC.Register(new(Commit),make(chan fastrpc.Serializable,8))
 r.tryPreAcceptRPC=r.RPC.Register(new(TryPreAccept),make(chan fastrpc.Serializable,8))
 r.tryPreAcceptReplyRPC=r.RPC.Register(new(TryPreAcceptReply),make(chan fastrpc.Serializable,8))
 return r,out
}

func assuranceReportDecode(t *testing.T, receiver *Replica, stream *bytes.Buffer) fastrpc.Serializable {
 t.Helper()
 // Bytes.Buffer implements ReadByte, matching the production buffered reader
 // without introducing read-ahead that could hide another pending frame.
 code,err:=stream.ReadByte(); if err!=nil {t.Fatal(err)}
 pair,ok:=receiver.RPC.Get(code); if !ok {t.Fatalf("unregistered RPC %d",code)}
 obj:=pair.Obj.New()
 if err:=obj.Unmarshal(stream); err!=nil {t.Fatal(err)}
 return obj
}
func assuranceReportEvent(t *testing.T, fields map[string]any) {
 t.Helper(); b,err:=json.Marshal(fields); if err!=nil {t.Fatal(err)}
 fmt.Println("CA_EVENT "+string(b))
}
func TestAssuranceAcceptedSupportPreparePhase(t *testing.T) {
 origin,originOut:=assuranceReportReplica(1)
 acceptor,acceptorOut:=assuranceReportReplica(0)
 coordinator,coordinatorOut:=assuranceReportReplica(2)
 // Keep the earlier conflicting proposal local to replica 2 and its selected
 // peers 3/4. Its messages remain pending; the target still reaches peers 0/2.
 coordinator.PreferredPeerOrder=[]int32{3,4,0,1,2}
 propose:=func(r *Replica,id int32,value byte) {
  r.handlePropose(&defs.GPropose{Propose:&defs.Propose{
   ClientId:10,CommandId:id,Command:state.Command{Op:state.PUT,K:9,V:state.Value{value}},
  },Reply:bufio.NewWriter(new(bytes.Buffer)),Mutex:new(sync.Mutex)})
 }
 propose(coordinator,20,20)
 propose(origin,11,42)
 for _,receiver:=range []*Replica{acceptor,coordinator} {
  msg,ok:=assuranceReportDecode(t,receiver,originOut[receiver.Id]).(*PreAccept)
  if !ok {t.Fatal("expected target PreAccept")}; receiver.handlePreAccept(msg)
 }
 for _,stream:=range []*bytes.Buffer{acceptorOut[origin.Id],coordinatorOut[origin.Id]} {
  msg,ok:=assuranceReportDecode(t,origin,stream).(*PreAcceptReply)
  if !ok {t.Fatal("expected target PreAcceptReply")}; origin.handlePreAcceptReply(msg)
 }
 target:=origin.InstanceSpace[1][0]
 if target==nil || target.Status!=ACCEPTED || target.lb.status!=ACCEPTED {
  t.Fatal("conflicting real preaccept replies did not enter the slow path")
 }
 var acceptedRequest *Accept
 var acceptedReply *AcceptReply
 for _,receiver:=range []*Replica{acceptor,coordinator} {
  req,ok:=assuranceReportDecode(t,receiver,originOut[receiver.Id]).(*Accept)
  if !ok {t.Fatal("expected target Accept")}
  before:=receiver.InstanceSpace[req.Replica][req.Instance]
  if before==nil || before.Status>=COMMITTED || req.Ballot<before.bal {
   t.Fatal("Accept would not reach eligible storage branch")
  }
  receiver.handleAccept(req)
  stream:=acceptorOut[origin.Id]; if receiver==coordinator {stream=coordinatorOut[origin.Id]}
  ack,ok:=assuranceReportDecode(t,origin,stream).(*AcceptReply)
  if !ok || ack.Ballot!=req.Ballot || ack.Replica!=req.Replica || ack.Instance!=req.Instance {
   t.Fatal("eligible Accept not acknowledged for the same instance and ballot")
  }
  local:=receiver.InstanceSpace[req.Replica][req.Instance]
  if local.bal!=req.Ballot || local.vbal!=req.Ballot || local.Seq!=req.Seq || !reflect.DeepEqual(local.Deps,req.Deps) {
   t.Fatal("eligible Accept did not store its ordering metadata")
  }
  if receiver==acceptor {acceptedRequest=req; acceptedReply=ack}
  origin.handleAcceptReply(ack)
 }
 if target.Status!=COMMITTED {t.Fatal("origin did not commit using the two actual accept replies")}
 // Commit bytes to peers 0/2 are retained, not dispatched. They can remain
 // in flight while replica 2 begins recovery for its uncommitted local slot.
 req:=acceptedRequest
 local:=acceptor.InstanceSpace[req.Replica][req.Instance]
 assuranceReportEvent(t,map[string]any{
  "event":"accept_support","scenario":"chosen_slow_path","acceptor":acceptor.Id,
  "origin":acceptedReply.Replica,"instance":acceptedReply.Instance,
  "accept_ballot":acceptedReply.Ballot,"origin_committed":target.Status==COMMITTED,
  "eligible_accept_completed":true,"local_phase":local.Status,"accepted_seq":req.Seq,
  "local_seq":local.Seq,"pending_commit_bytes":originOut[acceptor.Id].Len(),
 })
 coordinator.startRecoveryForInstance(req.Replica,req.Instance)
 prep,ok:=assuranceReportDecode(t,acceptor,coordinatorOut[acceptor.Id]).(*Prepare)
 if !ok || prep.Ballot<=local.bal {t.Fatal("expected higher recovery Prepare")}
 acceptor.handlePrepare(prep)
 report,ok:=assuranceReportDecode(t,coordinator,acceptorOut[coordinator.Id]).(*PrepareReply)
 if !ok {t.Fatal("expected recovery report")}
 assuranceReportEvent(t,map[string]any{
  "event":"accepted_phase_report","scenario":"chosen_slow_path","acceptor":report.AcceptorId,
  "origin":report.Replica,"instance":report.Instance,"request_ballot":report.Ballot,
  "reported_phase":report.Status,"accepted_or_later":report.Status>=ACCEPTED,
  "report_seq":report.Seq,"local_phase":local.Status,"decode_completed":true,
  "remaining_bytes":acceptorOut[coordinator.Id].Len(),
 })
}
