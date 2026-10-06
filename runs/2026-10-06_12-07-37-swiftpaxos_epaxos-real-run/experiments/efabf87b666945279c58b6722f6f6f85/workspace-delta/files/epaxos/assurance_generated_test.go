package epaxos

import (
 "bufio"
 "bytes"
 "encoding/json"
 "fmt"
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


type assurancePacket struct { from,to int; code byte; msg fastrpc.Serializable }
type assuranceNet struct { r []*Replica; w [][]*bytes.Buffer; pending []assurancePacket }
func (n *assuranceNet) collect(t *testing.T) {
 t.Helper()
 for from:=range n.r {for to:=range n.r {
  wire:=n.w[from][to]
  for wire.Len()>0 {
   code,err:=wire.ReadByte();if err!=nil {t.Fatal(err)}
   p,ok:=n.r[to].RPC.Get(code);if !ok {t.Fatal("unknown code")}
   msg:=p.Obj.New();if err:=msg.Unmarshal(wire);err!=nil {t.Fatal(err)}
   n.pending=append(n.pending,assurancePacket{from,to,code,msg})
  }
 }}
}
func (n *assuranceNet) deliver(t *testing.T,from,to int,code byte) {
 t.Helper();n.collect(t)
 for i,p:=range n.pending {
  if p.from!=from || p.to!=to || p.code!=code {continue}
  // A selected type is dispatched in its queued order at this receiver.
  for j:=0;j<i;j++ {q:=n.pending[j];if q.to==to && q.code==code {t.Fatal("type queue order violated")}}
  n.pending=append(n.pending[:i],n.pending[i+1:]...)
  t.Logf("dispatch %d -> %d %T %+v",from,to,p.msg,p.msg)
  switch m:=p.msg.(type) {
   case *PreAccept:n.r[to].handlePreAccept(m)
   case *PreAcceptReply:n.r[to].handlePreAcceptReply(m)
   case *Accept:n.r[to].handleAccept(m)
   case *AcceptReply:n.r[to].handleAcceptReply(m)
   case *Commit:n.r[to].handleCommit(m)
   case *Prepare:n.r[to].handlePrepare(m)
   case *PrepareReply:n.r[to].handlePrepareReply(m)
   default:t.Fatalf("unsupported packet %T",m)
  }
  n.collect(t);return
 }
 t.Fatalf("packet missing %d -> %d code %d",from,to,code)
}
func TestAssuranceExploreRecoveryAgreement(t *testing.T) {
 n:=&assuranceNet{r:make([]*Replica,5),w:make([][]*bytes.Buffer,5)}
 for i:=0;i<5;i++ {n.r[i],n.w[i]=assuranceWireReplica(int32(i))}
 r:=n.r
 x:=[]state.Command{{Op:state.PUT,K:17,V:state.Value("chosen")}}
 r[0].crtInstance[0]=0;r[0].startPhase1(x,0,0,0,nil)
 n.deliver(t,0,1,r[1].preAcceptRPC);n.deliver(t,0,2,r[2].preAcceptRPC)
 n.deliver(t,1,0,r[0].preAcceptReplyRPC);n.deliver(t,2,0,r[0].preAcceptReplyRPC)
 if r[0].InstanceSpace[0][0].Status!=COMMITTED {t.Fatal("first decision missing")}
 n.deliver(t,0,2,r[2].commitRPC)
 // Crash peer1 after the decision. Remaining nodes stop selecting that peer.
 for i:=0;i<5;i++ {r[i].Alive[1]=false}
 // The next instance reaches peer3 through thrifty failover. Commit0 is already
 // received/queued there but may remain undispatched while PreAccept1 is chosen.
 r[0].crtInstance[0]=1
 r[0].startPhase1([]state.Command{{Op:state.PUT,K:18,V:state.Value("later")}},0,1,0,nil)
 n.deliver(t,0,2,r[2].preAcceptRPC);n.deliver(t,0,3,r[3].preAcceptRPC)
 if r[3].crtInstance[0]!=1 || r[3].InstanceSpace[0][0]!=nil {t.Fatal("known hole missing")}
 assuranceWireEvent(t,map[string]interface{}{"event":"known_hole","replica":0,"instance":0,"coordinator":3,"known_max":r[3].crtInstance[0]})
 // Select the request the executor would enqueue for this known missing prefix.
 // This skips elapsed time only; no protocol state or result is installed.
 r[3].startRecoveryForInstance(0,0)
 n.deliver(t,3,2,r[2].prepareRPC);n.deliver(t,3,4,r[4].prepareRPC)
 n.deliver(t,2,3,r[3].prepareReplyRPC);n.deliver(t,4,3,r[3].prepareReplyRPC)
 assuranceWireEvent(t,map[string]interface{}{"event":"selected_recovery","status":r[3].InstanceSpace[0][0].Status,"cmds":r[3].InstanceSpace[0][0].Cmds})
 n.deliver(t,3,4,r[4].preAcceptRPC);n.deliver(t,3,0,r[0].preAcceptRPC)
 n.deliver(t,4,3,r[3].preAcceptReplyRPC);n.deliver(t,0,3,r[3].preAcceptReplyRPC)
 n.deliver(t,3,4,r[4].acceptRPC);n.deliver(t,3,0,r[0].acceptRPC)
 n.deliver(t,4,3,r[3].acceptReplyRPC);n.deliver(t,0,3,r[3].acceptReplyRPC)
 for _,i:=range []int{0,2,3} {
  inst:=r[i].InstanceSpace[0][0]
  assuranceWireEvent(t,map[string]interface{}{"event":"decision_snapshot","node":i,"replica":0,"instance":0,"status":inst.Status,"cmds":inst.Cmds,"ballot":inst.bal,"vballot":inst.vbal})
 }
}
