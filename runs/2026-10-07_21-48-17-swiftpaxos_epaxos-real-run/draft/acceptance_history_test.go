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
 rpc "github.com/imdea-software/swiftpaxos/rpc"
 "github.com/imdea-software/swiftpaxos/state"
)

// Single-owner handler schedule. SendMsg and all message codecs are unchanged.
// Each directed link is a byte stream; receive consumes its next actual message.
type assuranceNetwork struct {
 replicas []*Replica
 links [][]*bytes.Buffer
}

func assuranceNewNetwork(n int) *assuranceNetwork {
 net := &assuranceNetwork{replicas: make([]*Replica,n), links:make([][]*bytes.Buffer,n)}
 for id:=0; id<n; id++ {
  br:= &base.Replica{Logger:dlog.New("",false), N:n,F:(n-1)/2,Id:int32(id),
   Alive:make([]bool,n),PreferredPeerOrder:make([]int32,n),PeerWriters:make([]*bufio.Writer,n),
   State:state.InitState(),RPC:rpc.NewTableId(defs.RPC_TABLE),Stats:&defs.Stats{M:make(map[string]int)},
   ProposeChan:make(chan *defs.GPropose,16),Thrifty:true,Exec:true,Dreply:true}
  r:= &Replica{Replica:br, InstanceSpace:make([][]*Instance,n),crtInstance:make([]int32,n),
   CommittedUpTo:make([]int32,n),ExecedUpTo:make([]int32,n),conflicts:make([]map[state.Key]*InstPair,n),
   maxSeqPerKey:make(map[state.Key]int32),latestCPInstance:-1,clientMutex:new(sync.Mutex),
   instancesToRecover:make(chan *instanceId,16),maxRecvBallot:-1}
  r.exec=&Exec{r}
  r.prepareRPC=r.RPC.Register(new(Prepare),nil)
  r.prepareReplyRPC=r.RPC.Register(new(PrepareReply),nil)
  r.preAcceptRPC=r.RPC.Register(new(PreAccept),nil)
  r.preAcceptReplyRPC=r.RPC.Register(new(PreAcceptReply),nil)
  r.acceptRPC=r.RPC.Register(new(Accept),nil)
  r.acceptReplyRPC=r.RPC.Register(new(AcceptReply),nil)
  r.commitRPC=r.RPC.Register(new(Commit),nil)
  r.tryPreAcceptRPC=r.RPC.Register(new(TryPreAccept),nil)
  r.tryPreAcceptReplyRPC=r.RPC.Register(new(TryPreAcceptReply),nil)
  net.links[id]=make([]*bytes.Buffer,n)
  for peer:=0;peer<n;peer++ {
   r.InstanceSpace[peer]=make([]*Instance,16)
   r.crtInstance[peer]=-1;r.CommittedUpTo[peer]=-1;r.ExecedUpTo[peer]=-1
   r.conflicts[peer]=make(map[state.Key]*InstPair)
   r.PreferredPeerOrder[peer]=int32((id+1+peer)%n)
   r.Alive[peer]=peer!=id
   net.links[id][peer]=new(bytes.Buffer)
   r.PeerWriters[peer]=bufio.NewWriter(net.links[id][peer])
  }
  net.replicas[id]=r
 }
 return net
}

func assuranceEvent(t *testing.T, fields map[string]any) {
 t.Helper(); b,err:=json.Marshal(fields);if err!=nil {t.Fatal(err)}
 fmt.Println("CA_EVENT "+string(b))
}

func (n *assuranceNetwork) receive(t *testing.T,from,to int) rpc.Serializable {
 t.Helper()
 stream:=n.links[from][to]
 code,err:=stream.ReadByte();if err!=nil {t.Fatalf("missing message %d -> %d: %v",from,to,err)}
 pair,ok:=n.replicas[to].RPC.Get(code);if !ok {t.Fatalf("unknown message code %d",code)}
 msg:=pair.Obj.New();if err:=msg.Unmarshal(stream);err!=nil {t.Fatalf("decode %d -> %d: %v",from,to,err)}
 assuranceEvent(t,map[string]any{"event":"delivery","from":from,"to":to,"message_type":fmt.Sprintf("%T",msg),"message":msg})
 return msg
}

func assurancePropose(r *Replica, commandID int32, value string) {
 r.handlePropose(&defs.GPropose{Propose:&defs.Propose{CommandId:commandID,ClientId:r.Id,
  Command:state.Command{Op:state.PUT,K:17,V:state.Value(value)}},Mutex:new(sync.Mutex)})
}

func TestAssuranceAcceptedHistory(t *testing.T) {
 n:=assuranceNewNetwork(5)
 r0,r1,r2:=n.replicas[0],n.replicas[1],n.replicas[2]
 // An independently proposed conflicting command remains pending at replica 1.
 // Its broadcasts remain buffered; no message is dropped or forged.
 assurancePropose(r1,101,"prior")
 assurancePropose(r0,100,"target")
 pa1,ok:=n.receive(t,0,1).(*PreAccept);if !ok {t.Fatal("expected PreAccept")}
 r1.handlePreAccept(pa1)
 pa2,ok:=n.receive(t,0,2).(*PreAccept);if !ok {t.Fatal("expected PreAccept")}
 r2.handlePreAccept(pa2)
 pr1,ok:=n.receive(t,1,0).(*PreAcceptReply);if !ok {t.Fatal("expected PreAcceptReply")}
 r0.handlePreAcceptReply(pr1)
 pr2,ok:=n.receive(t,2,0).(*PreAcceptReply);if !ok {t.Fatal("expected PreAcceptReply")}
 r0.handlePreAcceptReply(pr2)
 if r0.InstanceSpace[0][0].lb.status!=ACCEPTED {t.Fatal("producer did not enter slow acceptance")}
 a,ok:=n.receive(t,0,2).(*Accept);if !ok {t.Fatal("expected producer-generated Accept")}
 before:=r2.InstanceSpace[a.Replica][a.Instance]
 if before==nil || before.Status>=COMMITTED || a.Ballot<before.bal {t.Fatal("Accept admission premise not met")}
 if a.Replica!=0 || a.Instance!=0 || len(before.Cmds)!=1 || string(before.Cmds[0].V)!="target" {t.Fatal("wrong target identity or command")}
 r2.handleAccept(a)
 ack,ok:=n.receive(t,2,0).(*AcceptReply);if !ok {t.Fatal("expected AcceptReply")}
 if ack.Replica!=a.Replica || ack.Instance!=a.Instance || ack.Ballot!=a.Ballot {t.Fatal("Accept was not acknowledged at its ballot")}
 // Consumption is real, but a single remote reply is not a five-node majority.
 r0.handleAcceptReply(ack)
 assuranceEvent(t,map[string]any{"event":"accepted_ack","origin":a.Replica,"instance":a.Instance,"acceptor":2,
  "ballot":ack.Ballot,"seq":a.Seq,"deps":a.Deps,"command":"target","coordinator_accept_count":r0.InstanceSpace[0][0].lb.acceptOKs,
  "admitted":true,"expected_status":ACCEPTED})
 // Deliver the older message on link 1 -> 2 before the later Prepare.
 seed,ok:=n.receive(t,1,2).(*PreAccept);if !ok {t.Fatal("expected pending independent PreAccept")}
 r2.handlePreAccept(seed)
 seedReply,ok:=n.receive(t,2,1).(*PreAcceptReply);if !ok {t.Fatal("expected independent reply")}
 r1.handlePreAcceptReply(seedReply)
 if r1.crtInstance[a.Replica]<a.Instance || r1.InstanceSpace[a.Replica][a.Instance].Status>=COMMITTED {t.Fatal("slot is not eligible for recovery scan")}
 // The recovery entry produces the next Prepare for the known stalled slot.
 // No prepare replies are fed to the recovery coordinator: self-vbal selection
 // is outside this local history-reporting proposition.
 r1.startRecoveryForInstance(a.Replica,a.Instance)
 prepare,ok:=n.receive(t,1,2).(*Prepare);if !ok {t.Fatal("expected generated Prepare")}
 if prepare.Replica!=a.Replica || prepare.Instance!=a.Instance || prepare.Ballot<=a.Ballot {t.Fatal("wrong recovery context")}
 r2.handlePrepare(prepare)
 report,ok:=n.receive(t,2,1).(*PrepareReply);if !ok {t.Fatal("expected PrepareReply")}
 if report.AcceptorId!=2 || report.Replica!=a.Replica || report.Instance!=a.Instance || report.Ballot!=prepare.Ballot {t.Fatal("report identity/context mismatch")}
 assuranceEvent(t,map[string]any{"event":"prepare_report","origin":report.Replica,"instance":report.Instance,"acceptor":report.AcceptorId,
  "promise":report.Ballot,"value_ballot":report.VBallot,"status":report.Status,"seq":report.Seq,"deps":report.Deps,"commands":report.Command,
  "completed":true})
 // No workers, sockets, files, or timers were started. Pending byte streams are
 // the explicit undelivered suffix of this finite schedule, not blocked workers.
}
