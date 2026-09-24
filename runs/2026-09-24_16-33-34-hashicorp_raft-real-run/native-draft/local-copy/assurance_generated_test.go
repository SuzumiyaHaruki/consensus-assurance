package raft

import (
    "encoding/json"
    "fmt"
    "testing"
    "time"
)

// The wrapper delegates every operation and only counts response access.
type assuranceObservedFuture struct {
    AppendFuture
    responseCalls int
}

func (f *assuranceObservedFuture) Response() *AppendEntriesResponse {
    f.responseCalls++
    return f.AppendFuture.Response()
}

// Only the ready-future channel is adapted. Futures come from the built-in pipeline.
type assuranceReadyPipeline struct {
    AppendPipeline
    ready chan AppendFuture
}

func (p *assuranceReadyPipeline) Consumer() <-chan AppendFuture { return p.ready }

func assuranceEvent(t *testing.T, event map[string]interface{}) {
    t.Helper()
    b, err := json.Marshal(event)
    if err != nil { t.Fatal(err) }
    fmt.Println("CA_EVENT " + string(b))
}

func assuranceAwaitFuture(t *testing.T, p AppendPipeline) AppendFuture {
    t.Helper()
    select {
    case f := <-p.Consumer():
        return f
    case <-time.After(3 * time.Second):
        t.Fatal("built-in pipeline did not publish a completed future")
        return nil
    }
}

func assuranceAwaitRPC(t *testing.T, peer *InmemTransport) RPC {
    t.Helper()
    select {
    case rpc := <-peer.Consumer():
        return rpc
    case <-time.After(3 * time.Second):
        t.Fatal("request was not admitted by the peer transport")
        return RPC{}
    }
}

func TestAssurancePipelineFailedFutureResponse(t *testing.T) {
    for _, scenario := range []string{"timeout", "success"} {
        t.Run(scenario, func(t *testing.T) {
            _, sender := NewInmemTransportWithTimeout("sender", 100*time.Millisecond)
            peerAddr, peer := NewInmemTransportWithTimeout("peer", time.Second)
            defer sender.Close()
            defer peer.Close()
            sender.Connect(peerAddr, peer)
            p, err := sender.AppendEntriesPipeline("peer", peerAddr)
            if err != nil { t.Fatal(err) }
            defer p.Close()

            req := &AppendEntriesRequest{Term: 4, Entries: []*Log{{Index: 2, Term: 4, Type: LogNoop}}}
            submitted, err := p.AppendEntries(req, new(AppendEntriesResponse))
            if err != nil { t.Fatal(err) }
            rpc := assuranceAwaitRPC(t, peer)
            if rpc.Command != req { t.Fatal("transport changed request identity") }
            assuranceEvent(t, map[string]interface{}{
                "event": "request_admitted", "operation_id": scenario,
                "admitted": true, "withhold_response": scenario == "timeout",
            })
            if scenario == "success" {
                rpc.Respond(&AppendEntriesResponse{Term: 4, LastLog: 2, Success: true}, nil)
            }
            // Withholding the timeout response models delay beyond the transport deadline.
            ready := assuranceAwaitFuture(t, p)
            if ready != submitted { t.Fatal("pipeline published a different future") }

            // A separately completed rejection ends decoding independently of the measured access.
            stopReq := &AppendEntriesRequest{Term: 4}
            stopper, err := p.AppendEntries(stopReq, new(AppendEntriesResponse))
            if err != nil { t.Fatal(err) }
            stopRPC := assuranceAwaitRPC(t, peer)
            stopRPC.Respond(&AppendEntriesResponse{Term: 4, Success: false}, nil)
            stopReady := assuranceAwaitFuture(t, p)
            if stopReady != stopper { t.Fatal("stop future identity mismatch") }
            observed := &assuranceObservedFuture{AppendFuture: ready}
            adapted := &assuranceReadyPipeline{AppendPipeline: p, ready: make(chan AppendFuture, 2)}
            adapted.ready <- observed
            adapted.ready <- stopReady
            assuranceEvent(t, map[string]interface{}{
                "event": "future_ready", "operation_id": scenario, "published": true,
            })

            config := Configuration{Servers: []Server{{ID: "sender", Suffrage: Voter}, {ID: "peer", Suffrage: Voter}}}
            c := newCommitment(make(chan struct{}, 1), config, 1)
            s := &followerReplication{
                peer: Server{ID: "peer", Address: peerAddr, Suffrage: Voter},
                commitment: c, notify: make(map[*verifyFuture]struct{}),
            }
            r := &Raft{noLegacyTelemetry: true}
            stop := make(chan struct{})
            finish := make(chan struct{})
            go r.pipelineDecode(s, adapted, stop, finish)
            select {
            case <-finish:
            case <-time.After(3 * time.Second):
                close(stop)
                t.Fatal("pipeline consumer did not complete")
            }
            // Observe the real completion status after the consumer has finished.
            // Reading it earlier could satisfy the interface precondition on its behalf.
            futureErr := ready.Error()
            if (futureErr != nil) != (scenario == "timeout") {
                t.Fatalf("unexpected producer result for %s: %v", scenario, futureErr)
            }
            assuranceEvent(t, map[string]interface{}{
                "event": "consumer_completed", "operation_id": scenario,
                "completed": true, "future_failed": futureErr != nil,
                "response_calls": observed.responseCalls,
                "commit_index": c.getCommitIndex(),
            })
        })
    }
}
