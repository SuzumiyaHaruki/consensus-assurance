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
 const n = 5
 base := &replica.Replica{Logger:dlog.New("",false), N:n, F:2, Id:id,
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

func TestAssuranceAcceptedSupportReporting(t *testing.T) {
 r:=make([]*Replica,5)
 w:=make([][]*bytes.Buffer,5)
 for i:=0;i<5;i++ {r[i],w[i]=assuranceWireReplica(int32(i))}
 // Replica 4 sends a conflicting command to its preferred peers 0 and 1.
 // Delivery to 0 stays pending while 1 receives it, a legal per-link prefix.
 r[4].crtInstance[4]=0
 r[4].startPhase1([]state.Command{{Op:state.PUT,K:17,V:state.Value("seed")}},4,0,4,nil)
 seed:=assuranceDecode(t,r[1],w[4][1],r[1].preAcceptRPC).(*PreAccept)
 r[1].handlePreAccept(seed)
 // Owner 0 forms a slow-path instance from differing real PreAccept replies.
 target:=[]state.Command{{Op:state.PUT,K:17,V:state.Value("target")}}
 r[0].crtInstance[0]=0
 r[0].startPhase1(target,0,0,0,nil)
 for _,a:=range []int32{1,2} {
  pa:=assuranceDecode(t,r[a],w[0][a],r[a].preAcceptRPC).(*PreAccept)
  r[a].handlePreAccept(pa)
  reply:=assuranceDecode(t,r[0],w[a][0],r[0].preAcceptReplyRPC).(*PreAcceptReply)
  r[0].handlePreAcceptReply(reply)
 }
 ownerInst:=r[0].InstanceSpace[0][0]
 if ownerInst.lb.status!=ACCEPTED || ownerInst.lb.deps[4]!=0 {t.Fatal("actual slow path not reached")}
 // Generate one higher Prepare request through the implementation recovery entry.
 // Its automatic trigger is outside this local reporting test.
 r[3].startRecoveryForInstance(0,0)
 for _,a:=range []int32{1,2} {
  accept:=assuranceDecode(t,r[a],w[0][a],r[a].acceptRPC).(*Accept)
  before:=r[a].InstanceSpace[0][0]
  if accept.Ballot<before.bal || before.Status>=COMMITTED {t.Fatal("Accept eligibility not reached")}
  r[a].handleAccept(accept)
  ack:=assuranceDecode(t,r[0],w[a][0],r[0].acceptReplyRPC).(*AcceptReply)
  if ack.Ballot!=accept.Ballot || ack.Replica!=accept.Replica || ack.Instance!=accept.Instance {
   t.Fatal("matching acknowledgment not reached")
  }
  inst:=r[a].InstanceSpace[0][0]
  if inst.Seq!=accept.Seq || !reflect.DeepEqual(inst.Deps,accept.Deps) || !reflect.DeepEqual(inst.Cmds,target) {
   t.Fatal("accepted attributes not installed")
  }
  assuranceWireEvent(t,map[string]interface{}{"event":"accept_acknowledged","acceptor":a,
   "replica":ack.Replica,"instance":ack.Instance,"ballot":ack.Ballot,"status_after_accept":inst.Status})
  prepare:=assuranceDecode(t,r[a],w[3][a],r[a].prepareRPC).(*Prepare)
  if prepare.Ballot<=inst.bal {t.Fatal("higher Prepare not reached")}
  r[a].handlePrepare(prepare)
  report:=assuranceDecode(t,r[3],w[a][3],r[3].prepareReplyRPC).(*PrepareReply)
  if report.Ballot!=prepare.Ballot || report.Seq!=inst.Seq || !reflect.DeepEqual(report.Deps,inst.Deps) || !reflect.DeepEqual(report.Command,target) {
   t.Fatal("Prepare report diagnostic failed")
  }
  assuranceWireEvent(t,map[string]interface{}{"event":"accepted_support_reported","acceptor":report.AcceptorId,
   "replica":report.Replica,"instance":report.Instance,"status":report.Status,
   "recognized_accepted_support":report.Status>=ACCEPTED,"prepare_ballot":report.Ballot})
 }
}
