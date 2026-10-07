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
 wire "github.com/imdea-software/swiftpaxos/rpc"
 "github.com/imdea-software/swiftpaxos/state"
)

// The driver replaces socket delivery and the event-loop scheduler only. Every
// peer message below is serialized by the implementation and decoded afresh.
// All handlers and observations run synchronously; no background workers exist.
type recoveryMessage struct { from, to int; code byte; value wire.Serializable }
type recoveryNetwork struct {
 t *testing.T
 replicas []*Replica
 links [][]*bytes.Buffer
 pending []recoveryMessage
}
func recoveryEvent(kind string, fields map[string]interface{}) {
 fields["kind"] = kind
 b, err := json.Marshal(fields); if err != nil { panic(err) }
 fmt.Println("CA_EVENT " + string(b))
}
func newRecoveryNetwork(t *testing.T) *recoveryNetwork {
 n := &recoveryNetwork{t:t, replicas:make([]*Replica,3), links:make([][]*bytes.Buffer,3)}
 for id:=0;id<3;id++ {
  b:= &base.Replica{Logger:dlog.New("",false), N:3,F:1,Id:int32(id),Thrifty:true,Dreply:true,
   State:state.InitState(), Stats:&defs.Stats{M:make(map[string]int)},
   Alive:[]bool{true,true,true}, PreferredPeerOrder:[]int32{int32((id+1)%3),int32((id+2)%3),int32(id)},
   PeerWriters:make([]*bufio.Writer,3), ProposeChan:make(chan *defs.GPropose,16)}
  r:= &Replica{Replica:b, InstanceSpace:make([][]*Instance,3),crtInstance:[]int32{-1,-1,-1},
   CommittedUpTo:[]int32{-1,-1,-1},ExecedUpTo:[]int32{-1,-1,-1}, conflicts:make([]map[state.Key]*InstPair,3),
   maxSeqPerKey:make(map[state.Key]int32),latestCPInstance:-1,clientMutex:new(sync.Mutex),maxRecvBallot:-1,
   prepareRPC:1,prepareReplyRPC:2,preAcceptRPC:3,preAcceptReplyRPC:4,acceptRPC:5,acceptReplyRPC:6,commitRPC:7}
  n.links[id]=make([]*bytes.Buffer,3)
  for j:=0;j<3;j++ {r.InstanceSpace[j]=make([]*Instance,16);r.conflicts[j]=make(map[state.Key]*InstPair);n.links[id][j]=new(bytes.Buffer);b.PeerWriters[j]=bufio.NewWriter(n.links[id][j])}
  n.replicas[id]=r
 }
 return n
}
func (n *recoveryNetwork) collect() {
 for from:=0;from<3;from++ {for to:=0;to<3;to++ {
  b:=n.links[from][to]
  for b.Len()>0 {
   code,err:=b.ReadByte();if err!=nil {n.t.Fatal(err)}
   var v wire.Serializable
   switch code {case 1:v=new(Prepare);case 2:v=new(PrepareReply);case 3:v=new(PreAccept);case 4:v=new(PreAcceptReply);case 5:v=new(Accept);case 6:v=new(AcceptReply);case 7:v=new(Commit);default:n.t.Fatalf("unknown code %d",code)}
   if err:=v.Unmarshal(b);err!=nil {n.t.Fatal(err)}
   n.pending=append(n.pending,recoveryMessage{from,to,code,v})
  }
 }}
}
func messageInstance(v wire.Serializable) int32 {
 switch m:=v.(type) {case *Prepare:return m.Instance;case *PrepareReply:return m.Instance;case *PreAccept:return m.Instance;case *PreAcceptReply:return m.Instance;case *Accept:return m.Instance;case *AcceptReply:return m.Instance;case *Commit:return m.Instance};panic("unknown")
}
func (n *recoveryNetwork) deliver(from,to int,code byte,instance int32) {
 n.collect()
 for i,m:=range n.pending {
  if m.from!=from || m.to!=to || m.code!=code || messageInstance(m.value)!=instance {continue}
  n.pending=append(n.pending[:i],n.pending[i+1:]...)
  recoveryEvent("delivery",map[string]interface{}{"from":from,"to":to,"code":code,"message":m.value})
  r:=n.replicas[to]
  switch v:=m.value.(type) {case *Prepare:r.handlePrepare(v);case *PrepareReply:r.handlePrepareReply(v);case *PreAccept:r.handlePreAccept(v);case *PreAcceptReply:r.handlePreAcceptReply(v);case *Accept:r.handleAccept(v);case *AcceptReply:r.handleAcceptReply(v);case *Commit:r.handleCommit(v)}
  n.collect();return
 }
 n.t.Fatalf("missing actual message %d -> %d code %d instance %d",from,to,code,instance)
}
func (n *recoveryNetwork) observe(label string,id int,instance int32) {
 r:=n.replicas[id];v:=r.InstanceSpace[0][instance]
 fields:=map[string]interface{}{"label":label,"observer":id,"row":0,"instance":instance,"present":v!=nil,"known_up_to":r.crtInstance[0]}
 if v!=nil {fields["commands"]=v.Cmds;fields["status"]=v.Status;fields["ballot"]=v.bal;fields["value_ballot"]=v.vbal;fields["seq"]=v.Seq;fields["deps"]=v.Deps}
 recoveryEvent("state",fields)
}
func TestAssuranceRecoveryExploration(t *testing.T) {
 n:=newRecoveryNetwork(t)
 // Both instances come from real proposal handlers. The extra instance exposes
 // the hole at node 2, as required by the execution loop's recovery scan.
 for i:=int32(0);i<2;i++ {
  sink:=new(bytes.Buffer)
  n.replicas[0].handlePropose(&defs.GPropose{Propose:&defs.Propose{CommandId:i,Command:state.Command{Op:state.PUT,K:state.Key(100+i),V:state.Value{byte(40+i)}}},Reply:bufio.NewWriter(sink),Mutex:new(sync.Mutex)})
  n.deliver(0,1,3,i)
  n.deliver(1,0,4,i)
  if n.replicas[0].InstanceSpace[0][i].Status!=COMMITTED {t.Fatal("original decision prerequisite missing")}
 }
 // Commit for 0.0 remains pending at node 2. Independent message goroutines
 // and distinct channel scheduling permit 0.1 to be handled first.
 n.deliver(0,2,7,1)
 n.observe("original_decision",0,0)
 n.observe("recovery_hole",2,0)
 if n.replicas[2].crtInstance[0]!=1 || n.replicas[2].InstanceSpace[0][0]!=nil {t.Fatal("hole prerequisite missing")}
 // Invoke the loop's recovery action once its timeout condition is eligible.
 // This exploration checks the action, not timer accuracy or eventual progress.
 n.replicas[2].startRecoveryForInstance(0,0)
 n.observe("promoted_self",2,0)
 n.deliver(2,0,1,0)
 n.deliver(0,2,2,0)
 n.observe("after_selection",2,0)
 // Follow the selected value through the implementation's own outgoing work.
 n.deliver(2,0,3,0)
 n.deliver(0,2,4,0)
 n.observe("after_recovered_preaccept",2,0)
 n.deliver(2,0,5,0)
 n.deliver(0,2,6,0)
 n.observe("original_final",0,0)
 n.observe("recovered_final",2,0)
 recoveryEvent("endpoint",map[string]interface{}{"pending_messages":len(n.pending),"handlers_completed":true})
}
