package raft

import (
	"encoding/json"
	"fmt"
	"sync/atomic"
	"testing"
	"time"

	"github.com/hashicorp/go-hclog"
)

// The transport executes the receiver handler, then controls delivery of its actual reply. No election is simulated.
type assuranceProducedTransport struct {
	Transport
	receiver *Raft
	produced *AppendEntriesResponse
	entered  chan struct{}
	release  chan struct{}
	calls    int32
}

func (a *assuranceProducedTransport) EncodePeer(_ ServerID, addr ServerAddress) []byte {
	return []byte(addr)
}
func (a *assuranceProducedTransport) DecodePeer(b []byte) ServerAddress { return ServerAddress(b) }
func (a *assuranceProducedTransport) AppendEntries(_ ServerID, _ ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
	n := atomic.AddInt32(&a.calls, 1)
	responseCh := make(chan RPCResponse, 1)
	a.receiver.appendEntries(RPC{Command: req, RespChan: responseCh}, req)
	result := <-responseCh
	if result.Error != nil {
		return result.Error
	}
	actual := result.Response.(*AppendEntriesResponse)
	if n == 1 {
		a.produced = actual
		close(a.entered)
		<-a.release
	}
	*resp = *actual
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
func TestAssuranceVerifyPublicCompletionExploration(t *testing.T) {
	for _, delayed := range []bool{true, false} {
		name := "fresh"
		if delayed {
			name = "preproduced_public"
		}
		t.Run(name, func(t *testing.T) {
			tr := &assuranceProducedTransport{entered: make(chan struct{}), release: make(chan struct{})}
			cfg := DefaultConfig()
			cfg.LocalID = "L"
			cfg.HeartbeatTimeout = time.Hour
			cfg.LeaderLeaseTimeout = time.Hour
			r := &Raft{trans: tr, localID: "L", localAddr: "L", stable: NewInmemStore(), logger: hclog.NewNullLogger(), verifyCh: make(chan *verifyFuture, 4), shutdownCh: make(chan struct{}), noLegacyTelemetry: true, mainThreadSaturation: newSaturationMetric([]string{"assurance"}, time.Hour)}
			r.conf.Store(*cfg)
			r.setCurrentTerm(7)
			r.setState(Leader)
			receiver := &Raft{trans: tr, localID: "F", localAddr: "F", stable: NewInmemStore(), logger: hclog.NewNullLogger()}
			fc := *cfg
			fc.LocalID = "F"
			receiver.conf.Store(fc)
			receiver.setState(Follower)
			receiver.setCurrentTerm(7)
			tr.receiver = receiver
			r.configurations.latest = Configuration{Servers: []Server{{ID: "L", Address: "L", Suffrage: Voter}, {ID: "F", Address: "F", Suffrage: Voter}, {ID: "N", Address: "N", Suffrage: Voter}}}
			s := &followerReplication{currentTerm: 7, peer: Server{ID: "F", Address: "F", Suffrage: Voter}, notifyCh: make(chan struct{}, 1), notify: make(map[*verifyFuture]struct{})}
			r.leaderState.replState = map[ServerID]*followerReplication{"F": s, "N": {peer: Server{ID: "N", Address: "N", Suffrage: Voter}, notifyCh: make(chan struct{}, 1), notify: make(map[*verifyFuture]struct{})}}
			r.leaderState.notify = make(map[*verifyFuture]struct{})
			r.leaderState.commitment = &commitment{startIndex: 1}
			stop, workerDone, loopDone := make(chan struct{}), make(chan struct{}), make(chan struct{})
			go func() { defer close(loopDone); r.leaderLoop() }()
			var future Future
			if delayed {
				s.notifyCh <- struct{}{}
			} else {
				future = r.VerifyLeader()
			}
			go func() { defer close(workerDone); r.heartbeat(s, stop) }()
			select {
			case <-tr.entered:
			case <-time.After(2 * time.Second):
				t.Fatal("reply production timeout")
			}
			assuranceVerifyEvent(t, map[string]interface{}{"event": "reply_produced", "operation": name, "reply_term": tr.produced.Term, "success": tr.produced.Success, "before_invocation": delayed})
			if delayed {
				req := &AppendEntriesRequest{RPCHeader: RPCHeader{ID: []byte("N"), Addr: []byte("N")}, Term: 8}
				ch := make(chan RPCResponse, 1)
				receiver.appendEntries(RPC{Command: req, RespChan: ch}, req)
				actual := <-ch
				assuranceVerifyEvent(t, map[string]interface{}{"event": "newer_request_processed", "operation": name, "receiver_term": receiver.getCurrentTerm(), "success": actual.Response.(*AppendEntriesResponse).Success})
				future = r.VerifyLeader()
				// The first heartbeat is blocked; only actual registration sends this notification.
				select {
				case <-s.notifyCh:
				case <-time.After(2 * time.Second):
					t.Fatal("registration timeout")
				}
			}
			assuranceVerifyEvent(t, map[string]interface{}{"event": "public_verification_admitted", "operation": name, "calls_before_release": atomic.LoadInt32(&tr.calls)})
			close(stop)
			close(tr.release)
			select {
			case <-workerDone:
			case <-time.After(2 * time.Second):
				t.Fatal("worker completion timeout")
			}
			result := make(chan error, 1)
			go func() { result <- future.Error() }()
			completed, success := false, false
			errText := ""
			select {
			case err := <-result:
				completed = true
				success = err == nil
				if err != nil {
					errText = err.Error()
				}
			case <-time.After(300 * time.Millisecond):
			}
			close(r.shutdownCh)
			select {
			case <-loopDone:
			case <-time.After(2 * time.Second):
				t.Fatal("leader loop shutdown timeout")
			}
			assuranceVerifyEvent(t, map[string]interface{}{"event": "public_verification_observed", "operation": name, "completed": completed, "success": success, "error": errText, "receiver_term": receiver.getCurrentTerm(), "reply_term": tr.produced.Term, "calls": atomic.LoadInt32(&tr.calls)})
		})
	}
}
