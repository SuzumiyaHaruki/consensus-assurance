package raft

import (
	"encoding/json"
	"fmt"
	"sync/atomic"
	"testing"
	"time"

	"github.com/hashicorp/go-hclog"
)

// The transport controls response delivery only; no remote election is simulated.
type assuranceVerifyTransport struct {
	Transport
	entered chan struct{}
	release chan struct{}
	calls   int32
}

func (a *assuranceVerifyTransport) EncodePeer(_ ServerID, addr ServerAddress) []byte {
	return []byte(addr)
}
func (a *assuranceVerifyTransport) AppendEntries(_ ServerID, _ ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
	n := atomic.AddInt32(&a.calls, 1)
	if n == 1 {
		close(a.entered)
		<-a.release
	}
	resp.Term = req.Term
	resp.Success = true
	return nil
}
func assuranceVerifyEvent(t *testing.T, fields map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(fields)
	if err != nil {
		t.Fatal(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}
func TestAssuranceVerifyInflightExploration(t *testing.T) {
	for _, before := range []bool{true, false} {
		name := "fresh"
		if before {
			name = "already_inflight"
		}
		t.Run(name, func(t *testing.T) {
			tr := &assuranceVerifyTransport{entered: make(chan struct{}), release: make(chan struct{})}
			r := &Raft{trans: tr, localID: "L", localAddr: "L", logger: hclog.NewNullLogger(), verifyCh: make(chan *verifyFuture, 4), noLegacyTelemetry: true}
			cfg := DefaultConfig()
			cfg.LocalID = "L"
			cfg.HeartbeatTimeout = time.Hour
			r.conf.Store(*cfg)
			r.configurations.latest = Configuration{Servers: []Server{{ID: "L", Address: "L", Suffrage: Voter}, {ID: "F", Address: "F", Suffrage: Voter}}}
			s := &followerReplication{currentTerm: 7, peer: Server{ID: "F", Address: "F", Suffrage: Voter}, notifyCh: make(chan struct{}, 1), notify: make(map[*verifyFuture]struct{})}
			r.leaderState.replState = map[ServerID]*followerReplication{"F": s}
			r.leaderState.notify = make(map[*verifyFuture]struct{})
			stop, done := make(chan struct{}), make(chan struct{})
			v := &verifyFuture{}
			v.init()
			if !before {
				r.verifyLeader(v)
			} else {
				s.notifyCh <- struct{}{}
			}
			go func() { defer close(done); r.heartbeat(s, stop) }()
			select {
			case <-tr.entered:
			case <-time.After(2 * time.Second):
				t.Fatal("heartbeat did not enter controlled transport")
			}
			assuranceVerifyEvent(t, map[string]interface{}{"event": "rpc_entered", "operation": name, "rpc_id": 1, "registered_before_rpc": !before})
			if before {
				r.verifyLeader(v)
			}
			assuranceVerifyEvent(t, map[string]interface{}{"event": "verification_registered", "operation": name, "rpc_id": 1, "calls_before_release": atomic.LoadInt32(&tr.calls)})
			// Stop independently of the vote outcome. Remove the extra notification so
			// only the controlled first RPC can supply this observation.
			select {
			case <-s.notifyCh:
			default:
			}
			close(stop)
			close(tr.release)
			select {
			case <-done:
			case <-time.After(2 * time.Second):
				t.Fatal("heartbeat worker did not stop")
			}
			notified := false
			same := false
			select {
			case got := <-r.verifyCh:
				notified = true
				same = got == v
			default:
			}
			v.voteLock.Lock()
			votes, quorum := v.votes, v.quorumSize
			v.voteLock.Unlock()
			assuranceVerifyEvent(t, map[string]interface{}{"event": "worker_finished", "operation": name, "rpc_id": 1, "calls": atomic.LoadInt32(&tr.calls), "notified": notified, "same_future": same, "votes": votes, "quorum": quorum})
		})
	}
}
