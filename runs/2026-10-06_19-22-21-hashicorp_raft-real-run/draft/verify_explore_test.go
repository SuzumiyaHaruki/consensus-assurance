package raft

import (
 "encoding/json"
 "fmt"
 "io"
 "sync"
 "sync/atomic"
 "testing"
 "time"
)

type assuranceVerifyFSM struct { mu sync.Mutex; values []string }
func (f *assuranceVerifyFSM) Apply(l *Log) interface{} { f.mu.Lock(); defer f.mu.Unlock(); f.values=append(f.values,string(l.Data)); return string(l.Data) }
func (f *assuranceVerifyFSM) Snapshot() (FSMSnapshot,error) { return nil,fmt.Errorf("snapshot unused in this bounded exploration") }
func (f *assuranceVerifyFSM) Restore(r io.ReadCloser) error { defer r.Close(); return fmt.Errorf("restore unused") }
func (f *assuranceVerifyFSM) has(v string) bool { f.mu.Lock(); defer f.mu.Unlock(); for _,s:=range f.values { if s==v{return true} };return false }
type assuranceVerifyTransport struct { *InmemTransport; phase atomic.Int32; mu sync.Mutex; successes map[ServerID]int }
func (x *assuranceVerifyTransport) AppendEntriesPipeline(ServerID,ServerAddress)(AppendPipeline,error){return nil,ErrPipelineReplicationNotSupported}
func (x *assuranceVerifyTransport) AppendEntries(id ServerID,a ServerAddress,q *AppendEntriesRequest,r *AppendEntriesResponse) error {
 err:=x.InmemTransport.AppendEntries(id,a,q,r)
 if x.phase.Load()==2 && err==nil && r.Success { x.mu.Lock();x.successes[id]++;x.mu.Unlock() }
 return err
}
func assuranceVerifyEvent(m map[string]interface{}) { b,_:=json.Marshal(m);fmt.Println("CA_EVENT "+string(b)) }
func assuranceVerifyWait(t *testing.T,label string,d time.Duration,p func()bool) {
 t.Helper(); deadline:=time.Now().Add(d);for time.Now().Before(deadline){if p(){return};time.Sleep(5*time.Millisecond)};t.Fatalf("unreached prerequisite: %s",label)
}
func assuranceVerifyFuture(t *testing.T,label string,f Future,d time.Duration) error {
 t.Helper();ch:=make(chan error,1);go func(){ch<-f.Error()}();select{case e:=<-ch:return e;case <-time.After(d):t.Fatalf("future did not complete: %s",label);return fmt.Errorf("timeout")}
}
func TestAssuranceVerifyNonvoterExplore(t *testing.T) {
 ids:=[]ServerID{"old","v1","v2","nonvoter"}
 rs:=make([]*Raft,4);fs:=make([]*assuranceVerifyFSM,4);ts:=make([]*assuranceVerifyTransport,4)
 for i,id:=range ids { _,tr:=NewInmemTransportWithTimeout(ServerAddress(id),100*time.Millisecond);ts[i]=&assuranceVerifyTransport{InmemTransport:tr,successes:make(map[ServerID]int)} }
 for i:=range ts { for j:=range ts { if i!=j { ts[i].Connect(ServerAddress(ids[j]),ts[j].InmemTransport) } } }
 defer func(){for _,r:=range rs{if r!=nil{r.Shutdown()}};for _,r:=range rs{if r!=nil{r.Shutdown().Error()}};for _,tr:=range ts{tr.Close()}}()
 for i,id:=range ids {
  c:=DefaultConfig();c.LocalID=id;c.LogOutput=io.Discard;c.CommitTimeout=10*time.Millisecond;c.SnapshotInterval=time.Hour
  c.HeartbeatTimeout=100*time.Millisecond;c.ElectionTimeout=100*time.Millisecond;c.LeaderLeaseTimeout=100*time.Millisecond
  if i==0 {c.HeartbeatTimeout=2*time.Second;c.ElectionTimeout=2*time.Second;c.LeaderLeaseTimeout=2*time.Second}
  st:=NewInmemStore();sn:=NewInmemSnapshotStore();fs[i]=&assuranceVerifyFSM{}
  if i==0 {if e:=BootstrapCluster(c,st,st,sn,ts[i],Configuration{Servers:[]Server{{ID:id,Address:ServerAddress(id),Suffrage:Voter}}});e!=nil{t.Fatal(e)}}
  var e error;rs[i],e=NewRaft(c,fs[i],st,st,sn,ts[i]);if e!=nil{t.Fatal(e)}
 }
 assuranceVerifyWait(t,"initial leader",6*time.Second,func()bool{return rs[0].State()==Leader})
 for i:=1;i<4;i++ {var f IndexFuture;if i==3{f=rs[0].AddNonvoter(ids[i],ServerAddress(ids[i]),0,time.Second)}else{f=rs[0].AddVoter(ids[i],ServerAddress(ids[i]),0,time.Second)};if e:=assuranceVerifyFuture(t,"membership",f,2*time.Second);e!=nil{t.Fatal(e)}}
 if e:=assuranceVerifyFuture(t,"prefix apply",rs[0].Apply([]byte("prefix"),time.Second),2*time.Second);e!=nil{t.Fatal(e)}
 assuranceVerifyWait(t,"prefix applied at every node",2*time.Second,func()bool{for _,f:=range fs{if !f.has("prefix"){return false}};return true})
 oldTerm:=rs[0].CurrentTerm()
 assuranceVerifyEvent(map[string]interface{}{"stage":"prefix","old_term":oldTerm,"nodes":4,"voters":3,"nonvoters":1})
 // Partition the old leader and nonvoter from the other two voters. Existing RPCs are not rewritten.
 for _,a:=range []int{0,3}{for _,b:=range []int{1,2}{ts[a].Disconnect(ServerAddress(ids[b]));ts[b].Disconnect(ServerAddress(ids[a]))}}
 partitionAt:=time.Now()
 assuranceVerifyEvent(map[string]interface{}{"stage":"partition","old_term":oldTerm})
 newIdx:=-1
 assuranceVerifyWait(t,"replacement leader",1500*time.Millisecond,func()bool{for _,i:=range []int{1,2}{if rs[i].State()==Leader{newIdx=i;return true}};return false})
 af:=rs[newIdx].Apply([]byte("new-decision"),time.Second)
 if e:=assuranceVerifyFuture(t,"new decision",af,time.Second);e!=nil{t.Fatal(e)}
 assuranceVerifyWait(t,"new decision on voting majority",time.Second,func()bool{return fs[1].has("new-decision")&&fs[2].has("new-decision")})
 assuranceVerifyEvent(map[string]interface{}{"stage":"new_decision","new_leader":ids[newIdx],"new_term":rs[newIdx].CurrentTerm(),"old_term":oldTerm,"index":af.Index(),"elapsed_ms":time.Since(partitionAt).Milliseconds()})
 ts[0].phase.Store(2)
 assuranceVerifyEvent(map[string]interface{}{"stage":"verify_admission","operation":"verify-old-1","old_role":rs[0].State().String(),"old_term":rs[0].CurrentTerm(),"new_term":rs[newIdx].CurrentTerm(),"old_has_new":fs[0].has("new-decision")})
 vf:=rs[0].VerifyLeader();err:=assuranceVerifyFuture(t,"verify",vf,3*time.Second)
 ts[0].mu.Lock();counts:=make(map[ServerID]int);for k,v:=range ts[0].successes{counts[k]=v};ts[0].mu.Unlock()
 errText:="";if err!=nil{errText=err.Error()}
 assuranceVerifyEvent(map[string]interface{}{"stage":"verify_result","operation":"verify-old-1","success":err==nil,"error":errText,"old_role":rs[0].State().String(),"old_has_new":fs[0].has("new-decision"),"new_has_new":fs[newIdx].has("new-decision"),"success_replies_during_window":counts,"elapsed_ms":time.Since(partitionAt).Milliseconds()})
}
