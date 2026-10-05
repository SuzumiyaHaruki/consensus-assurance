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

// Isolate synchronous handlers. Reproduce constructor state for a five-node,
// volatile, thrifty configuration, with bounded empty instance rows. No network,
// timer, execution goroutine or file is opened; captured streams replace TCP.
func assuranceNode(id int32) (*Replica, []*bytes.Buffer) {
 const n = 5
 r := &Replica{Replica: &base.Replica{
  Logger:dlog.New("",false), N:n,F:2,Id:id, Thrifty:true,Dreply:true,
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
func TestAssuranceAcceptPhaseExploration(t *testing.T){
 owner,oo:=assuranceNode(1)
 acceptor,ao:=assuranceNode(2)
 other,bo:=assuranceNode(3)
 recovery,ro:=assuranceNode(0)
 propose:=func(r *Replica,k state.Key,v string){r.handlePropose(&defs.GPropose{Propose:&defs.Propose{ClientId:r.Id+10,CommandId:1,Command:state.Command{Op:state.PUT,K:k,V:[]byte(v)}},Mutex:new(sync.Mutex)})}
 // A local pending conflicting command at recipient 2 makes its generated
 // PreAccept reply differ from recipient 3. Its outgoing messages stay pending.
 propose(acceptor,17,"earlier")
 propose(owner,17,"target")
 for _,entry:=range []struct{r *Replica;buf *bytes.Buffer}{{acceptor,oo[2]},{other,oo[3]}}{
  pa:=new(PreAccept);if err:=pa.Unmarshal(assuranceReader(t,entry.buf,owner.preAcceptRPC));err!=nil{t.Fatal(err)}
  entry.r.handlePreAccept(pa);entry.buf.Reset()
 }
 for _,buf:=range []*bytes.Buffer{ao[1],bo[1]}{
  reply:=new(PreAcceptReply);if err:=reply.Unmarshal(assuranceReader(t,buf,acceptor.preAcceptReplyRPC));err!=nil{t.Fatal(err)}
  owner.handlePreAcceptReply(reply);buf.Reset()
 }
 if owner.InstanceSpace[1][0].Status!=ACCEPTED{t.Fatal("slow path not reached")}
 a:=new(Accept);if err:=a.Unmarshal(assuranceReader(t,oo[2],owner.acceptRPC));err!=nil{t.Fatal(err)}
 before:=acceptor.InstanceSpace[1][0]
 assuranceEvent(map[string]any{"event":"accept_input","acceptor":2,"replica":a.Replica,"instance":a.Instance,"ballot":a.Ballot,"prior_ballot":before.bal,"prior_status":before.Status,"seq":a.Seq,"deps":a.Deps})
 acceptor.handleAccept(a)
 ack:=new(AcceptReply);if err:=ack.Unmarshal(assuranceReader(t,ao[1],acceptor.acceptReplyRPC));err!=nil{t.Fatal(err)}
 owner.handleAcceptReply(ack)
 if owner.InstanceSpace[1][0].lb.acceptOKs!=1{t.Fatal("ack not counted")}
 assuranceEvent(map[string]any{"event":"accept_ack","acceptor":2,"replica":ack.Replica,"instance":ack.Instance,"ballot":ack.Ballot,"counted":owner.InstanceSpace[1][0].lb.acceptOKs,"recipient_status":before.Status,"recipient_vballot":before.vbal,"recipient_seq":before.Seq})
 // No quorum of Accept replies and no Commit; explicitly invoke recovery to
 // generate a higher-ballot Prepare, without asserting scanner reachability.
 recovery.startRecoveryForInstance(1,0)
 p:=new(Prepare);if err:=p.Unmarshal(assuranceReader(t,ro[2],recovery.prepareRPC));err!=nil{t.Fatal(err)}
 acceptor.handlePrepare(p)
 pr:=new(PrepareReply).New().(*PrepareReply)
 if err:=pr.Unmarshal(assuranceReader(t,ao[0],acceptor.prepareReplyRPC));err!=nil{t.Fatal(err)}
 assuranceEvent(map[string]any{"event":"prepare_report","acceptor":pr.AcceptorId,"replica":pr.Replica,"instance":pr.Instance,"ballot":pr.Ballot,"status":pr.Status,"live_status":before.Status,"live_vballot":before.vbal,"seq":pr.Seq,"deps":pr.Deps,"command_count":len(pr.Command)})
}
