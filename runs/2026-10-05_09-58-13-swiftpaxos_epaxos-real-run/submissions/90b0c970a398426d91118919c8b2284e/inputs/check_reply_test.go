package epaxos

import (
 "bufio"
 "bytes"
 "encoding/json"
 "fmt"
 "sync"
 "testing"

 "github.com/imdea-software/swiftpaxos/dlog"
 base "github.com/imdea-software/swiftpaxos/replica"
 "github.com/imdea-software/swiftpaxos/replica/defs"
 "github.com/imdea-software/swiftpaxos/state"
)

// Isolate synchronous handlers. Reproduce constructor state for a three-node,
// volatile, thrifty configuration, with bounded empty instance rows. No network,
// timer, execution goroutine or file is opened; captured streams replace TCP.
func assuranceNode(id int32) (*Replica, []*bytes.Buffer) {
 const n = 3
 r := &Replica{Replica: &base.Replica{
  Logger:dlog.New("",false), N:n,F:1,Id:id, Thrifty:true,Dreply:true,
  PeerWriters:make([]*bufio.Writer,n),Alive:make([]bool,n),
  PreferredPeerOrder:make([]int32,n),ProposeChan:make(chan *defs.GPropose,8),
  Stats:&defs.Stats{M:make(map[string]int)},State:state.InitState(),
 },InstanceSpace:make([][]*Instance,n),crtInstance:make([]int32,n),
 CommittedUpTo:make([]int32,n),ExecedUpTo:make([]int32,n),
 conflicts:make([]map[state.Key]*InstPair,n),maxSeqPerKey:make(map[state.Key]int32),
 clientMutex:new(sync.Mutex),maxRecvBallot:-1,latestCPInstance:-1,
 prepareRPC:1,prepareReplyRPC:2,preAcceptRPC:3,preAcceptReplyRPC:4,
 acceptRPC:5,acceptReplyRPC:6,commitRPC:7,
 }
 out:=make([]*bytes.Buffer,n)
 for i:=0;i<n;i++ {
  r.InstanceSpace[i]=make([]*Instance,8)
  r.crtInstance[i]=-1;r.CommittedUpTo[i]=-1;r.ExecedUpTo[i]=-1
  r.conflicts[i]=make(map[state.Key]*InstPair)
  r.PreferredPeerOrder[i]=(id+1+int32(i))%n
  r.Alive[i]=int32(i)!=id
  out[i]=new(bytes.Buffer);r.PeerWriters[i]=bufio.NewWriter(out[i])
 }
 return r,out
}
func assuranceEvent(v any) {b,_:=json.Marshal(v);fmt.Println("CA_EVENT "+string(b))}
func assuranceReader(t *testing.T,b *bytes.Buffer,code byte)*bufio.Reader{
 t.Helper();rd:=bufio.NewReader(bytes.NewReader(append([]byte(nil),b.Bytes()...)))
 got,e:=rd.ReadByte();if e!=nil||got!=code{t.Fatalf("missing packet code %d: got %d, %v",code,got,e)}
 return rd
}
func TestAssurancePrepareReplyPreservation(t *testing.T){
 owner,ownerOut:=assuranceNode(1)
 acceptor,acceptorOut:=assuranceNode(2)
 recovery,recoveryOut:=assuranceNode(0)
 // Owner creates the command at its legal initial ballot and emits PreAccept.
 owner.handlePropose(&defs.GPropose{Propose:&defs.Propose{ClientId:9,CommandId:1,Command:state.Command{Op:state.PUT,K:17,V:[]byte("x")}},Mutex:new(sync.Mutex)})
 pa:=new(PreAccept)
 if err:=pa.Unmarshal(assuranceReader(t,ownerOut[2],owner.preAcceptRPC));err!=nil{t.Fatal(err)}
 acceptor.handlePreAccept(pa)
 inst:=acceptor.InstanceSpace[1][0]
 if inst==nil||inst.vbal!=1||inst.Status<PREACCEPTED||len(inst.Cmds)!=1{t.Fatal("PreAccept prerequisite absent")}
 // Delay its reply to the owner. Owner and request are not modified. A recovery
 // request for the missing row instance is produced by the real recovery entry.
 // This explicit trigger substitutes the execution scanner; no timeout is claimed.
 recovery.startRecoveryForInstance(1,0)
 prepare:=new(Prepare)
 if err:=prepare.Unmarshal(assuranceReader(t,recoveryOut[2],recovery.prepareRPC));err!=nil{t.Fatal(err)}
 acceptor.handlePrepare(prepare)
 assuranceEvent(map[string]any{"event":"producer","acceptor":2,"replica":1,"instance":0,"ballot":inst.bal,"vballot":inst.vbal,"status":inst.Status,"command_count":len(inst.Cmds),"prepare_ballot":prepare.Ballot})
 decoded:=new(PrepareReply).New().(*PrepareReply)
 if err:=decoded.Unmarshal(assuranceReader(t,acceptorOut[0],acceptor.prepareReplyRPC));err!=nil{t.Fatal(err)}
 assuranceEvent(map[string]any{"event":"decoded","acceptor":decoded.AcceptorId,"replica":decoded.Replica,"instance":decoded.Instance,"ballot":decoded.Ballot,"vballot":decoded.VBallot,"status":decoded.Status,"command_count":len(decoded.Command)})
}
