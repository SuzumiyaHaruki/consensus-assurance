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

func TestAssurancePrepareValueBallot(t *testing.T) {
 n:=assuranceNewNetwork(3)
 owner,peer:=n.replicas[1],n.replicas[2]
 assurancePropose(owner,201,"value-history")
 pa,ok:=n.receive(t,1,2).(*PreAccept);if !ok {t.Fatal("expected emitted PreAccept")}
 peer.handlePreAccept(pa)
 if peer.crtInstance[1]<0 || peer.InstanceSpace[1][0].Status>=COMMITTED {t.Fatal("recovery slot not eligible")}
 // The PreAcceptReply remains pending on 2 -> 1. Receive and dispatch it
 // only after Prepare, using the production type-channel dispatch boundary.
 // Here we instead receive it now without dispatch, retaining the exact object.
 pending,ok:=n.receive(t,2,1).(*PreAcceptReply);if !ok {t.Fatal("expected pending reply")}
 _=pending
 peer.startRecoveryForInstance(1,0)
 prepare,ok:=n.receive(t,2,1).(*Prepare);if !ok {t.Fatal("expected emitted Prepare")}
 current:=owner.InstanceSpace[1][0]
 if prepare.Replica!=1 || prepare.Instance!=0 || prepare.Ballot<=current.bal || current.vbal!=1 {t.Fatal("wrong established context")}
 owner.handlePrepare(prepare)
 // The source producer copies this same local field synchronously into the
 // reply passed to SendMsg. No owner writes intervene before decode below.
 assuranceEvent(t,map[string]any{"event":"prepare_sent","origin":prepare.Replica,"instance":prepare.Instance,
  "acceptor":owner.Id,"recipient":peer.Id,"request_ballot":prepare.Ballot,"producer_vballot":current.vbal,
  "producer_status":current.Status,"bytes_queued":n.links[1][2].Len(),"emitted":n.links[1][2].Len()>0})
 reply,ok:=n.receive(t,1,2).(*PrepareReply);if !ok {t.Fatal("expected actual PrepareReply")}
 if reply.AcceptorId!=owner.Id || reply.Replica!=prepare.Replica || reply.Instance!=prepare.Instance || reply.Ballot!=prepare.Ballot {t.Fatal("wrong report correlation")}
 assuranceEvent(t,map[string]any{"event":"prepare_decoded","origin":reply.Replica,"instance":reply.Instance,
  "acceptor":reply.AcceptorId,"recipient":peer.Id,"request_ballot":reply.Ballot,"decoded_vballot":reply.VBallot,
  "decoded_status":reply.Status,"seq":reply.Seq,"deps":reply.Deps,"commands":reply.Command,"completed":true})
 // The pending PreAcceptReply was decoded before Prepare but remains undispatched.
 // This is permitted by distinct production channels. No goroutines were started.
}
