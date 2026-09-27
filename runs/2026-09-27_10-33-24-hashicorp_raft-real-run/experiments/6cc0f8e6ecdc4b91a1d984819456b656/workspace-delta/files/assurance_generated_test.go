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
func TestAssuranceVerifyProducedReplyExploration(t *testing.T) {
	for _, before := range []bool{true, false} {
		name := "fresh"
		if before {
			name = "reply_preproduced"
		}
		t.Run(name, func(t *testing.T) {
			tr := &assuranceProducedTransport{entered: make(chan struct{}), release: make(chan struct{})}
			r := &Raft{trans: tr, localID: "L", localAddr: "L", logger: hclog.NewNullLogger(), verifyCh: make(chan *verifyFuture, 4), noLegacyTelemetry: true}
			cfg := DefaultConfig()
			cfg.LocalID = "L"
			cfg.HeartbeatTimeout = time.Hour
			r.conf.Store(*cfg)
			receiver := &Raft{trans: tr, localID: "F", localAddr: "F", logger: hclog.NewNullLogger(), stable: NewInmemStore()}
			receiver.conf.Store(*cfg)
			receiver.setState(Follower)
			receiver.setCurrentTerm(7)
			tr.receiver = receiver
			r.configurations.latest = Configuration{Servers: []Server{{ID: "L", Address: "L", Suffrage: Voter}, {ID: "F", Address: "F", Suffrage: Voter}, {ID: "N", Address: "N", Suffrage: Voter}}}
			s := &followerReplication{currentTerm: 7, peer: Server{ID: "F", Address: "F", Suffrage: Voter}, notifyCh: make(chan struct{}, 1), notify: make(map[*verifyFuture]struct{})}
			r.leaderState.replState = map[ServerID]*followerReplication{"F": s, "N": {peer: Server{ID: "N", Address: "N", Suffrage: Voter}, notifyCh: make(chan struct{}, 1), notify: make(map[*verifyFuture]struct{})}}
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
			assuranceVerifyEvent(t, map[string]interface{}{"event": "reply_produced", "operation": name, "rpc_id": 1, "registered_before_reply": !before, "reply_success": tr.produced.Success, "reply_term": tr.produced.Term})
			if before {
				// The new leader's election is an input assumption, not executed here.
				newer := &AppendEntriesRequest{RPCHeader: RPCHeader{ID: []byte("N"), Addr: []byte("N")}, Term: 8}
				ch := make(chan RPCResponse, 1)
				receiver.appendEntries(RPC{Command: newer, RespChan: ch}, newer)
				actual := <-ch
				assuranceVerifyEvent(t, map[string]interface{}{"event": "newer_request_processed", "operation": name, "receiver_term": receiver.getCurrentTerm(), "success": actual.Response.(*AppendEntriesResponse).Success})
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
			assuranceVerifyEvent(t, map[string]interface{}{"event": "worker_finished", "operation": name, "rpc_id": 1, "calls": atomic.LoadInt32(&tr.calls), "receiver_term": receiver.getCurrentTerm(), "delivered_reply_term": tr.produced.Term, "notified": notified, "same_future": same, "votes": votes, "quorum": quorum})
		})
	}
}
