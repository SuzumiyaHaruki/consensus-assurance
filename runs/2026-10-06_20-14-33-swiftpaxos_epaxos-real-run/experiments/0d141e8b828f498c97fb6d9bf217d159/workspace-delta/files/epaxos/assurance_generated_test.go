package epaxos

import (
 "bufio"
 "bytes"
 "encoding/json"
 "fmt"
 "sync"
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
func TestAssurancePrepareReportValueBallot(t *testing.T) {
 origin,originOut:=assuranceReportReplica(1)
 acceptor,acceptorOut:=assuranceReportReplica(0)
 coordinator,coordinatorOut:=assuranceReportReplica(2)
 origin.handlePropose(&defs.GPropose{Propose:&defs.Propose{
  ClientId:10, CommandId:11, Command:state.Command{Op:state.PUT,K:9,V:state.Value{42}},
 },Reply:bufio.NewWriter(new(bytes.Buffer)),Mutex:new(sync.Mutex)})
 for _,receiver:=range []*Replica{acceptor,coordinator} {
  msg,ok:=assuranceReportDecode(t,receiver,originOut[receiver.Id]).(*PreAccept)
  if !ok {t.Fatal("expected origin PreAccept")}
  receiver.handlePreAccept(msg)
 }
 // PreAccept replies remain pending toward the origin. Both receivers have
 // uncommitted instance 1.0. Invoke the recovery entry for that known slot;
 // this check does not assert a timer deadline or a completed recovery.
 coordinator.startRecoveryForInstance(1,0)
 req,ok:=assuranceReportDecode(t,acceptor,coordinatorOut[acceptor.Id]).(*Prepare)
 if !ok {t.Fatal("expected recovery Prepare")}
 inst:=acceptor.InstanceSpace[req.Replica][req.Instance]
 if inst==nil || inst.vbal!=1 || inst.Status<PREACCEPTED || inst.Status>=COMMITTED {
  t.Fatal("proposal prefix did not establish the declared nonzero value-ballot state")
 }
 if req.LeaderId!=coordinator.Id || req.Ballot<=inst.bal {t.Fatal("expected a higher recovery ballot")}
 expectedVBallot:=inst.vbal
 acceptor.handlePrepare(req)
 // The report producer copies inst.vbal (unchanged by handlePrepare). No
 // goroutine can modify this state or the outgoing frame during observation.
 assuranceReportEvent(t,map[string]any{
  "event":"report_sent", "scenario":"nonzero_origin", "acceptor":acceptor.Id,
  "origin":req.Replica,"instance":req.Instance,"requester":req.LeaderId,
  "request_ballot":req.Ballot,"reported_vballot":expectedVBallot,
  "stored_vballot":inst.vbal,"stored_ballot":inst.bal,"status":inst.Status,
  "prefix_reached":true,"reply_bytes":acceptorOut[coordinator.Id].Len(),
 })
 reply,ok:=assuranceReportDecode(t,coordinator,acceptorOut[coordinator.Id]).(*PrepareReply)
 if !ok {t.Fatal("expected PrepareReply")}
 assuranceReportEvent(t,map[string]any{
  "event":"report_decoded","scenario":"nonzero_origin","acceptor":reply.AcceptorId,
  "origin":reply.Replica,"instance":reply.Instance,"requester":coordinator.Id,
  "request_ballot":reply.Ballot,"decoded_vballot":reply.VBallot,"status":reply.Status,
  "decode_completed":true,"remaining_bytes":acceptorOut[coordinator.Id].Len(),
 })
}
