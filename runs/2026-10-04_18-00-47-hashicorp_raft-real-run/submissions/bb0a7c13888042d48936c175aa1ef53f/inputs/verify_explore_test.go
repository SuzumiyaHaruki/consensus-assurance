package raft

import (
 "bytes"
 "encoding/json"
 "fmt"
 "io"
 "sync"
 "testing"
 "time"
)

// The network only drops cross-partition calls and responses. It never creates
// replies. Pipeline fallback is selected through the supported transport error.
type assuranceNet struct {
 mu sync.Mutex
 cut bool
 seen map[string]bool
 successes map[string]int
}
func (n *assuranceNet) blocked(from, to ServerID) bool {
 return n.cut && ((from == "a" || from == "n") != (to == "a" || to == "n"))
}
type assuranceTransport struct {
 *InmemTransport
 id ServerID
 net *assuranceNet
}
func (s *assuranceTransport) before(to ServerID, lane string) error {
 s.net.mu.Lock()
 defer s.net.mu.Unlock()
 if s.net.blocked(s.id,to) {
  if s.id == "a" { s.net.seen[string(to)+"/"+lane] = true }
  return fmt.Errorf("selected partition")
 }
 return nil
}
func (s *assuranceTransport) after(to ServerID, err error, success bool) error {
 s.net.mu.Lock()
 defer s.net.mu.Unlock()
 if s.net.blocked(s.id,to) {return fmt.Errorf("selected partition response drop")}
 if err == nil && success {s.net.successes[string(s.id)+"/"+string(to)]++}
 return err
}
func (s *assuranceTransport) AppendEntriesPipeline(ServerID, ServerAddress) (AppendPipeline,error) {
 return nil, ErrPipelineReplicationNotSupported
}
func (s *assuranceTransport) AppendEntries(id ServerID, addr ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
 lane := "append"
 if req.PrevLogEntry == 0 && req.PrevLogTerm == 0 && len(req.Entries)==0 && req.LeaderCommitIndex==0 {lane="heartbeat"}
 if err:=s.before(id,lane); err!=nil {return err}
 err:=s.InmemTransport.AppendEntries(id,addr,req,resp)
 return s.after(id,err,resp.Success)
}
func (s *assuranceTransport) RequestVote(id ServerID, addr ServerAddress, req *RequestVoteRequest, resp *RequestVoteResponse) error {
 if err:=s.before(id,"vote");err!=nil{return err}
 err:=s.InmemTransport.RequestVote(id,addr,req,resp)
 return s.after(id,err,false)
}
func (s *assuranceTransport) RequestPreVote(id ServerID, addr ServerAddress, req *RequestPreVoteRequest, resp *RequestPreVoteResponse) error {
 if err:=s.before(id,"prevote");err!=nil{return err}
 err:=s.InmemTransport.RequestPreVote(id,addr,req,resp)
 return s.after(id,err,false)
}
func (s *assuranceTransport) InstallSnapshot(id ServerID, addr ServerAddress, req *InstallSnapshotRequest, resp *InstallSnapshotResponse, reader io.Reader) error {
 if err:=s.before(id,"snapshot");err!=nil{return err}
 err:=s.InmemTransport.InstallSnapshot(id,addr,req,resp,reader)
 return s.after(id,err,resp.Success)
}
func (s *assuranceTransport) TimeoutNow(id ServerID, addr ServerAddress, req *TimeoutNowRequest, resp *TimeoutNowResponse) error {
 if err:=s.before(id,"transfer");err!=nil{return err}
 err:=s.InmemTransport.TimeoutNow(id,addr,req,resp)
 return s.after(id,err,false)
}
type assuranceFSM struct {mu sync.Mutex; value string; index uint64}
func (f *assuranceFSM) Apply(l *Log) interface{} {
 f.mu.Lock();defer f.mu.Unlock();f.value=string(l.Data);f.index=l.Index;return f.value
}
func (f *assuranceFSM) read() (string,uint64) {f.mu.Lock();defer f.mu.Unlock();return f.value,f.index}
func (f *assuranceFSM) Snapshot() (FSMSnapshot,error) {v,_:=f.read();return assuranceSnap(v),nil}
func (f *assuranceFSM) Restore(r io.ReadCloser) error {
 b,err:=io.ReadAll(r);if err!=nil{return err};f.mu.Lock();f.value=string(b);f.mu.Unlock();return nil
}
type assuranceSnap string
func (s assuranceSnap) Persist(w SnapshotSink) error {
 if _,err:=io.Copy(w,bytes.NewBufferString(string(s)));err!=nil{w.Cancel();return err};return w.Close()
}
func (s assuranceSnap) Release(){}
func assuranceEvent(event string, fields map[string]interface{}) {
 fields["event"]=event;fields["operation"]="verify-after-successor-write"
 b,err:=json.Marshal(fields);if err!=nil{panic(err)};fmt.Println("CA_EVENT "+string(b))
}
func assuranceWait(t *testing.T, label string, d time.Duration, pred func()bool) {
 t.Helper();end:=time.Now().Add(d)
 for time.Now().Before(end){if pred(){return};time.Sleep(5*time.Millisecond)}
 t.Fatalf("prerequisite not reached: %s",label)
}
func assuranceFuture(t *testing.T,label string,f Future) {
 t.Helper();done:=make(chan error,1);go func(){done<-f.Error()}()
 select{case err:=<-done:if err!=nil{t.Fatalf("%s: %v",label,err)};case <-time.After(4*time.Second):t.Fatalf("prerequisite future incomplete: %s",label)}
}
func TestAssuranceVerifyAfterSuccessorWrite(t *testing.T) {
 ids:=[]ServerID{"a","b","c","n"}
 net:=&assuranceNet{seen:make(map[string]bool),successes:make(map[string]int)}
 transports:=make(map[ServerID]*assuranceTransport)
 nodes:=make(map[ServerID]*Raft)
 fsms:=make(map[ServerID]*assuranceFSM)
 for _,id:=range ids {
  _,base:=NewInmemTransportWithTimeout(ServerAddress(id),100*time.Millisecond)
  transports[id]=&assuranceTransport{base,id,net}
 }
 for _,id:=range ids{for _,other:=range ids{if other!=id{transports[id].Connect(ServerAddress(other),transports[other].InmemTransport)}}}
 defer func(){
  futures:=[]Future{}
  for _,id:=range ids{if r:=nodes[id];r!=nil{futures=append(futures,r.Shutdown())}}
  for _,f:=range futures{if err:=f.Error();err!=nil{t.Errorf("shutdown: %v",err)}}
 }()
 for _,id:=range ids {
  cfg:=DefaultConfig();cfg.LocalID=id;cfg.LogOutput=io.Discard
  cfg.HeartbeatTimeout=250*time.Millisecond;cfg.ElectionTimeout=250*time.Millisecond;cfg.LeaderLeaseTimeout=100*time.Millisecond
  cfg.CommitTimeout=10*time.Millisecond
  if id=="a"{cfg.HeartbeatTimeout=3*time.Second;cfg.ElectionTimeout=3*time.Second;cfg.LeaderLeaseTimeout=3*time.Second}
  store:=NewInmemStore();snaps:=NewInmemSnapshotStore();fsm:=&assuranceFSM{};fsms[id]=fsm
  if id=="a"{if err:=BootstrapCluster(cfg,store,store,snaps,transports[id],Configuration{Servers:[]Server{{Suffrage:Voter,ID:id,Address:ServerAddress(id)}}});err!=nil{t.Fatal(err)}}
  r,err:=NewRaft(cfg,fsm,store,store,snaps,transports[id]);if err!=nil{t.Fatal(err)};nodes[id]=r
 }
 a:=nodes["a"]
 assuranceWait(t,"initial single-voter election",8*time.Second,func()bool{return a.State()==Leader})
 for _,id:=range []ServerID{"b","c"}{assuranceFuture(t,"add voter "+string(id),a.AddVoter(id,ServerAddress(id),0,time.Second))}
 assuranceFuture(t,"add nonvoter",a.AddNonvoter("n","n",0,time.Second))
 baseline:=a.Apply([]byte("before"),time.Second);assuranceFuture(t,"baseline write",baseline)
 assuranceWait(t,"all FSMs apply baseline",2*time.Second,func()bool{for _,id:=range ids{v,_:=fsms[id].read();if v!="before"{return false}};return true})
 configs:=map[string]interface{}{}
 for _,id:=range ids {
  cf:=nodes[id].GetConfiguration();assuranceFuture(t,"read configuration",cf)
  cc:=cf.Configuration();if len(cc.Servers)!=4{t.Fatalf("unexpected configuration on %s: %+v",id,cc)}
  for _,server:=range cc.Servers{expected:=Voter;if server.ID=="n"{expected=Nonvoter};if server.Suffrage!=expected{t.Fatalf("wrong suffrage on %s",id)}}
  configs[string(id)]=cf.Index()
 }
 assuranceEvent("cluster_ready",map[string]interface{}{"leader":"a","term":a.CurrentTerm(),"baseline_index":baseline.Index(),"configuration_indexes":configs,"voters":3,"nonvoters":1})
 net.mu.Lock();net.cut=true;net.mu.Unlock()
 cutAt:=time.Now()
 // Each of the two producers for each remote voter must enter its next call
 // after the cut. With pipelining disabled, previous notifyAll on that same
 // producer has finished before this next call begins.
 assuranceWait(t,"old voter reply producers cross cut",2*time.Second,func()bool{
  net.mu.Lock();defer net.mu.Unlock()
  return net.seen["b/append"]&&net.seen["b/heartbeat"]&&net.seen["c/append"]&&net.seen["c/heartbeat"]
 })
 assuranceEvent("partition_producers_drained",map[string]interface{}{"elapsed_ms":time.Since(cutAt).Milliseconds(),"old_role":a.State().String()})
 var successor *Raft;var successorID ServerID
 assuranceWait(t,"successor election",2*time.Second,func()bool{for _,id:=range []ServerID{"b","c"}{if nodes[id].State()==Leader{successor=nodes[id];successorID=id;return true}};return false})
 fresh:=successor.Apply([]byte("after"),time.Second);assuranceFuture(t,"successor write",fresh)
 newValue,newIndex:=fsms[successorID].read()
 oldValue,oldIndex:=fsms["a"].read()
 assuranceEvent("successor_write_complete",map[string]interface{}{"successor":string(successorID),"successor_term":successor.CurrentTerm(),"old_term":a.CurrentTerm(),"write_index":fresh.Index(),"new_value":newValue,"new_index":newIndex,"old_value":oldValue,"old_index":oldIndex,"elapsed_ms":time.Since(cutAt).Milliseconds()})
 // Observe, do not force, the authority state at invocation.
 net.mu.Lock();beforeN:=net.successes["a/n"];beforeB:=net.successes["a/b"];beforeC:=net.successes["a/c"];net.mu.Unlock()
 assuranceEvent("verify_invoked",map[string]interface{}{"old_role":a.State().String(),"old_term":a.CurrentTerm(),"successor_term":successor.CurrentTerm(),"elapsed_ms":time.Since(cutAt).Milliseconds()})
 vf:=a.VerifyLeader();done:=make(chan error,1);go func(){done<-vf.Error()}()
 select {
 case err:=<-done:
  observed,index:=fsms["a"].read()
  net.mu.Lock();nDelta:=net.successes["a/n"]-beforeN;bDelta:=net.successes["a/b"]-beforeB;cDelta:=net.successes["a/c"]-beforeC;net.mu.Unlock()
  errText:="";if err!=nil{errText=err.Error()}
  assuranceEvent("verify_completed",map[string]interface{}{"success":err==nil,"error":errText,"old_role":a.State().String(),"old_term":a.CurrentTerm(),"observed_value":observed,"observed_index":index,"expected_value":newValue,"nonvoter_successes":nDelta,"voter_b_successes":bDelta,"voter_c_successes":cDelta,"elapsed_ms":time.Since(cutAt).Milliseconds()})
 case <-time.After(time.Second):
  assuranceEvent("verify_incomplete",map[string]interface{}{"elapsed_ms":time.Since(cutAt).Milliseconds(),"old_role":a.State().String()})
 }
}
