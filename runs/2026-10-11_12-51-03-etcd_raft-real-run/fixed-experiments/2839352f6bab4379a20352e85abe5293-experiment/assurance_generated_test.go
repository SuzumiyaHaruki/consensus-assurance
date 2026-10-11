package raft

import (
 "encoding/hex"
 "encoding/json"
 "fmt"
 "testing"
 pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssuranceReadContext(t *testing.T) {
 emit := func(v map[string]interface{}) { b, err := json.Marshal(v); if err != nil { t.Fatal(err) }; fmt.Println("CA_EVENT " + string(b)) }
 for _, scenario := range []string{"empty", "nonempty"} {
  n := newNetwork(nil, nil, nil)
  n.send(pb.Message{From:1, To:1, Type:pb.MsgHup})
  leader := n.peers[1].(*raft)
  if leader.state != StateLeader || !leader.committedEntryInCurrentTerm() { t.Fatal("election prefix did not establish a committed current-term entry") }
  phase := "initial"
  n.msgHook = func(m pb.Message) bool {
   if m.Type == pb.MsgHeartbeat || m.Type == pb.MsgHeartbeatResp {
    emit(map[string]interface{}{"event":"wire", "scenario":scenario, "phase":phase, "type":m.Type.String(), "from":m.From, "to":m.To, "term":m.Term, "context_hex":hex.EncodeToString(m.Context)})
   }
   return true
  }
  ctx := []byte{}
  if scenario == "nonempty" { ctx = []byte("read-1") }
  emit(map[string]interface{}{"event":"request", "scenario":scenario, "operation":1, "context_hex":hex.EncodeToString(ctx), "term":leader.Term, "commit":leader.raftLog.committed, "state":leader.state.String()})
  n.send(pb.Message{From:1, To:1, Type:pb.MsgReadIndex, Entries:[]pb.Entry{{Data:ctx}}})
  snapshot := func(stage string) {
   outputs := []map[string]interface{}{}
   for i, rs := range leader.readStates { outputs = append(outputs, map[string]interface{}{"position":i,"index":rs.Index,"context_hex":hex.EncodeToString(rs.RequestCtx)}) }
   queue := []string{}
   for _, k := range leader.readOnly.readIndexQueue { queue = append(queue, hex.EncodeToString([]byte(k))) }
   emit(map[string]interface{}{"event":"sample", "scenario":scenario, "stage":stage, "operation":1, "term":leader.Term, "commit":leader.raftLog.committed, "state":leader.state.String(), "outputs":outputs, "pending_contexts_hex":queue})
  }
  snapshot("after_request_drain")
  phase = "heartbeats"
  for i:=0; i<3; i++ { n.send(pb.Message{From:1,To:1,Type:pb.MsgBeat}) }
  snapshot("after_three_heartbeat_rounds")
  phase = "fresh_request"
  fresh := []byte("read-2")
  emit(map[string]interface{}{"event":"request", "scenario":scenario, "operation":2, "context_hex":hex.EncodeToString(fresh), "term":leader.Term,"commit":leader.raftLog.committed})
  n.send(pb.Message{From:1,To:1,Type:pb.MsgReadIndex,Entries:[]pb.Entry{{Data:fresh}}})
  snapshot("after_fresh_request_drain")
 }
}
