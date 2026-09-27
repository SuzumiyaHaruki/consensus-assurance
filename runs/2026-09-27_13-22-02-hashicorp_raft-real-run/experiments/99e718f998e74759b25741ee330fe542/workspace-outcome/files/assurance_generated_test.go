package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"

	"github.com/hashicorp/go-hclog"
)

func assuranceContactEvent(t *testing.T, e map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(e)
	if err != nil {
		t.Fatal(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// This is a conditional local-state exploration, not a cluster election history.
// No receiving Raft runs: queued requests receive no processing or reply.
func TestAssuranceContactTimeoutLeaseCheck(t *testing.T) {
	for _, mode := range []string{"pipeline_timeout", "ordinary_timeout"} {
		t.Run(mode, func(t *testing.T) {
			addr, sender := NewInmemTransportWithTimeout(ServerAddress("sender-"+mode), 40*time.Millisecond)
			peerAddr, receiver := NewInmemTransportWithTimeout(ServerAddress("receiver-"+mode), 40*time.Millisecond)
			defer sender.Close()
			defer receiver.Close()
			sender.Connect(peerAddr, receiver)
			conf := DefaultConfig()
			conf.LocalID = ServerID(addr)
			conf.LeaderLeaseTimeout = 2 * time.Second
			conf.HeartbeatTimeout = 2 * time.Second
			conf.ElectionTimeout = 2 * time.Second
			if err := ValidateConfig(conf); err != nil {
				t.Fatal(err)
			}
			old := time.Now().Add(-4 * time.Second)
			peer := Server{ID: ServerID(peerAddr), Address: peerAddr, Suffrage: Voter}
			s := &followerReplication{peer: peer, currentTerm: 1, nextIndex: 1,
				lastContact: old, notify: make(map[*verifyFuture]struct{}), stepDown: make(chan struct{}, 1)}
			r := &Raft{localID: ServerID(addr), localAddr: addr, trans: sender,
				logger: hclog.NewNullLogger(), shutdownCh: make(chan struct{}), logs: NewInmemStore()}
			r.conf.Store(*conf)
			r.raftState.setState(Leader)
			r.configurations.latest = Configuration{Servers: []Server{
				{ID: r.localID, Address: addr, Suffrage: Voter}, peer,
			}}
			r.leaderState.replState = map[ServerID]*followerReplication{peer.ID: s}
			assuranceContactEvent(t, map[string]interface{}{"event": "local_prefix", "operation": mode,
				"state": r.State().String(), "contact_ns": old.UnixNano(), "lease_ns": int64(conf.LeaderLeaseTimeout),
				"initialization": "constructed local state; no election; no remote Raft worker"})

			var request *AppendEntriesRequest
			futureError := ""
			if mode == "pipeline_timeout" {
				p, err := sender.AppendEntriesPipeline(peer.ID, peerAddr)
				if err != nil {
					t.Fatal(err)
				}
				defer p.Close()
				request = &AppendEntriesRequest{Term: 1}
				future, err := p.AppendEntries(request, new(AppendEntriesResponse))
				if err != nil {
					t.Fatal(err)
				}
				completed := make(chan error, 1)
				go func() { completed <- future.Error() }()
				select {
				case err = <-completed:
					if err != nil {
						futureError = err.Error()
					}
				case <-time.After(3 * time.Second):
					t.Fatal("future completion timeout")
				}
				assuranceContactEvent(t, map[string]interface{}{"event": "transport_completion", "operation": mode,
					"error": futureError, "same_request": future.Request() == request, "contact_ns": s.LastContact().UnixNano()})
				stop, finish := make(chan struct{}), make(chan struct{})
				go r.pipelineDecode(s, p, stop, finish)
				select {
				case <-finish:
				case <-time.After(3 * time.Second):
					close(stop)
					t.Fatal("decoder completion timeout")
				}
			} else {
				completed := make(chan bool, 1)
				go func() { completed <- r.replicateTo(s, 0) }()
				select {
				case shouldStop := <-completed:
					assuranceContactEvent(t, map[string]interface{}{"event": "replication_completion", "operation": mode,
						"should_stop": shouldStop, "failures": s.failures})
				case <-time.After(3 * time.Second):
					t.Fatal("ordinary replication completion timeout")
				}
			}
			// Inspect the one admitted request only after completion; do not respond.
			var received RPC
			select {
			case received = <-receiver.Consumer():
			default:
				t.Fatal("missing admitted request")
			}
			actual, ok := received.Command.(*AppendEntriesRequest)
			if !ok {
				t.Fatal("unexpected RPC type")
			}
			if request != nil && actual != request {
				t.Fatal("request identity mismatch")
			}
			beforeLease := s.LastContact()
			assuranceContactEvent(t, map[string]interface{}{"event": "consumer_completion", "operation": mode,
				"request_term": actual.Term, "contact_before_ns": old.UnixNano(), "contact_after_ns": beforeLease.UnixNano(),
				"contact_changed": !beforeLease.Equal(old), "contact_age_ns": int64(time.Since(beforeLease)), "pipeline_error": futureError})
			r.checkLeaderLease()
			assuranceContactEvent(t, map[string]interface{}{"event": "lease_result", "operation": mode,
				"state": r.State().String(), "contact_ns": s.LastContact().UnixNano()})
		})
	}
}
