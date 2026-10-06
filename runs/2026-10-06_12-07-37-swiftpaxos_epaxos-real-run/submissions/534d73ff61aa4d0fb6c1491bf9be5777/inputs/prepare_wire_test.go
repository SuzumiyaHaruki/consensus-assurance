package epaxos

import (
 "bufio"
 "bytes"
 "encoding/json"
 "fmt"
 "reflect"
 "testing"

 "github.com/imdea-software/swiftpaxos/dlog"
 "github.com/imdea-software/swiftpaxos/replica"
 "github.com/imdea-software/swiftpaxos/replica/defs"
 fastrpc "github.com/imdea-software/swiftpaxos/rpc"
 "github.com/imdea-software/swiftpaxos/state"
)

// Bounded allocation mirrors the relevant constructor state without starting
// sockets, clocks, or executor goroutines. All protocol mutations use handlers.
func assuranceWireReplica(id int32) (*Replica, []*bytes.Buffer) {
 const n = 3
 base := &replica.Replica{Logger:dlog.New("",false), N:n, F:1, Id:id,
  RPC:fastrpc.NewTableId(defs.RPC_TABLE), State:state.InitState(),
  Stats:&defs.Stats{M:make(map[string]int)}, Thrifty:true, Dreply:true,
  Alive:make([]bool,n), PreferredPeerOrder:make([]int32,n),
  PeerWriters:make([]*bufio.Writer,n)}
 r := &Replica{Replica:base, InstanceSpace:make([][]*Instance,n),
  crtInstance:make([]int32,n), CommittedUpTo:make([]int32,n), ExecedUpTo:make([]int32,n),
  conflicts:make([]map[state.Key]*InstPair,n), maxSeqPerKey:make(map[state.Key]int32),
  latestCPInstance:-1, maxRecvBallot:-1}
 wires:=make([]*bytes.Buffer,n)
 for i:=0;i<n;i++ {
  r.InstanceSpace[i]=make([]*Instance,8)
  r.crtInstance[i]=-1; r.CommittedUpTo[i]=-1; r.ExecedUpTo[i]=-1
  r.conflicts[i]=make(map[state.Key]*InstPair)
  r.Alive[i]=true
  r.PreferredPeerOrder[i]=(id+1+int32(i))%n
  wires[i]=new(bytes.Buffer);r.PeerWriters[i]=bufio.NewWriter(wires[i])
 }
 // Preserve production RPC registration order.
 r.prepareRPC=r.RPC.Register(new(Prepare),nil)
 r.prepareReplyRPC=r.RPC.Register(new(PrepareReply),nil)
 r.preAcceptRPC=r.RPC.Register(new(PreAccept),nil)
 r.preAcceptReplyRPC=r.RPC.Register(new(PreAcceptReply),nil)
 r.acceptRPC=r.RPC.Register(new(Accept),nil)
 r.acceptReplyRPC=r.RPC.Register(new(AcceptReply),nil)
 r.commitRPC=r.RPC.Register(new(Commit),nil)
 r.tryPreAcceptRPC=r.RPC.Register(new(TryPreAccept),nil)
 r.tryPreAcceptReplyRPC=r.RPC.Register(new(TryPreAcceptReply),nil)
 return r,wires
}

func assuranceDecode(t *testing.T, r *Replica, wire *bytes.Buffer, code byte) fastrpc.Serializable {
 t.Helper()
 got,err:=wire.ReadByte();if err!=nil {t.Fatal(err)}
 if got!=code {t.Fatalf("RPC code %d, expected %d",got,code)}
 p,ok:=r.RPC.Get(got);if !ok {t.Fatal("unregistered RPC")}
 msg:=p.Obj.New()
 if err:=msg.Unmarshal(wire);err!=nil {t.Fatal(err)}
 if wire.Len()!=0 {t.Fatalf("unconsumed bytes: %d",wire.Len())}
 return msg
}

func assuranceWireEvent(t *testing.T, fields map[string]interface{}) {
 t.Helper(); b,err:=json.Marshal(fields);if err!=nil {t.Fatal(err)}
 fmt.Println("CA_EVENT "+string(b))
}

func TestAssurancePrepareValueBallotTransport(t *testing.T) {
 // Both cases are selected before observing results. Zero is a diagnostic
 // boundary case of the same responsibility; nonzero tests lost provenance.
 for _,ownerID:=range []int32{0,1} {
  t.Run(fmt.Sprintf("owner_%d",ownerID),func(t *testing.T){
   acceptorID:=(ownerID+1)%3; coordinatorID:=(ownerID+2)%3
   owner,ow:=assuranceWireReplica(ownerID)
   acceptor,aw:=assuranceWireReplica(acceptorID)
   coordinator,cw:=assuranceWireReplica(coordinatorID)
   cmds:=[]state.Command{{Op:state.PUT,K:17,V:state.Value("payload")}}
   // This is the internal entry used by handlePropose for the first instance.
   owner.crtInstance[ownerID]=0
   owner.startPhase1(cmds,ownerID,0,ownerID,nil)
   pa:=assuranceDecode(t,acceptor,ow[acceptorID],acceptor.preAcceptRPC).(*PreAccept)
   acceptor.handlePreAccept(pa)
   inst:=acceptor.InstanceSpace[ownerID][0]
   if inst==nil || inst.vbal!=ownerID || inst.Status!=PREACCEPTED_EQ || !reflect.DeepEqual(inst.Cmds,cmds) {
    t.Fatal("preaccept prefix not established")
   }
   // An executor may request recovery of a missing instance. The coordinator's
   // production entry creates its own attempt and emits the Prepare request.
   coordinator.startRecoveryForInstance(ownerID,0)
   prepare:=assuranceDecode(t,acceptor,cw[acceptorID],acceptor.prepareRPC).(*Prepare)
   if prepare.Replica!=ownerID || prepare.Instance!=0 || prepare.Ballot<=inst.bal {
    t.Fatal("recovery request premise not established")
   }
   acceptor.handlePrepare(prepare)
   if inst.bal!=prepare.Ballot || inst.vbal!=ownerID {t.Fatal("prepare producer state not established")}
   // handlePrepare constructs the reply directly from these live fields. No
   // concurrent owner runs here, and SendMsg has synchronously flushed bytes.
   scenario:=fmt.Sprintf("owner_%d",ownerID)
   assuranceWireEvent(t,map[string]interface{}{"event":"prepare_produced","scenario":scenario,
    "acceptor":acceptorID,"replica":ownerID,"instance":int32(0),
    "expected_vballot":inst.vbal,"ballot":inst.bal,"status":inst.Status})
   reply:=assuranceDecode(t,coordinator,aw[coordinatorID],coordinator.prepareReplyRPC).(*PrepareReply)
   if reply.Ballot!=prepare.Ballot || reply.Status!=inst.Status || reply.Seq!=inst.Seq ||
    !reflect.DeepEqual(reply.Command,inst.Cmds) || !reflect.DeepEqual(reply.Deps,inst.Deps) {
    t.Fatal("transport payload diagnostic failed")
   }
   assuranceWireEvent(t,map[string]interface{}{"event":"prepare_decoded","scenario":scenario,
    "acceptor":reply.AcceptorId,"replica":reply.Replica,"instance":reply.Instance,
    "vballot":reply.VBallot,"ballot":reply.Ballot,"status":reply.Status})
  })
 }
}
