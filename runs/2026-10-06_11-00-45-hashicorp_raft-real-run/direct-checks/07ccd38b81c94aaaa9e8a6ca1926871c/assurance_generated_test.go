package raft

import (
 "encoding/json"
 "fmt"
 "io"
 "sync"
 "testing"
 "time"
)

type assuranceVerifyTransport struct {
 *InmemTransport
 mu sync.Mutex
 blocked map[ServerID]bool
 positive map[ServerID]int
 denied map[ServerID]int
}
func (a *assuranceVerifyTransport) AppendEntries(id ServerID, addr ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
 a.mu.Lock()
 blocked := a.blocked[id]
 if blocked { a.denied[id]++ }
 a.mu.Unlock()
 if blocked { return fmt.Errorf("controlled unavailable voter %s", id) }
 err := a.InmemTransport.AppendEntries(id, addr, req, resp)
 if err == nil && resp.Success { a.mu.Lock(); a.positive[id]++; a.mu.Unlock() }
 return err
}
func (a *assuranceVerifyTransport) AppendEntriesPipeline(id ServerID, addr ServerAddress) (AppendPipeline,error) {
 return nil, ErrPipelineReplicationNotSupported
}
func assuranceVerifyEvent(v map[string]interface{}) {
 b, _ := json.Marshal(v)
 fmt.Println("CA_EVENT " + string(b))
}
func TestAssuranceVerifyNonvoterEligibility(t *testing.T) {
 ids := []ServerID{"a", "b", "c", "n"}
 membership := Configuration{}
 for i,id := range ids { suffrage:=Voter; if i==3 { suffrage=Nonvoter }; membership.Servers=append(membership.Servers,Server{ID:id,Address:ServerAddress(id),Suffrage:suffrage}) }
 nodes:=make([]*Raft,4)
 transports:=make([]*InmemTransport,4)
 var outbound *assuranceVerifyTransport
 for i,id:=range ids {
  _,tr:=NewInmemTransport(ServerAddress(id));transports[i]=tr
  cfg:=DefaultConfig();cfg.LocalID=id;cfg.skipStartup=true;cfg.PreVoteDisabled=true
  cfg.HeartbeatTimeout=5*time.Second;cfg.ElectionTimeout=5*time.Second;cfg.LeaderLeaseTimeout=5*time.Second;cfg.LogOutput=io.Discard
  store:=NewInmemStore();snaps:=NewInmemSnapshotStore()
  var transport Transport=tr
  if i==0 { outbound=&assuranceVerifyTransport{InmemTransport:tr,blocked:map[ServerID]bool{},positive:map[ServerID]int{},denied:map[ServerID]int{}};transport=outbound }
  if i==0 {if err:=BootstrapCluster(cfg,store,store,snaps,transport,membership);err!=nil {t.Fatal(err)}}
  initialIndex,err:=store.LastIndex();if err!=nil {t.Fatal(err)}
  if i==0 && initialIndex!=1 {t.Fatalf("bootstrap index: %d",initialIndex)}
  if i!=0 && initialIndex!=0 {t.Fatalf("joining node must start empty: %d",initialIndex)}
  r,err:=NewRaft(cfg,&MockFSM{},store,store,snaps,transport);if err!=nil {t.Fatal(err)};nodes[i]=r
 }
 for i,tr:=range transports { for j,peer:=range transports {if i!=j {tr.Connect(ServerAddress(ids[j]),peer)}} }
 stop:=make(chan struct{});var pumps sync.WaitGroup
 // Serialize each follower's real handlers; election timers are not run during this bounded schedule.
 for i:=1;i<4;i++ {r:=nodes[i];pumps.Add(1);go func(){defer pumps.Done();for {select {case rpc:=<-r.rpcCh:r.processRPC(rpc);case <-stop:return}}}()}
 defer func(){for _,r:=range nodes {if err:=r.Shutdown().Error();err!=nil {t.Error(err)}};close(stop);pumps.Wait();for _,tr:=range transports {tr.Close()}}()
 leader:=nodes[0]
 leader.setState(Candidate)
 leader.runCandidate()
 if leader.State()!=Leader {t.Fatalf("election not won: %v",leader.State())}
 // No replication goroutine has started, hence there are no earlier append replies to drain.
 outbound.mu.Lock();outbound.blocked["b"]=true;outbound.blocked["c"]=true;outbound.mu.Unlock()
 assuranceVerifyEvent(map[string]interface{}{"event":"prepared","operation":"verify-1","term":leader.CurrentTerm(),"state":leader.State().String(),"voters":3,"nonvoters":1,"policy":"only_nonvoter_append_replies","replication_started":false,"bootstrap_nodes":1,"empty_joining_nodes":3})
 leader.goFunc(leader.runLeader)
 future:=leader.VerifyLeader()
 assuranceVerifyEvent(map[string]interface{}{"event":"admitted","operation":"verify-1","policy":"only_nonvoter_append_replies"})
 done:=make(chan error,1);go func(){done<-future.Error()}()
 select {
 case err:=<-done:
  outbound.mu.Lock();positive:=map[ServerID]int{};denied:=map[ServerID]int{};for id,n:=range outbound.positive {positive[id]=n};for id,n:=range outbound.denied {denied[id]=n};outbound.mu.Unlock()
  errText:="";if err!=nil {errText=err.Error()}
  eligible:=1;totalVoters:=0
  for _,server:=range membership.Servers {if server.Suffrage==Voter {totalVoters++;if server.ID!=leader.localID && positive[server.ID]>0 {eligible++}}}
  quorum:=totalVoters/2+1
  assuranceVerifyEvent(map[string]interface{}{"event":"result","operation":"verify-1","success":err==nil,"completed":true,"eligible_voter_quorum":eligible>=quorum,"eligible_voter_support":eligible,"quorum":quorum,"error":errText,"positive_append_responses":positive,"blocked_calls":denied,"state":leader.State().String(),"term":leader.CurrentTerm()})
 case <-time.After(2*time.Second):
  assuranceVerifyEvent(map[string]interface{}{"event":"bounded_pending","operation":"verify-1"})
  leader.Shutdown()
  select {case <-done:case <-time.After(time.Second):t.Fatal("verification waiter did not exit after shutdown")}
 }
}
