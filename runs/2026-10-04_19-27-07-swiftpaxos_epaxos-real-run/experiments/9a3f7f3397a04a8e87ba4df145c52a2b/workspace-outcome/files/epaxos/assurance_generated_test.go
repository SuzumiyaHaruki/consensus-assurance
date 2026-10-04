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
 wire "github.com/imdea-software/swiftpaxos/rpc"
 "github.com/imdea-software/swiftpaxos/state"
)

// The driver substitutes finite-capacity instance allocation and a serial event
// scheduler for sockets, goroutines and timers. Protocol messages are produced
// by target handlers and transported through the target Marshal/Unmarshal pair.
// It does not edit protocol state after initialization or duplicate deliveries.
type arMessage struct { from, to int; value wire.Serializable }
type arNetwork struct { t *testing.T; rs []*Replica; links [][]*bytes.Buffer; pending []arMessage }
func arEvent(name string, fields map[string]interface{}) {
 fields["event"] = name
 b, err := json.Marshal(fields); if err != nil { panic(err) }; fmt.Println("CA_EVENT " + string(b))
}
func arNew(t *testing.T) *arNetwork {
 n:= &arNetwork{t:t, rs:make([]*Replica,5), links:make([][]*bytes.Buffer,5)}
 for id:=0;id<5;id++ {
  base:= &replica.Replica{Logger:dlog.New("",false),N:5,F:2,Id:int32(id),Thrifty:true,Dreply:true,Exec:true,
   Alive:[]bool{true,true,true,true,true},PreferredPeerOrder:make([]int32,5),PeerWriters:make([]*bufio.Writer,5),
   State:state.InitState(),Stats:&defs.Stats{M:make(map[string]int)},ProposeChan:make(chan *defs.GPropose,16)}
  for k:=0;k<5;k++ {base.PreferredPeerOrder[k]=int32((id+1+k)%5)}
  // A fixed allowed preference order for replica 1, established before work.
  if id==1 {base.PreferredPeerOrder=[]int32{3,4,0,2,1}}
  r:= &Replica{Replica:base,InstanceSpace:make([][]*Instance,5),crtInstance:make([]int32,5),CommittedUpTo:make([]int32,5),ExecedUpTo:make([]int32,5),conflicts:make([]map[state.Key]*InstPair,5),maxSeqPerKey:make(map[state.Key]int32),latestCPInstance:-1,clientMutex:new(sync.Mutex),instancesToRecover:make(chan *instanceId,16),maxRecvBallot:-1}
  for k:=0;k<5;k++ { r.InstanceSpace[k]=make([]*Instance,16);r.crtInstance[k]=-1;r.CommittedUpTo[k]=-1;r.ExecedUpTo[k]=-1;r.conflicts[k]=make(map[state.Key]*InstPair) }
  r.exec=&Exec{r}
  r.prepareRPC=1;r.prepareReplyRPC=2;r.preAcceptRPC=3;r.preAcceptReplyRPC=4;r.acceptRPC=5;r.acceptReplyRPC=6;r.commitRPC=7;r.tryPreAcceptRPC=8;r.tryPreAcceptReplyRPC=9
  n.rs[id]=r;n.links[id]=make([]*bytes.Buffer,5)
  for to:=0;to<5;to++ {n.links[id][to]=new(bytes.Buffer);base.PeerWriters[to]=bufio.NewWriter(n.links[id][to])}
 }
 return n
}
func arType(code byte) wire.Serializable {
 switch code {case 1:return new(Prepare);case 2:return new(PrepareReply);case 3:return new(PreAccept);case 4:return new(PreAcceptReply);case 5:return new(Accept);case 6:return new(AcceptReply);case 7:return new(Commit);case 8:return new(TryPreAccept);case 9:return new(TryPreAcceptReply)}
 panic("unknown message code")
}
func (n *arNetwork) harvest() {
 for from:=0;from<5;from++ {for to:=0;to<5;to++ {b:=n.links[from][to];for b.Len()>0 {
  code,err:=b.ReadByte();if err!=nil {n.t.Fatal(err)};m:=arType(code);if err=m.Unmarshal(b);err!=nil {n.t.Fatal(err)}
  n.pending=append(n.pending,arMessage{from,to,m})
 }}}
}
func (n *arNetwork) deliver(from,to int, kind string) {
 n.harvest()
 for i,m:=range n.pending { if m.from!=from || m.to!=to || fmt.Sprintf("%T",m.value)!=kind {continue}
  n.pending=append(n.pending[:i],n.pending[i+1:]...)
  arEvent("delivery",map[string]interface{}{"from":from,"to":to,"kind":kind,"message":m.value})
  r:=n.rs[to]
  switch v:=m.value.(type) {case *Prepare:r.handlePrepare(v);case *PrepareReply:r.handlePrepareReply(v);case *PreAccept:r.handlePreAccept(v);case *PreAcceptReply:r.handlePreAcceptReply(v);case *Accept:r.handleAccept(v);case *AcceptReply:r.handleAcceptReply(v);case *Commit:r.handleCommit(v);default:n.t.Fatalf("unexpected delivery %T",v)}
  n.harvest();return
 }
 n.t.Fatalf("missing queued %s %d -> %d",kind,from,to)
}
func (n *arNetwork) propose(id int, value string, cid int32) {
 p:= &defs.GPropose{Propose:&defs.Propose{CommandId:cid,Command:state.Command{Op:state.PUT,K:7,V:state.Value(value)}},Reply:bufio.NewWriter(new(bytes.Buffer)),Mutex:new(sync.Mutex)}
 n.rs[id].handlePropose(p);n.harvest()
}
func arSnapshot(n *arNetwork, stage string, observer int) {
 i:=n.rs[observer].InstanceSpace[0][0]
 arEvent("snapshot",map[string]interface{}{"stage":stage,"observer":observer,"origin":0,"instance":0,"status":i.Status,"bal":i.bal,"vbal":i.vbal,"seq":i.Seq,"deps":append([]int32(nil),i.Deps...),"cmds":i.Cmds})
}
func TestAssuranceAcceptRecoveryExplore(t *testing.T) {
 n:=arNew(t)
 arEvent("setup",map[string]interface{}{"n":5,"f":2,"thrifty":true,"durable":false,"fast_quorum":n.rs[0].FastQuorumSize(),"slow_quorum":n.rs[0].SlowQuorumSize()})
 // Background conflicting proposal remains pending at its origin 2.
 n.propose(2,"background",20)
 n.propose(0,"principal",10)
 n.deliver(0,1,"*epaxos.PreAccept");n.deliver(0,2,"*epaxos.PreAccept")
 n.deliver(1,0,"*epaxos.PreAcceptReply");n.deliver(2,0,"*epaxos.PreAcceptReply")
 if n.rs[0].InstanceSpace[0][0].lb.status!=ACCEPTED {t.Fatal("slow path not reached")}
 n.deliver(0,1,"*epaxos.Accept");n.deliver(0,2,"*epaxos.Accept")
 arSnapshot(n,"after_accept",1)
 n.deliver(1,0,"*epaxos.AcceptReply");n.deliver(2,0,"*epaxos.AcceptReply")
 if n.rs[0].InstanceSpace[0][0].Status!=COMMITTED {t.Fatal("first decision not reached")}
 arSnapshot(n,"first_decision",0)
 // All Commit messages and background messages remain queued. A timer-driven
 // recovery entry is invoked for the known incomplete slot at replica 1.
 // No claim about elapsed time or automatic trigger completion is measured.
 n.rs[1].startRecoveryForInstance(0,0);n.harvest()
 n.deliver(1,3,"*epaxos.Prepare");n.deliver(1,4,"*epaxos.Prepare")
 n.deliver(3,1,"*epaxos.PrepareReply");n.deliver(4,1,"*epaxos.PrepareReply")
 arSnapshot(n,"after_recovery_selection",1)
 n.deliver(1,3,"*epaxos.PreAccept");n.deliver(1,4,"*epaxos.PreAccept")
 n.deliver(3,1,"*epaxos.PreAcceptReply");n.deliver(4,1,"*epaxos.PreAcceptReply")
 n.deliver(1,3,"*epaxos.Accept");n.deliver(1,4,"*epaxos.Accept")
 n.deliver(3,1,"*epaxos.AcceptReply");n.deliver(4,1,"*epaxos.AcceptReply")
 arSnapshot(n,"second_decision",1)
 arSnapshot(n,"first_decision_retained",0)
 arEvent("end",map[string]interface{}{"pending_messages":len(n.pending),"stop_rule":"fixed finite delivery script complete"})
}
