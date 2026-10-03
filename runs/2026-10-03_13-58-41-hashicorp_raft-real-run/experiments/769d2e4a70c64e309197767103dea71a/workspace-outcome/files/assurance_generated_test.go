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

type assuranceFailCandidate struct { *InmemStore; armed bool; failures int }
func (s *assuranceFailCandidate) Set(k, v []byte) error {
 if s.armed && bytes.Equal(k, keyLastVoteCand) { s.armed=false; s.failures++; return fmt.Errorf("injected candidate write failure") }
 return s.InmemStore.Set(k,v)
}
type assuranceVoteRecord struct { candidate ServerID; term uint64; granted bool }
type assuranceVoteNetwork struct {
 sync.Mutex
 nodes map[ServerID]*Raft
 blocked map[string]bool
 history []assuranceVoteRecord
 final bool
 operation string
}
type assuranceVoteTransport struct { *InmemTransport; id ServerID; net *assuranceVoteNetwork }
func assuranceVoteEmit(e map[string]interface{}) { b,err:=json.Marshal(e);if err!=nil {panic(err)};fmt.Println("CA_EVENT "+string(b)) }
func (x *assuranceVoteTransport) RequestVote(id ServerID, addr ServerAddress, req *RequestVoteRequest, resp *RequestVoteResponse) error {
 x.net.Lock()
 blocked:=x.net.blocked[string(x.id)+":"+string(id)]
 node:=x.net.nodes[id]
 final:=x.net.final && x.id=="a" && id=="v"
 prior:=false
 for _,h:=range x.net.history { if h.term==req.Term && h.candidate==x.id && h.granted {prior=true} }
 x.net.Unlock()
 if blocked { return fmt.Errorf("scheduled message omission") }
 if final {
  idx,term:=node.getLastEntry()
  stale:=req.LastLogTerm<term || (req.LastLogTerm==term && req.LastLogIndex<idx)
  assuranceVoteEmit(map[string]interface{}{"event":"vote_admitted","operation":x.net.operation,"request_term":req.Term,"candidate":string(x.id),"candidate_index":req.LastLogIndex,"candidate_log_term":req.LastLogTerm,"receiver_index":idx,"receiver_log_term":term,"candidate_stale":stale,"prior_same_term_grant":prior})
 }
 ch:=make(chan RPCResponse,1)
 node.processRPC(RPC{Command:req,RespChan:ch})
 result:=<-ch
 if result.Error!=nil {return result.Error}
 *resp=*(result.Response.(*RequestVoteResponse))
 if id=="v" { x.net.Lock(); x.net.history=append(x.net.history,assuranceVoteRecord{x.id,req.Term,resp.Granted}); x.net.Unlock() }
 if final {
  vt,_:=node.stable.GetUint64(keyLastVoteTerm);vc,_:=node.stable.Get(keyLastVoteCand)
  assuranceVoteEmit(map[string]interface{}{"event":"vote_result","operation":x.net.operation,"granted":resp.Granted,"response_term":resp.Term,"stored_vote_term":vt,"stored_candidate":string(vc),"rpc_completed":true})
 }
 return nil
}
func (x *assuranceVoteTransport) AppendEntries(id ServerID, addr ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
 ch:=make(chan RPCResponse,1);x.net.nodes[id].processRPC(RPC{Command:req,RespChan:ch});v:=<-ch
 if v.Error!=nil{return v.Error};*resp=*(v.Response.(*AppendEntriesResponse));return nil
}
func assuranceCampaign(t *testing.T,r *Raft) int {
 t.Helper();r.setState(Candidate);ch:=r.electSelf();grants:=0
 for i:=0;i<3;i++ { select {case v:=<-ch:if v.Granted {grants++};case <-time.After(time.Second):t.Fatal("campaign response missing")} }
 return grants
}
func TestAssurancePartialVotePair(t *testing.T) {
 for _,fault:=range []bool{false,true} {
  name:="successful_write_control";if fault{name="failed_candidate_write"}
  t.Run(name,func(t *testing.T){
   cfgs:=Configuration{Servers:[]Server{{ID:"a",Address:"a",Suffrage:Voter},{ID:"b",Address:"b",Suffrage:Voter},{ID:"v",Address:"v",Suffrage:Voter}}}
   net:=&assuranceVoteNetwork{nodes:map[ServerID]*Raft{},blocked:map[string]bool{},operation:name}
   var receiverStore *assuranceFailCandidate
   for _,server:=range cfgs.Servers {
    cfg:=DefaultConfig();cfg.LocalID=server.ID;cfg.ProtocolVersion=3;cfg.PreVoteDisabled=true;cfg.skipStartup=true;cfg.LogOutput=io.Discard
    _,base:=NewInmemTransport(server.Address);tr:=&assuranceVoteTransport{base,server.ID,net}
    store:=NewInmemStore();stable:=&assuranceFailCandidate{InmemStore:store};if server.ID=="v"{receiverStore=stable}
    snaps:=NewInmemSnapshotStore();if err:=BootstrapCluster(cfg,store,stable,snaps,tr,cfgs);err!=nil{t.Fatal(err)}
    r,err:=NewRaft(cfg,&MockFSM{},store,stable,snaps,tr);if err!=nil{t.Fatal(err)};net.nodes[server.ID]=r
   }
   defer func(){for _,r:=range net.nodes{r.Shutdown().Error()}}()
   a,b,v:=net.nodes["a"],net.nodes["b"],net.nodes["v"]
   // A's term-2 campaign executes real grants. Delay its main-loop tally;
   // B's later term-3 campaign can arrive while A is still a candidate.
   if assuranceCampaign(t,a)!=3 {t.Fatal("initial campaign grants missing")}
   net.blocked["b:v"]=true
   if assuranceCampaign(t,b)!=2 {t.Fatal("B did not get A+self majority")}
   b.setState(Leader);b.setLeader(b.localAddr,b.localID);b.setupLeaderState()
   // Prepare the same initial replication state as a new leader, before noop.
   repl:=&followerReplication{lastContact:time.Now(),peer:cfgs.Servers[2],commitment:b.leaderState.commitment,currentTerm:b.getCurrentTerm(),nextIndex:b.getLastIndex()+1,stopCh:make(chan uint64,1),triggerCh:make(chan struct{},1),notify:map[*verifyFuture]struct{}{},stepDown:b.leaderState.stepDown}
   b.leaderState.replState["v"]=repl
   b.leaderState.replState["a"]=&followerReplication{peer:cfgs.Servers[0],lastContact:time.Now(),triggerCh:make(chan struct{},1)}
   noop:=&logFuture{log:Log{Type:LogNoop}};noop.init();b.dispatchLogs([]*logFuture{noop})
   if b.replicateTo(repl,b.getLastIndex()){t.Fatal("replication stopped")}
   // V learns term-3 history through AppendEntries, without voting for B.
   vi,vt:=v.getLastEntry();ai,at:=a.getLastEntry()
   oldTerm,_:=receiverStore.GetUint64(keyLastVoteTerm);oldCand,_:=receiverStore.Get(keyLastVoteCand)
   if oldTerm!=2 || string(oldCand)!="a" || !(vt>at || (vt==at && vi>ai)) {t.Fatal("prefix did not establish old vote and newer receiver log")}
   // Let contacts expire, execute the real lease check, then the real follower
   // timeout path. No peers respond during this scheduled interval.
   time.Sleep(b.config().LeaderLeaseTimeout+10*time.Millisecond)
   b.checkLeaderLease()
   if b.getState()!=Follower {t.Fatal("lease did not remove leader authority")}
   b.setLastContact() // runLeader exit performs this update before follower loop.
   b.runFollower()
   if b.getState()!=Candidate {t.Fatal("follower timeout did not start campaign")}
   net.blocked["b:v"]=false;net.blocked["b:a"]=true
   receiverStore.armed=fault
   grants:=assuranceCampaign(t,b)
   bGranted:=grants==2
   pairTerm,_:=receiverStore.GetUint64(keyLastVoteTerm);pairCand,_:=receiverStore.Get(keyLastVoteCand)
   assuranceVoteEmit(map[string]interface{}{"event":"vote_prefix","operation":name,"old_vote_term":oldTerm,"old_candidate":string(oldCand),"receiver_index":vi,"receiver_log_term":vt,"stale_index":ai,"stale_log_term":at,"intervening_granted":bGranted,"write_failures":receiverStore.failures,"pair_term":pairTerm,"pair_candidate":string(pairCand)})
   // A learned term 3 when it granted B's prior election, but missed B's
   // new log. Its own electSelf therefore produces a real stale term-4 RPC.
   net.blocked["a:b"]=true;net.final=true
   assuranceCampaign(t,a)
  })
 }
}
