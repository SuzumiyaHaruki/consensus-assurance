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

type assuranceEnvelope struct { from,to int; msg fastrpc.Serializable }
type assuranceNet struct { t *testing.T; nodes []*Replica; wire [][]*bytes.Buffer; queue []assuranceEnvelope; step int }
func assuranceEvent(kind string, fields map[string]any) { fields["kind"]=kind; b,err:=json.Marshal(fields); if err!=nil {panic(err)}; fmt.Println("CA_EVENT "+string(b)) }
func assuranceNewNet(t *testing.T) *assuranceNet {
 const n=5
 net:=&assuranceNet{t:t,nodes:make([]*Replica,n),wire:make([][]*bytes.Buffer,n)}
 for id:=0;id<n;id++ {
  base:=&replica.Replica{Logger:dlog.New("",false),N:n,F:2,Id:int32(id),Thrifty:true,Dreply:true,State:state.InitState(),Stats:&defs.Stats{M:make(map[string]int)},Alive:make([]bool,n),PreferredPeerOrder:make([]int32,n),PeerWriters:make([]*bufio.Writer,n),ProposeChan:make(chan *defs.GPropose,16),RPC:fastrpc.NewTableId(defs.RPC_TABLE)}
  r:=&Replica{Replica:base,InstanceSpace:make([][]*Instance,n),crtInstance:make([]int32,n),CommittedUpTo:make([]int32,n),ExecedUpTo:make([]int32,n),conflicts:make([]map[state.Key]*InstPair,n),maxSeqPerKey:make(map[state.Key]int32),maxRecvBallot:-1,latestCPInstance:-1,instancesToRecover:make(chan *instanceId,16)}
  net.nodes[id]=r;net.wire[id]=make([]*bytes.Buffer,n)
  for q:=0;q<n;q++ { r.InstanceSpace[q]=make([]*Instance,16);r.crtInstance[q]=-1;r.CommittedUpTo[q]=-1;r.ExecedUpTo[q]=-1;r.conflicts[q]=make(map[state.Key]*InstPair);r.Alive[q]=true;r.PreferredPeerOrder[q]=int32((id+1+q)%n);net.wire[id][q]=new(bytes.Buffer);r.PeerWriters[q]=bufio.NewWriter(net.wire[id][q]) }
  r.prepareRPC=base.RPC.Register(new(Prepare),nil);r.prepareReplyRPC=base.RPC.Register(new(PrepareReply),nil);r.preAcceptRPC=base.RPC.Register(new(PreAccept),nil);r.preAcceptReplyRPC=base.RPC.Register(new(PreAcceptReply),nil);r.acceptRPC=base.RPC.Register(new(Accept),nil);r.acceptReplyRPC=base.RPC.Register(new(AcceptReply),nil);r.commitRPC=base.RPC.Register(new(Commit),nil);r.tryPreAcceptRPC=base.RPC.Register(new(TryPreAccept),nil);r.tryPreAcceptReplyRPC=base.RPC.Register(new(TryPreAcceptReply),nil)
 }
 return net
}
func (n *assuranceNet) collect() {
 for from,row:=range n.wire { for to,b:=range row {for b.Len()>0 {code,err:=b.ReadByte();if err!=nil{n.t.Fatal(err)};pair,ok:=n.nodes[to].RPC.Get(code);if !ok{n.t.Fatal("unknown RPC",code)};msg:=pair.Obj.New();if err:=msg.Unmarshal(b);err!=nil{n.t.Fatal(err)};n.queue=append(n.queue,assuranceEnvelope{from,to,msg});assuranceEvent("send",map[string]any{"from":from,"to":to,"type":fmt.Sprintf("%T",msg),"message":msg})}} }
}
func (n *assuranceNet) deliver(from,to int,typ string, origin,slot int32) {
 n.t.Helper()
 for i,e:=range n.queue {if e.from!=from||e.to!=to||fmt.Sprintf("%T",e.msg)!=typ {continue};var r,s int32
  switch m:=e.msg.(type){case *PreAccept:r,s=m.Replica,m.Instance;case *PreAcceptReply:r,s=m.Replica,m.Instance;case *Accept:r,s=m.Replica,m.Instance;case *AcceptReply:r,s=m.Replica,m.Instance;case *Prepare:r,s=m.Replica,m.Instance;case *PrepareReply:r,s=m.Replica,m.Instance;case *Commit:r,s=m.Replica,m.Instance;default:n.t.Fatal("unsupported dispatch")}
  if r!=origin||s!=slot{continue};n.queue=append(n.queue[:i],n.queue[i+1:]...);n.step++;assuranceEvent("dispatch",map[string]any{"step":n.step,"from":from,"to":to,"type":typ,"message":e.msg})
  target:=n.nodes[to];switch m:=e.msg.(type){case *PreAccept:target.handlePreAccept(m);case *PreAcceptReply:target.handlePreAcceptReply(m);case *Accept:target.handleAccept(m);case *AcceptReply:target.handleAcceptReply(m);case *Prepare:target.handlePrepare(m);case *PrepareReply:target.handlePrepareReply(m);case *Commit:target.handleCommit(m)};n.collect();return
 };n.t.Fatalf("missing %s %d->%d for %d.%d",typ,from,to,origin,slot)
}
func (n *assuranceNet) snapshot(label string,id int,origin,slot int32) {
 inst:=n.nodes[id].InstanceSpace[origin][slot];if inst==nil{assuranceEvent(label,map[string]any{"observer":id,"replica":origin,"instance":slot,"present":false});return}
 assuranceEvent(label,map[string]any{"observer":id,"replica":origin,"instance":slot,"present":true,"status":inst.Status,"ballot":inst.bal,"value_ballot":inst.vbal,"commands":inst.Cmds,"seq":inst.Seq,"deps":inst.Deps})
}
func TestAssuranceExploreAcceptRecovery(t *testing.T) {
 n:=assuranceNewNet(t)
 // Bounded constructor-equivalent storage, serial handlers and captured real wire bytes.
 // No application executor, client reply waiter, timers or network goroutines run.
 // The schedule retains rather than drains undelivered messages.
 for _,id:=range []int{1,0} {r:=n.nodes[id];r.handlePropose(&defs.GPropose{Propose:&defs.Propose{Command:state.Command{Op:state.PUT,K:10,V:state.Value{byte(id+1)}}}});n.collect()}
 n.deliver(0,1,"*epaxos.PreAccept",0,0);n.deliver(0,2,"*epaxos.PreAccept",0,0)
 n.deliver(1,0,"*epaxos.PreAcceptReply",0,0);n.deliver(2,0,"*epaxos.PreAcceptReply",0,0)
 n.snapshot("coordinator_after_preaccept",0,0,0)
 for _,id:=range []int{1,2} {n.deliver(0,id,"*epaxos.Accept",0,0);n.snapshot("follower_after_accept",id,0,0)}
 n.deliver(1,0,"*epaxos.AcceptReply",0,0);n.deliver(2,0,"*epaxos.AcceptReply",0,0)
 n.snapshot("original_coordinator_decision",0,0,0)
 // Replica 0 stops participating after producing Commit; its messages remain in flight.
 for _,r:=range n.nodes {r.Alive[0]=false}
 assuranceEvent("fault_policy",map[string]any{"failed_replica":0,"future_dispatch_to_or_from_failed":false,"pending_messages":len(n.queue)})
 // Direct recovery entry is exploratory: unseen-slot admission by the scanner is not assumed.
 n.nodes[3].startRecoveryForInstance(0,0);n.collect();n.snapshot("recoverer_after_start",3,0,0)
 n.deliver(3,1,"*epaxos.Prepare",0,0);n.deliver(3,2,"*epaxos.Prepare",0,0)
 n.deliver(1,3,"*epaxos.PrepareReply",0,0);n.deliver(2,3,"*epaxos.PrepareReply",0,0)
 n.snapshot("recoverer_after_prepare",3,0,0)
 for _,id:=range []int{4,1}{n.deliver(3,id,"*epaxos.PreAccept",0,0)}
 for _,id:=range []int{4,1}{n.deliver(id,3,"*epaxos.PreAcceptReply",0,0)}
 for _,id:=range []int{4,1}{n.deliver(3,id,"*epaxos.Accept",0,0)}
 for _,id:=range []int{4,1}{n.deliver(id,3,"*epaxos.AcceptReply",0,0)}
 n.snapshot("recovery_coordinator_decision",3,0,0)
 assuranceEvent("exploration_complete",map[string]any{"pending_messages":len(n.queue),"dispatch_count":n.step})
}
