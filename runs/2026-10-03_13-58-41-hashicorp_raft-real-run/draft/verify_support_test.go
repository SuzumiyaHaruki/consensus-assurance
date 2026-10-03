package raft

import (
    "encoding/json"
    "fmt"
    "io"
    "sync"
    "testing"
    "time"
)

// The wrapper preserves the actual RPC and response. It ends this isolated
// heartbeat worker after one exchange, independently of verification outcome.
type assuranceOneHeartbeat struct {
    *InmemTransport
    stop chan struct{}
    once sync.Once
    response AppendEntriesResponse
    rpcErr error
    calledID ServerID
}

func (x *assuranceOneHeartbeat) AppendEntries(id ServerID, addr ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
    err := x.InmemTransport.AppendEntries(id, addr, req, resp)
    x.response = *resp
    x.rpcErr = err
    x.calledID = id
    x.once.Do(func() { close(x.stop) })
    return err
}

func assuranceEmit(fields map[string]interface{}) {
    raw, err := json.Marshal(fields)
    if err != nil { panic(err) }
    fmt.Println("CA_EVENT " + string(raw))
}

func TestAssuranceVerifySupportEligibility(t *testing.T) {
    for _, selected := range []ServerID{"voter-b", "nonvoter"} {
        t.Run(string(selected), func(t *testing.T) {
            servers := []Server{
                {ID: "leader", Address: "leader", Suffrage: Voter},
                {ID: "voter-b", Address: "voter-b", Suffrage: Voter},
                {ID: "voter-c", Address: "voter-c", Suffrage: Voter},
                {ID: "nonvoter", Address: "nonvoter", Suffrage: Nonvoter},
            }
            configuration := Configuration{Servers: servers}
            nodes := make(map[ServerID]*Raft)
            transports := make(map[ServerID]*InmemTransport)
            var leaderTransport *assuranceOneHeartbeat
            for _, server := range servers {
                cfg := DefaultConfig()
                cfg.ProtocolVersion = 3
                cfg.LocalID = server.ID
                cfg.PreVoteDisabled = true
                cfg.HeartbeatTimeout = time.Hour
                cfg.ElectionTimeout = time.Hour
                cfg.LeaderLeaseTimeout = time.Hour
                cfg.LogOutput = io.Discard
                cfg.skipStartup = true
                _, trans := NewInmemTransportWithTimeout(server.Address, time.Second)
                transports[server.ID] = trans
                var transport Transport = trans
                if server.ID == "leader" {
                    leaderTransport = &assuranceOneHeartbeat{InmemTransport: trans, stop: make(chan struct{})}
                    transport = leaderTransport
                }
                store := NewInmemStore()
                snaps := NewInmemSnapshotStore()
                if err := BootstrapCluster(cfg, store, store, snaps, transport, configuration); err != nil { t.Fatal(err) }
                node, err := NewRaft(cfg, &MockFSM{}, store, store, snaps, transport)
                if err != nil { t.Fatal(err) }
                nodes[server.ID] = node
            }
            for _, a := range servers {
                for _, b := range servers {
                    if a.ID != b.ID { transports[a.ID].Connect(b.Address, transports[b.ID]) }
                }
            }
            stopReceivers := make(chan struct{})
            var receivers sync.WaitGroup
            for _, server := range servers {
                if server.ID == "leader" { continue }
                node := nodes[server.ID]
                receivers.Add(1)
                go func() {
                    defer receivers.Done()
                    for {
                        select {
                        case rpc := <-node.rpcCh: node.processRPC(rpc)
                        case <-stopReceivers: return
                        }
                    }
                }()
            }
            defer func() {
                close(stopReceivers)
                receivers.Wait()
                for _, n := range nodes { n.Shutdown().Error() }
                for _, tr := range transports { tr.Close() }
            }()
            leader := nodes["leader"]
            // Replace only campaign-loop scheduling: execute electSelf and real
            // voter handlers, then take the same majority transition as runCandidate.
            leader.setState(Candidate)
            votes := leader.electSelf()
            granted := 0
            voters := 0
            for _, server := range configuration.Servers { if server.Suffrage == Voter { voters++ } }
            for i := 0; i < voters; i++ {
                select {
                case vote := <-votes:
                    if vote.Granted && vote.Term == leader.getCurrentTerm() { granted++ }
                case <-time.After(2*time.Second): t.Fatal("election response missing")
                }
            }
            if granted < voters/2+1 { t.Fatal("election did not establish majority") }
            leader.setState(Leader)
            leader.setLeader(leader.localAddr, leader.localID)
            leader.setupLeaderState()
            // Materialize startStopReplication's per-peer state without starting
            // all workers. Only the selected heartbeat is scheduled below.
            for _, server := range configuration.Servers {
                if server.ID == leader.localID { continue }
                leader.leaderState.replState[server.ID] = &followerReplication{
                    peer: server,
                    commitment: leader.leaderState.commitment,
                    currentTerm: leader.getCurrentTerm(),
                    nextIndex: leader.getLastIndex()+1,
                    stopCh: make(chan uint64, 1),
                    triggerCh: make(chan struct{}, 1),
                    triggerDeferErrorCh: make(chan *deferError, 1),
                    lastContact: time.Now(),
                    notify: make(map[*verifyFuture]struct{}),
                    notifyCh: make(chan struct{}, 1),
                    stepDown: leader.leaderState.stepDown,
                }
            }
            op := string(selected)
            selectedVoter := false
            for _, server := range configuration.Servers {
                if server.ID == selected { selectedVoter = server.Suffrage == Voter }
            }
            v := &verifyFuture{}
            v.init()
            leader.verifyLeader(v)
            initialVotes := v.votes
            registered := len(leader.leaderState.replState)
            assuranceEmit(map[string]interface{}{
                "event":"verify_admitted", "operation":op,
                "term":leader.getCurrentTerm(), "election_grants":granted,
                "configuration_voters":voters, "quorum":v.quorumSize,
                "initial_votes":initialVotes, "registered_workers":registered,
                "selected_peer":string(selected), "selected_voter":selectedVoter,
            })
            finished := make(chan struct{})
            go func() { defer close(finished); leader.heartbeat(leader.leaderState.replState[selected], leaderTransport.stop) }()
            select {
            case <-finished:
            case <-time.After(3*time.Second): t.Fatal("heartbeat exchange did not finish")
            }
            // Worker join precedes observation; no other replication workers run.
            notified := false
            sameFuture := true
            select {
            case ready := <-leader.verifyCh:
                notified = true
                sameFuture = ready == v
            default:
            }
            v.voteLock.Lock()
            finalVotes := v.votes
            v.voteLock.Unlock()
            eligibleVotes := initialVotes
            if selectedVoter && leaderTransport.rpcErr == nil && leaderTransport.response.Success { eligibleVotes++ }
            errText := ""
            if leaderTransport.rpcErr != nil { errText = leaderTransport.rpcErr.Error() }
            assuranceEmit(map[string]interface{}{
                "event":"verify_observed", "operation":op,
                "worker_finished":true, "rpc_error":errText,
                "rpc_success":leaderTransport.response.Success,
                "response_term":leaderTransport.response.Term,
                "actual_peer":string(leaderTransport.calledID),
                "final_votes":finalVotes, "eligible_votes":eligibleVotes,
                "eligibility_respected":finalVotes <= eligibleVotes,
                "threshold_notified":notified, "same_future":sameFuture,
            })
        })
    }
}
