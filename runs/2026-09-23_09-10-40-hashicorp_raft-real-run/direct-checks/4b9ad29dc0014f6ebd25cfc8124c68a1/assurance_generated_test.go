package raft

import (
 "encoding/json"
 "fmt"
 "io"
 "testing"
 "time"
)

func TestAssuranceVerifyContributorEligibility(t *testing.T) {
 emit := func(v map[string]interface{}) {
  b, err := json.Marshal(v)
  if err != nil { t.Fatal(err) }
  fmt.Println("CA_EVENT " + string(b))
 }
 for _, contributor := range []ServerID{"N", "V1"} {
  t.Run(string(contributor), func(t *testing.T) {
   op := "verify-" + string(contributor)
   members := Configuration{Servers: []Server{
    {ID: "L", Address: "L", Suffrage: Voter},
    {ID: "V1", Address: "V1", Suffrage: Voter},
    {ID: "V2", Address: "V2", Suffrage: Voter},
    {ID: "N", Address: "N", Suffrage: Nonvoter},
   }}
   conf := Config{ProtocolVersion: 3, LocalID: "L", LeaderLeaseTimeout: time.Hour, LogOutput: io.Discard}
   r := &Raft{localID: "L", localAddr: "L", verifyCh: make(chan *verifyFuture, 64), shutdownCh: make(chan struct{})}
   r.conf.Store(conf)
   r.logger = conf.getOrCreateLogger()
   r.mainThreadSaturation = newSaturationMetric([]string{"raft", "assurance", "saturation"}, time.Second)
   r.configurations.latest = members
   r.configurations.committed = members
   r.latestConfiguration.Store(members)
   r.raftState.setState(Leader)
   r.raftState.setCurrentTerm(1)
   r.setupLeaderState()
   for _, server := range members.Servers {
    if server.ID == r.localID { continue }
    r.leaderState.replState[server.ID] = &followerReplication{
     peer: server, currentTerm: 1, nextIndex: 1,
     commitment: r.leaderState.commitment,
     stopCh: make(chan uint64, 1), triggerCh: make(chan struct{}, 1),
     triggerDeferErrorCh: make(chan *deferError, 1),
     notifyCh: make(chan struct{}, 1), notify: make(map[*verifyFuture]struct{}),
     stepDown: r.leaderState.stepDown, lastContact: time.Now(),
    }
   }
   primary := &verifyFuture{}
   primary.init()
   r.verifyLeader(primary)
   peer := r.leaderState.replState[contributor]
   _, registered := peer.notify[primary]
   if !registered { t.Fatal("selected contributor did not receive registration") }
   emit(map[string]interface{}{"event":"registered", "operation_id":op, "contributor_id":string(peer.peer.ID), "registered":registered, "implementation_quorum":primary.quorumSize})

   voters, support := 0, 0
   contributorIsVoter := false
   for _, server := range members.Servers {
    if server.Suffrage == Voter {
     voters++
     if server.ID == r.localID || server.ID == peer.peer.ID { support++ }
     if server.ID == peer.peer.ID { contributorIsVoter = true }
    }
   }
   expectedSuccess := support >= voters/2+1
   peer.notifyAll(true)
   emit(map[string]interface{}{"event":"contribution_completed", "operation_id":op, "contributor_id":string(peer.peer.ID), "contributor_is_voter":contributorIsVoter, "affirmative":true, "voter_count":voters, "voter_support":support, "expected_success":expectedSuccess})

   // A distinct marker cannot vote on or complete the primary future.
   // FIFO consumption establishes that earlier terminal notifications were processed.
   marker := &verifyFuture{quorumSize:1, votes:1}
   marker.init()
   r.verifyCh <- marker
   done := make(chan struct{})
   go func() { defer close(done); r.leaderLoop() }()
   stopped := false
   defer func() {
    if !stopped {
     close(r.shutdownCh)
     select { case <-done: case <-time.After(5*time.Second): t.Error("leaderLoop cleanup timeout") }
    }
   }()
   select {
   case err := <-marker.errCh:
    if err != nil { t.Fatalf("processing marker failed: %v", err) }
   case <-done:
    t.Fatal("leaderLoop exited before processing marker")
   case <-time.After(5*time.Second):
    t.Fatal("processing marker timeout")
   }
   close(r.shutdownCh)
   stopped = true
   select {
   case <-done:
   case <-time.After(5*time.Second):
    t.Fatal("leaderLoop join timeout")
   }
   if r.getState() != Leader { t.Fatal("leader generation changed during boundary check") }
   emit(map[string]interface{}{"event":"endpoint_completed", "operation_id":op, "marker_completed":true, "loop_joined":true})
   completed, success := false, false
   errorText := ""
   select {
   case err := <-primary.errCh:
    completed = true
    success = err == nil
    if err != nil { errorText = err.Error() }
   default:
   }
   emit(map[string]interface{}{"event":"verification_result", "operation_id":op, "completed":completed, "success":success, "error":errorText, "votes":primary.votes, "implementation_quorum":primary.quorumSize, "pending_after_endpoint":!completed})
  })
 }
}
