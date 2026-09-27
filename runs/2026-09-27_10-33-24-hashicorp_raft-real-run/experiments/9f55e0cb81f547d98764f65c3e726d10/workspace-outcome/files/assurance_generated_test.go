package raft

import (
	"encoding/json"
	"errors"
	"fmt"
	"sync/atomic"
	"testing"
	"time"

	"github.com/hashicorp/go-hclog"
)

// The transport executes the receiver handler, then controls delivery of its actual reply. The replacement election uses actual follower timeout, candidate tally and peer vote handlers.
type assuranceProducedTransport struct {
	Transport
	receiver *Raft
	voter    *Raft
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
func (a *assuranceProducedTransport) RequestVote(id ServerID, _ ServerAddress, req *RequestVoteRequest, resp *RequestVoteResponse) error {
	if id != "N" {
		return errors.New("controlled partition to L")
	}
	ch := make(chan RPCResponse, 1)
	a.voter.requestVote(RPC{Command: req, RespChan: ch}, req)
	result := <-ch
	if result.Error != nil {
		return result.Error
	}
	*resp = *result.Response.(*RequestVoteResponse)
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
func TestAssuranceVerifyAfterElection(t *testing.T) {
	for _, delayed := range []bool{true, false} {
		name := "fresh"
		if delayed {
			name = "elected_before_verify"
		}
		t.Run(name, func(t *testing.T) {
			tr := &assuranceProducedTransport{entered: make(chan struct{}), release: make(chan struct{})}
			cfg := DefaultConfig()
			cfg.LocalID = "L"
			cfg.HeartbeatTimeout = time.Hour
			cfg.LeaderLeaseTimeout = time.Hour
			cfg.ElectionTimeout = time.Hour
			if err := ValidateConfig(cfg); err != nil {
				t.Fatal(err)
			}
			r := &Raft{trans: tr, localID: "L", localAddr: "L", stable: NewInmemStore(), logger: hclog.NewNullLogger(), verifyCh: make(chan *verifyFuture, 4), shutdownCh: make(chan struct{}), noLegacyTelemetry: true, mainThreadSaturation: newSaturationMetric([]string{"assurance"}, time.Hour)}
			r.conf.Store(*cfg)
			r.setCurrentTerm(7)
			r.setState(Leader)
			receiver := &Raft{trans: tr, localID: "F", localAddr: "F", stable: NewInmemStore(), logger: hclog.NewNullLogger()}
			fc := *cfg
			fc.LocalID = "F"
			fc.HeartbeatTimeout = 5 * time.Millisecond
			fc.ElectionTimeout = 200 * time.Millisecond
			fc.LeaderLeaseTimeout = 5 * time.Millisecond
			if err := ValidateConfig(&fc); err != nil {
				t.Fatal(err)
			}
			receiver.conf.Store(fc)
			receiver.preVoteDisabled = true
			receiver.mainThreadSaturation = newSaturationMetric([]string{"assurance_follower"}, time.Hour)
			receiver.setState(Follower)
			receiver.setCurrentTerm(7)
			tr.receiver = receiver
			r.configurations.latest = Configuration{Servers: []Server{{ID: "L", Address: "L", Suffrage: Voter}, {ID: "F", Address: "F", Suffrage: Voter}, {ID: "N", Address: "N", Suffrage: Voter}}}
			s := &followerReplication{currentTerm: 7, peer: Server{ID: "F", Address: "F", Suffrage: Voter}, notifyCh: make(chan struct{}, 1), notify: make(map[*verifyFuture]struct{})}
			r.leaderState.replState = map[ServerID]*followerReplication{"F": s, "N": {peer: Server{ID: "N", Address: "N", Suffrage: Voter}, notifyCh: make(chan struct{}, 1), notify: make(map[*verifyFuture]struct{})}}
			receiver.configurations = r.configurations
			receiver.configurations.latestIndex = 1
			receiver.configurations.committed = receiver.configurations.latest
			receiver.configurations.committedIndex = 1
			voter := &Raft{trans: tr, localID: "N", localAddr: "N", stable: NewInmemStore(), logger: hclog.NewNullLogger(), protocolVersion: cfg.ProtocolVersion}
			nc := *cfg
			nc.LocalID = "N"
			voter.conf.Store(nc)
			voter.setCurrentTerm(7)
			voter.setState(Follower)
			voter.configurations = receiver.configurations
			tr.voter = voter
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
				electionDone := make(chan struct{})
				go func() { defer close(electionDone); receiver.runFollower(); receiver.runCandidate() }()
				select {
				case <-electionDone:
				case <-time.After(2 * time.Second):
					t.Fatal("replacement election timeout")
				}
				receiver.routinesGroup.Wait()
				storedVote, err := voter.stable.GetUint64(keyLastVoteTerm)
				if err != nil {
					t.Fatal(err)
				}
				assuranceVerifyEvent(t, map[string]interface{}{"event": "replacement_election_completed", "operation": name, "receiver_term": receiver.getCurrentTerm(), "receiver_is_leader": receiver.getState() == Leader, "voter_term": voter.getCurrentTerm(), "voter_persisted_vote_term": storedVote})
				if receiver.getState() != Leader {
					t.Fatal("replacement election did not establish leader")
				}

				future = r.VerifyLeader()
				// The first heartbeat is blocked; only actual registration sends this notification.
				select {
				case <-s.notifyCh:
				case <-time.After(2 * time.Second):
					t.Fatal("registration timeout")
				}
			}
			assuranceVerifyEvent(t, map[string]interface{}{"event": "public_verification_admitted", "operation": name, "calls_before_release": atomic.LoadInt32(&tr.calls), "elected_term": receiver.getCurrentTerm()})
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
