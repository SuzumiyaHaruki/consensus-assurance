package raft

import (
 "encoding/json"
 "fmt"
 "sync"
 "sync/atomic"
 "testing"
 "time"
 "github.com/hashicorp/go-hclog"
)

type assuranceOrderObserver struct { selected atomic.Bool; done chan struct{} }
type assuranceOrderFuture struct { AppendFuture; returned atomic.Bool; observer *assuranceOrderObserver }
func (f *assuranceOrderFuture) Error() error {
 err := f.AppendFuture.Error()
 f.returned.Store(true)
 return err
}
func assuranceOrderEvent(event string, data map[string]interface{}) {
 data["event"]=event
 data["history"]="pipeline-live-1"
 data["operation"]="first-observed-response"
 b,_:=json.Marshal(data)
 fmt.Println("CA_EVENT "+string(b))
}
func (f *assuranceOrderFuture) Response() *AppendEntriesResponse {
 observe:=f.observer.selected.CompareAndSwap(false,true)
 prior:=f.returned.Load()
 if observe {
  req:=f.AppendFuture.Request()
  assuranceOrderEvent("response_invoked",map[string]interface{}{"request_term":req.Term,"previous_index":req.PrevLogEntry,"entries":len(req.Entries),"error_returned_before_call":prior})
 }
 resp:=f.AppendFuture.Response()
 if observe {
  assuranceOrderEvent("response_returned",map[string]interface{}{"error_returned_before_call":prior,"response_term":resp.Term,"response_success":resp.Success})
  close(f.observer.done)
 }
 return resp
}
type assuranceOrderPipeline struct {
 AppendPipeline
 observer *assuranceOrderObserver
 mu sync.Mutex
 futures map[AppendFuture]*assuranceOrderFuture
 output chan AppendFuture
 stop chan struct{}
 once sync.Once
}
func (p *assuranceOrderPipeline) wrap(f AppendFuture) *assuranceOrderFuture {
 p.mu.Lock();defer p.mu.Unlock()
 if v,ok:=p.futures[f];ok{return v}
 v:=&assuranceOrderFuture{AppendFuture:f,observer:p.observer}
 p.futures[f]=v
 return v
}
func (p *assuranceOrderPipeline) AppendEntries(req *AppendEntriesRequest, resp *AppendEntriesResponse) (AppendFuture,error) {
 f,err:=p.AppendPipeline.AppendEntries(req,resp)
 if err!=nil{return nil,err}
 return p.wrap(f),nil
}
func (p *assuranceOrderPipeline) Consumer() <-chan AppendFuture {return p.output}
func (p *assuranceOrderPipeline) Close() error {
 p.once.Do(func(){close(p.stop)})
 return p.AppendPipeline.Close()
}
type assuranceOrderTransport struct { *InmemTransport; observer *assuranceOrderObserver }
func (t *assuranceOrderTransport) AppendEntriesPipeline(id ServerID, addr ServerAddress) (AppendPipeline,error) {
 inner,err:=t.InmemTransport.AppendEntriesPipeline(id,addr)
 if err!=nil{return nil,err}
 p:=&assuranceOrderPipeline{AppendPipeline:inner,observer:t.observer,futures:make(map[AppendFuture]*assuranceOrderFuture),output:make(chan AppendFuture),stop:make(chan struct{})}
 go func(){
  for {
   select {
   case f:=<-inner.Consumer():
    wrapped:=p.wrap(f)
    select {case p.output<-wrapped:case <-p.stop:return}
   case <-p.stop:return
   }
  }
 }()
 return p,nil
}
func assuranceOrderWait(t *testing.T, label string, f Future) {
 t.Helper()
 ch:=make(chan error,1)
 go func(){ch<-f.Error()}()
 select{case err:=<-ch:if err!=nil{t.Fatal(label,err)};case <-time.After(5*time.Second):t.Fatal("incomplete",label)}
}
func TestAssurancePipelineResponseOrder(t *testing.T) {
 observer:=&assuranceOrderObserver{done:make(chan struct{})}
 nodes:=make([]*Raft,2)
 transports:=make([]*assuranceOrderTransport,2)
 for i:=range nodes{
  addr:=ServerAddress(fmt.Sprintf("P%d",i))
  _,base:=NewInmemTransportWithTimeout(addr,200*time.Millisecond)
  transports[i]=&assuranceOrderTransport{InmemTransport:base,observer:observer}
 }
 transports[0].Connect("P1",transports[1].InmemTransport)
 transports[1].Connect("P0",transports[0].InmemTransport)
 defer func(){
  for _,n:=range nodes{if n!=nil{n.Shutdown()}}
  for _,n:=range nodes{if n!=nil{_ = n.Shutdown().Error()}}
  for _,tr:=range transports{_ = tr.Close()}
 }()
 for i:=range nodes{
  conf:=DefaultConfig()
  conf.LocalID=ServerID(fmt.Sprintf("P%d",i))
  conf.HeartbeatTimeout=200*time.Millisecond
  conf.ElectionTimeout=200*time.Millisecond
  conf.LeaderLeaseTimeout=100*time.Millisecond
  conf.CommitTimeout=10*time.Millisecond
  conf.Logger=hclog.NewNullLogger()
  store:=NewInmemStore()
  n,err:=NewRaft(conf,&MockFSM{},store,store,NewInmemSnapshotStore(),transports[i])
  if err!=nil{t.Fatal(err)}
  nodes[i]=n
 }
 assuranceOrderWait(t,"bootstrap",nodes[0].BootstrapCluster(Configuration{Servers:[]Server{{ID:"P0",Address:"P0",Suffrage:Voter}}}))
 deadline:=time.Now().Add(3*time.Second)
 for nodes[0].State()!=Leader && time.Now().Before(deadline){time.Sleep(5*time.Millisecond)}
 if nodes[0].State()!=Leader{t.Fatal("prefix incomplete: election")}
 assuranceOrderWait(t,"add voter",nodes[0].AddVoter("P1","P1",0,time.Second))
 assuranceOrderWait(t,"apply",nodes[0].Apply([]byte("pipeline-live-command"),time.Second))
 select{case <-observer.done:case <-time.After(3*time.Second):t.Fatal("incomplete: no actual Response call")}
 assuranceOrderEvent("driver_complete",map[string]interface{}{"apply_completed":true})
}
