package epaxos

import (
 "bufio"
 "bytes"
 "encoding/json"
 "fmt"
 "encoding/binary"
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

func TestAssuranceRangeConflictDependencies(t *testing.T) {
 scan:=func(base state.Key) state.Command {v:=make([]byte,8);binary.LittleEndian.PutUint64(v,10);return state.Command{Op:state.SCAN,K:base,V:v}}
 put:=func(key state.Key) state.Command {return state.Command{Op:state.PUT,K:key,V:state.Value("value")}}
 cases:=[]struct{name string;prior,next state.Command}{
  {"put_then_range",put(17),scan(10)},
  {"range_then_put",scan(10),put(17)},
  {"same_base_control",put(10),scan(10)},
  {"outside_control",put(21),scan(10)},
 }
 for _,tc:=range cases {t.Run(tc.name,func(t *testing.T){
  owner0,w0:=assuranceWireReplica(0)
  owner1,w1:=assuranceWireReplica(1)
  acceptor,wa:=assuranceWireReplica(2)
  owner0.crtInstance[0]=0
  owner0.startPhase1([]state.Command{tc.prior},0,0,0,nil)
  prior:=assuranceDecode(t,acceptor,w0[2],acceptor.preAcceptRPC).(*PreAccept)
  acceptor.handlePreAccept(prior)
  inst:=acceptor.InstanceSpace[0][0]
  if inst==nil || len(inst.Cmds)!=1 || inst.Status>=COMMITTED {t.Fatal("outstanding prior instance missing")}
  owner1.crtInstance[1]=0
  owner1.startPhase1([]state.Command{tc.next},1,0,1,nil)
  next:=assuranceDecode(t,acceptor,w1[2],acceptor.preAcceptRPC).(*PreAccept)
  for _,d:=range next.Deps {if d!=-1 {t.Fatal("unexpected supplied dependency")}}
  for row:=0;row<5;row++ {for idx,i:=range acceptor.InstanceSpace[row] {
   if i!=nil && (row!=0 || idx!=0) {t.Fatal("unexpected transitive history")}
  }}
  conflict:=state.ConflictBatch(inst.Cmds,next.Command)
  assuranceWireEvent(t,map[string]interface{}{"event":"conflict_input","scenario":tc.name,
   "replica":next.Replica,"instance":next.Instance,"prior_replica":prior.Replica,"prior_instance":prior.Instance,
   "conflicts":conflict,"prior_op":tc.prior.Op,"prior_key":tc.prior.K,"next_op":tc.next.Op,"next_key":tc.next.K})
  acceptor.handlePreAccept(next)
  reply:=assuranceDecode(t,owner1,wa[1],owner1.preAcceptReplyRPC).(*PreAcceptReply)
  if reply.Ballot!=next.Ballot || reply.Status>=ACCEPTED || len(reply.Deps)!=5 {t.Fatal("fresh PreAccept response missing")}
  assuranceWireEvent(t,map[string]interface{}{"event":"dependency_reply","scenario":tc.name,
   "replica":reply.Replica,"instance":reply.Instance,"covers_prior":reply.Deps[prior.Replica]>=prior.Instance,
   "prior_dependency":reply.Deps[prior.Replica],"seq":reply.Seq,"status":reply.Status})
 })}
}
