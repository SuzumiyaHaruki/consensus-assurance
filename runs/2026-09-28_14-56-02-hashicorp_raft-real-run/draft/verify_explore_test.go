package raft

import (
 "encoding/json"
 "fmt"
 "sync"
 "testing"
 "time"

 "github.com/hashicorp/go-hclog"
)

// Transport faults affect delivery only. All successful replies come from real Raft handlers.
type assuranceTransport struct {
 *InmemTransport
 mu sync.Mutex
 blocked map[ServerID]bool
 failed map[string]int
 epoch uint64
}
func (x *assuranceTransport) AppendEntriesPipeline(id ServerID, addr ServerAddress) (AppendPipeline, error) {
 return nil, ErrPipelineReplicationNotSupported
}
func (x *assuranceTransport) AppendEntries(id ServerID, addr ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
 kind := "append"
 if req.PrevLogEntry == 0 && req.PrevLogTerm == 0 && len(req.Entries) == 0 && req.LeaderCommitIndex == 0 { kind = "heartbeat" }
 x.mu.Lock()
 epoch := x.epoch
 blocked := x.blocked[id]
 if blocked { x.failed[string(id)+"/"+kind]++ }
 x.mu.Unlock()
 if blocked { return fmt.Errorf("controlled partition to %s", id) }
 err := x.InmemTransport.AppendEntries(id, addr, req, resp)
 x.mu.Lock()
 changed := epoch != x.epoch && x.blocked[id]
 x.mu.Unlock()
 if changed { return fmt.Errorf("partition crossed response delivery to %s", id) }
 return err
}
func assuranceEvent(kind string, fields map[string]interface{}) {
 fields["event"] = kind
 b, _ := json.Marshal(fields)
 fmt.Println("CA_EVENT " + string(b))
}
func assuranceWait(t *testing.T, what string, limit time.Duration, predicate func() bool) {
 t.Helper()
 deadline := time.Now().Add(limit)
 for time.Now().Before(deadline) {
  if predicate() { return }
  time.Sleep(5*time.Millisecond)
 }
 t.Fatalf("prefix incomplete: %s", what)
}
func assuranceError(t *testing.T, what string, f Future) error {
 t.Helper()
 done := make(chan error, 1)
 go func(){ done <- f.Error() }()
 select {
 case err := <-done: return err
 case <-time.After(8*time.Second): t.Fatalf("incomplete future: %s", what); return fmt.Errorf("timeout")
 }
}
func TestAssuranceVerifyNonvoterHistory(t *testing.T) {
 const history = "verify-partition-1"
 ids := []ServerID{"A", "B", "C", "D"}
 nodes := make([]*Raft, 4)
 fsms := make([]*MockFSM, 4)
 trans := make([]*assuranceTransport, 4)
 for i, id := range ids {
  _, base := NewInmemTransportWithTimeout(ServerAddress(id), 100*time.Millisecond)
  trans[i] = &assuranceTransport{InmemTransport:base, blocked:make(map[ServerID]bool), failed:make(map[string]int)}
 }
 for i := range trans { for j := range trans { if i != j { trans[i].Connect(ServerAddress(ids[j]), trans[j].InmemTransport) } } }
 defer func(){
  for _, n := range nodes { if n != nil { n.Shutdown() } }
  for _, n := range nodes { if n != nil { _ = n.Shutdown().Error() } }
  for _, tr := range trans { _ = tr.Close() }
 }()
 for i,id := range ids {
  conf := DefaultConfig()
  conf.LocalID = id
  conf.HeartbeatTimeout = 200*time.Millisecond
  conf.ElectionTimeout = 200*time.Millisecond
  conf.LeaderLeaseTimeout = 100*time.Millisecond
  conf.CommitTimeout = 10*time.Millisecond
  conf.Logger = hclog.NewNullLogger()
  if i == 0 {
   conf.HeartbeatTimeout = 2*time.Second
   conf.ElectionTimeout = 2*time.Second
   conf.LeaderLeaseTimeout = 2*time.Second
  }
  store := NewInmemStore()
  fsms[i] = &MockFSM{}
  n, err := NewRaft(conf, fsms[i], store, store, NewInmemSnapshotStore(), trans[i])
  if err != nil { t.Fatal(err) }
  nodes[i] = n
 }
 if err := assuranceError(t,"bootstrap",nodes[0].BootstrapCluster(Configuration{Servers:[]Server{{ID:"A",Address:"A",Suffrage:Voter}}})); err != nil {t.Fatal(err)}
 assuranceWait(t,"A elected from single-voter bootstrap",6*time.Second,func()bool{return nodes[0].State()==Leader})
 if err:=assuranceError(t,"add D nonvoter",nodes[0].AddNonvoter("D","D",0,time.Second));err!=nil{t.Fatal(err)}
 for _,id := range []ServerID{"B","C"} {
  if err:=assuranceError(t,"add voter",nodes[0].AddVoter(id,ServerAddress(id),0,time.Second));err!=nil{t.Fatal(err)}
 }
 prefix := nodes[0].Apply([]byte("prefix"),time.Second)
 if err:=assuranceError(t,"prefix apply",prefix);err!=nil{t.Fatal(err)}
 for i := range nodes {
  ii:=i
  assuranceWait(t,"configuration and prefix propagation",3*time.Second,func()bool{
   cf:=nodes[ii].GetConfiguration()
   if cf.Error()!=nil{return false}
   return len(cf.Configuration().Servers)==4 && len(fsms[ii].Logs())>=1
  })
 }
 control:=nodes[0].VerifyLeader()
 if err:=assuranceError(t,"connected verification",control);err!=nil{t.Fatal(err)}
 assuranceEvent("prefix",map[string]interface{}{"history":history,"leader":"A","term":nodes[0].CurrentTerm(),"prefix_index":prefix.Index(),"control_ok":true,"voters":3,"nonvoters":1})
 // Split {A,D} from {B,C}. Disable existing and future cross-partition routes.
 for i := range trans {
  for j := range trans {
   if (i==0||i==3)!=(j==0||j==3) {
    trans[i].mu.Lock();trans[i].epoch++;trans[i].blocked[ids[j]]=true;trans[i].mu.Unlock()
    trans[i].Disconnect(ServerAddress(ids[j]))
   }
  }
 }
 // Each of A's two sequential workers must begin a failed post-partition RPC.
 // This proves its preceding pre-partition callback has already run.
 assuranceWait(t,"old voter reply drain",time.Second,func()bool{
  trans[0].mu.Lock();defer trans[0].mu.Unlock()
  return trans[0].failed["B/append"]>0 && trans[0].failed["B/heartbeat"]>0 && trans[0].failed["C/append"]>0 && trans[0].failed["C/heartbeat"]>0
 })
 next:=-1
 assuranceWait(t,"majority election",1500*time.Millisecond,func()bool{
  for _,i:=range []int{1,2}{if nodes[i].State()==Leader{next=i;return true}}
  return false
 })
 newWrite:=nodes[next].Apply([]byte("majority-after-partition"),time.Second)
 if err:=assuranceError(t,"majority apply",newWrite);err!=nil{t.Fatal(err)}
 assuranceEvent("new_leader_apply",map[string]interface{}{"history":history,"leader":ids[next],"term":nodes[next].CurrentTerm(),"index":newWrite.Index(),"old_state":nodes[0].State().String(),"old_fsm_count":len(fsms[0].Logs()),"new_fsm_count":len(fsms[next].Logs())})
 op:="verify-after-majority"
 assuranceEvent("verify_invoked",map[string]interface{}{"history":history,"operation":op,"node":"A","new_leader":ids[next],"new_term":nodes[next].CurrentTerm(),"new_apply_index":newWrite.Index(),"old_term":nodes[0].CurrentTerm(),"old_state":nodes[0].State().String()})
 f:=nodes[0].VerifyLeader()
 err:=assuranceError(t,"target verification",f)
 errText:="";if err!=nil{errText=err.Error()}
 assuranceEvent("verify_result",map[string]interface{}{"history":history,"operation":op,"node":"A","success":err==nil,"error":errText,"old_state":nodes[0].State().String(),"old_fsm_count":len(fsms[0].Logs()),"new_fsm_count":len(fsms[next].Logs())})
}
