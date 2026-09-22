package raft

import (
 "encoding/json"
 "fmt"
 "testing"
)

func TestAssuranceVerifyVoterEligibility(t *testing.T) {
 emit := func(fields map[string]interface{}) {
  t.Helper()
  b, err := json.Marshal(fields)
  if err != nil { t.Fatal(err) }
  fmt.Println("CA_EVENT " + string(b))
 }
 for _, supporter := range []ServerID{"nonvoter", "voter-a"} {
  t.Run(string(supporter), func(t *testing.T) {
   op := "verify-" + string(supporter)
   configuration := Configuration{Servers: []Server{
    {ID: "leader", Address: "leader", Suffrage: Voter},
    {ID: "voter-a", Address: "voter-a", Suffrage: Voter},
    {ID: "voter-b", Address: "voter-b", Suffrage: Voter},
    {ID: "nonvoter", Address: "nonvoter", Suffrage: Nonvoter},
   }}
   var r Raft
   r.localID = "leader"
   r.protocolVersion = 3
   r.raftState.setState(Leader)
   r.configurations = configurations{
    latest: configuration.Clone(), committed: configuration.Clone(),
    latestIndex: 1, committedIndex: 1,
   }
   r.verifyCh = make(chan *verifyFuture, 1)
   r.leaderState.notify = make(map[*verifyFuture]struct{})
   r.leaderState.replState = make(map[ServerID]*followerReplication)
   for _, server := range configuration.Servers {
    if server.ID == r.localID { continue }
    r.leaderState.replState[server.ID] = &followerReplication{
     peer: server,
     notify: make(map[*verifyFuture]struct{}),
     notifyCh: make(chan struct{}, 1),
    }
   }
   v := &verifyFuture{}
   v.init()
   r.verifyLeader(v)
   _, tracked := r.leaderState.notify[v]
   registered := 0
   for _, worker := range r.leaderState.replState {
    worker.notifyLock.Lock()
    _, ok := worker.notify[v]
    worker.notifyLock.Unlock()
    if ok { registered++ }
   }
   emit(map[string]interface{}{
    "event": "verification_registered", "op_id": op, "stage": "registered",
    "tracked": tracked, "registered_workers": registered,
    "initial_votes": v.votes, "implementation_quorum": v.quorumSize,
    "leader_state": r.getState().String(),
   })
   if !tracked || v.votes != 1 || len(r.verifyCh) != 0 {
    t.Fatal("verification entry prerequisites were not established")
   }
   worker := r.leaderState.replState[supporter]
   if worker == nil { t.Fatal("supporting worker is absent") }
   supportingIDs := map[ServerID]bool{r.localID: true, worker.peer.ID: true}
   voters, eligibleSupport := 0, 0
   for _, server := range configuration.Servers {
    if server.Suffrage == Voter {
     voters++
     if supportingIDs[server.ID] { eligibleSupport++ }
    }
   }
   threshold := voters/2 + 1
   eligibleQuorum := eligibleSupport >= threshold
   emit(map[string]interface{}{
    "event": "support_input", "op_id": op, "registration_stage": "registered",
    "supporter_id": string(worker.peer.ID), "supporter_suffrage": worker.peer.Suffrage.String(),
    "positive": true, "voter_count": voters, "eligible_support": eligibleSupport,
    "independent_threshold": threshold, "eligible_quorum": eligibleQuorum,
   })
   worker.notifyAll(true)
   notified := false
   sameFuture := false
   select {
   case received := <-r.verifyCh:
    notified = true
    sameFuture = received == v
   default:
   }
   if notified && !sameFuture { t.Fatal("notification could not be associated with the verification future") }
   emit(map[string]interface{}{
    "event": "verification_result", "op_id": op, "endpoint": "after_notify_all",
    "notified": notified, "same_future": sameFuture,
    "actual_votes": v.votes, "implementation_quorum": v.quorumSize,
   })
  })
 }
}
