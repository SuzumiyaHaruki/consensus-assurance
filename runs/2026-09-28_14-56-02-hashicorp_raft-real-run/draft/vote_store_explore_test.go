package raft

import (
 "bytes"
 "encoding/json"
 "fmt"
 "testing"
 "github.com/hashicorp/go-hclog"
)

type assuranceVoteStore struct { *InmemStore; failCandidate bool; failures int }
func (s *assuranceVoteStore) Set(key, value []byte) error {
 if s.failCandidate && bytes.Equal(key,keyLastVoteCand) {
  s.failCandidate=false
  s.failures++
  return fmt.Errorf("injected candidate write failure before mutation")
 }
 return s.InmemStore.Set(key,value)
}
func TestAssuranceVoteStorePairExplore(t *testing.T) {
 for _,fault:=range []bool{false,true}{
  conf:=DefaultConfig();conf.LocalID="F";conf.skipStartup=true;conf.Logger=hclog.NewNullLogger()
  _,tr:=NewInmemTransport("F")
  store:=&assuranceVoteStore{InmemStore:NewInmemStore()}
  snaps:=NewInmemSnapshotStore()
  config:=Configuration{Servers:[]Server{{ID:"F",Address:"F",Suffrage:Voter},{ID:"A",Address:"A",Suffrage:Voter},{ID:"B",Address:"B",Suffrage:Voter}}}
  if err:=BootstrapCluster(conf,store,store,snaps,tr,config);err!=nil{t.Fatal(err)}
  r,err:=NewRaft(conf,&MockFSM{},store,store,snaps,tr);if err!=nil{t.Fatal(err)}
  vote:=func(id string,term,index,logterm uint64)*RequestVoteResponse{
   ch:=make(chan RPCResponse,1)
   req:=&RequestVoteRequest{RPCHeader:RPCHeader{ProtocolVersion:conf.ProtocolVersion,ID:[]byte(id),Addr:[]byte(id)},Term:term,LastLogIndex:index,LastLogTerm:logterm}
   r.processRPC(RPC{Command:req,RespChan:ch})
   out:=<-ch;if out.Error!=nil{t.Fatal(out.Error)}
   return out.Response.(*RequestVoteResponse)
  }
  first:=vote("A",2,1,1)
  if !first.Granted{t.Fatal("initial vote not reached")}
  ch:=make(chan RPCResponse,1)
  appendReq:=&AppendEntriesRequest{RPCHeader:RPCHeader{ProtocolVersion:conf.ProtocolVersion,ID:[]byte("B"),Addr:[]byte("B")},Term:3,PrevLogEntry:1,PrevLogTerm:1,Entries:[]*Log{{Index:2,Term:3,Type:LogCommand,Data:[]byte("later-history")}}}
  r.processRPC(RPC{Command:appendReq,RespChan:ch})
  appendOut:=<-ch
  if appendOut.Error!=nil || !appendOut.Response.(*AppendEntriesResponse).Success{t.Fatal("append prefix failed",appendOut)}
  store.failCandidate=fault
  next:=vote("B",4,2,3)
  savedTerm,_:=store.GetUint64(keyLastVoteTerm)
  savedCandidate,_:=store.Get(keyLastVoteCand)
  retry:=vote("A",4,1,1)
  localIndex,localTerm:=r.getLastEntry()
  fields:=map[string]interface{}{"event":"vote_pair_result","fault":fault,"first_granted":first.Granted,"next_granted":next.Granted,"saved_vote_term":savedTerm,"saved_candidate":string(savedCandidate),"retry_granted":retry.Granted,"retry_term":retry.Term,"local_index":localIndex,"local_log_term":localTerm,"request_index":1,"request_log_term":1,"injected_failures":store.failures}
  data,_:=json.Marshal(fields);fmt.Println("CA_EVENT "+string(data))
  _=r.Shutdown().Error();_=tr.Close()
 }
}
