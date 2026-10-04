package raft

import (
	"encoding/json"
	"fmt"
	"sync"
	"testing"
	"time"
)

type assurancePending struct {
	id   ServerID
	addr ServerAddress
	req  *AppendEntriesRequest
	resp *AppendEntriesResponse
	done chan error
}

func (p *assurancePending) heartbeat() bool {
	return p.req.PrevLogEntry == 0 && len(p.req.Entries) == 0 && p.req.LeaderCommitIndex == 0
}

type assuranceTransport struct {
	*InmemTransport
	pending chan *assurancePending
	cancel  <-chan struct{}
}

func (a *assuranceTransport) AppendEntries(id ServerID, addr ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
	p := &assurancePending{id: id, addr: addr, req: req, resp: resp, done: make(chan error, 1)}
	select {
	case a.pending <- p:
	case <-a.cancel:
		return fmt.Errorf("driver closed")
	}
	select {
	case err := <-p.done:
		return err
	case <-a.cancel:
		return fmt.Errorf("driver closed")
	}
}
func (a *assuranceTransport) AppendEntriesPipeline(ServerID, ServerAddress) (AppendPipeline, error) {
	return nil, ErrPipelineReplicationNotSupported
}
func assuranceEmit(t *testing.T, event string, fields map[string]interface{}) {
	fields["event"] = event
	data, err := json.Marshal(fields)
	if err != nil {
		t.Fatal(err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

func TestAssuranceVerifyNonvoterEligibility(t *testing.T) {
	// Only scheduling is substituted: real elections, storage, replication,
	// heartbeat response production and verification accounting run unchanged.
	cancel := make(chan struct{})
	var nodes []*Raft
	var transports []*InmemTransport
	var pump sync.WaitGroup
	var leader *Raft
	defer func() {
		close(cancel)
		if leader != nil {
			for _, s := range leader.leaderState.replState {
				close(s.stopCh)
			}
		}
		var stops []Future
		for _, r := range nodes {
			stops = append(stops, r.Shutdown())
		}
		for _, stop := range stops {
			if err := stop.Error(); err != nil {
				t.Log(err)
			}
		}
		pump.Wait()
		for _, tr := range transports {
			tr.Close()
		}
	}()
	configuration := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "a", Address: "a"}, {Suffrage: Voter, ID: "b", Address: "b"},
		{Suffrage: Voter, ID: "c", Address: "c"}, {Suffrage: Nonvoter, ID: "n", Address: "n"},
	}}
	var controlled *assuranceTransport
	for i, server := range configuration.Servers {
		_, base := NewInmemTransportWithTimeout(server.Address, time.Second)
		transports = append(transports, base)
		var tr Transport = base
		if i == 0 {
			controlled = &assuranceTransport{InmemTransport: base, pending: make(chan *assurancePending, 64), cancel: cancel}
			tr = controlled
		}
		conf := DefaultConfig()
		conf.LocalID = server.ID
		conf.skipStartup = true
		conf.PreVoteDisabled = true
		conf.HeartbeatTimeout = 20 * time.Millisecond
		conf.ElectionTimeout = 20 * time.Millisecond
		conf.LeaderLeaseTimeout = 20 * time.Millisecond
		conf.CommitTimeout = 5 * time.Millisecond
		store := NewInmemStore()
		snaps := NewInmemSnapshotStore()
		if i == 0 {
			if err := BootstrapCluster(conf, store, store, snaps, tr, configuration); err != nil {
				t.Fatal(err)
			}
		}
		r, err := NewRaft(conf, &MockFSM{}, store, store, snaps, tr)
		if err != nil {
			t.Fatal(err)
		}
		nodes = append(nodes, r)
	}
	for _, a := range transports {
		for _, b := range transports {
			if a != b {
				a.Connect(b.LocalAddr(), b)
			}
		}
	}
	// Followers process the actual network RPCs, but their autonomous election
	// timers are not scheduled during this finite local-accounting experiment.
	for _, r := range nodes[1:] {
		pump.Add(1)
		go func(r *Raft) {
			defer pump.Done()
			for {
				select {
				case rpc := <-r.rpcCh:
					r.processRPC(rpc)
				case <-cancel:
					return
				}
			}
		}(r)
	}
	leader = nodes[0]
	leader.runFollower()
	if leader.getState() != Candidate {
		t.Fatal("candidate transition not reached")
	}
	leader.runCandidate()
	if leader.getState() != Leader {
		t.Fatal("real campaign did not elect leader")
	}
	leader.setupLeaderState()
	leader.startStopReplication()
	noop := &logFuture{log: Log{Type: LogNoop}}
	noop.init()
	leader.dispatchLogs([]*logFuture{noop})
	var held []*assurancePending
	await := func(id ServerID, hb bool) *assurancePending {
		t.Helper()
		timer := time.NewTimer(3 * time.Second)
		defer timer.Stop()
		for {
			for i, p := range held {
				if p.id == id && p.heartbeat() == hb {
					held = append(held[:i], held[i+1:]...)
					return p
				}
			}
			select {
			case p := <-controlled.pending:
				held = append(held, p)
			case <-timer.C:
				t.Fatalf("missing scheduled request peer=%s heartbeat=%v", id, hb)
				return nil
			}
		}
	}
	release := func(p *assurancePending) bool {
		t.Helper()
		err := controlled.InmemTransport.AppendEntries(p.id, p.addr, p.req, p.resp)
		success := err == nil && p.resp.Success
		p.done <- err
		if err != nil {
			t.Fatalf("actual RPC failed: %v", err)
		}
		return success
	}
	// Synchronize every peer through configuration and the elected-term no-op.
	// Waiting for the next request on the same serial replication path ensures
	// its previous updateLastAppended/notifyAll has finished before admission.
	for _, id := range []ServerID{"b", "c", "n"} {
		for {
			p := await(id, false)
			if release(p) {
				break
			}
		}
		p := await(id, false)
		held = append(held, p)
	}
	ci := leader.leaderState.commitment.getCommitIndex()
	if ci != noop.log.Index {
		t.Fatalf("no-op commitment missing: %d", ci)
	}
	// These calls are the corresponding leaderLoop commit-notification branch;
	// do not run unrelated main-loop timer cases in this controlled schedule.
	leader.setCommitIndex(ci)
	leader.setCommittedConfiguration(leader.configurations.latest, leader.configurations.latestIndex)
	leader.processLogs(ci, map[uint64]*logFuture{noop.log.Index: noop})
	for _, id := range []ServerID{"b", "c", "n"} {
		for {
			p := await(id, false)
			advertised := p.req.LeaderCommitIndex
			release(p)
			if advertised == ci {
				break
			}
		}
		p := await(id, false)
		held = append(held, p)
	}
	if leader.configurations.latestIndex != leader.configurations.committedIndex {
		t.Fatal("configuration not stable")
	}
	for _, r := range nodes[1:] {
		if r.configurations.latestIndex != r.configurations.committedIndex {
			t.Fatal("peer configuration not stable")
		}
	}
	// No response remains in post-return notification work: normal replication
	// requests are all parked at their next send; heartbeats have never replied.
	for _, responder := range []ServerID{"n", "b"} {
		caseID := "verify-" + string(responder)
		v := &verifyFuture{}
		v.init()
		leader.verifyLeader(v)
		v.voteLock.Lock()
		before, quorum := v.votes, v.quorumSize
		v.voteLock.Unlock()
		s := leader.leaderState.replState[responder]
		peer := s.peer
		s.notifyLock.Lock()
		_, registered := s.notify[v]
		s.notifyLock.Unlock()
		assuranceEmit(t, "verify_admitted", map[string]interface{}{"case_id": caseID, "peer_id": string(peer.ID), "suffrage": peer.Suffrage.String(), "before": before, "quorum": quorum, "registered": registered, "leader": leader.getState() == Leader, "stable": leader.configurations.latestIndex == leader.configurations.committedIndex, "term": leader.getCurrentTerm()})
		p := await(responder, true)
		success := release(p)
		assuranceEmit(t, "verify_acknowledged", map[string]interface{}{"case_id": caseID, "peer_id": string(peer.ID), "response_success": success})
		// The next heartbeat invocation occurs after native heartbeat() has called
		// notifyAll for the released response. It is held without a second reply.
		next := await(responder, true)
		held = append(held, next)
		v.voteLock.Lock()
		after := v.votes
		v.voteLock.Unlock()
		signaled := false
		correctIdentity := true
		select {
		case got := <-leader.verifyCh:
			signaled = true
			correctIdentity = got == v
		default:
		}
		assuranceEmit(t, "verify_observed", map[string]interface{}{"case_id": caseID, "peer_id": string(peer.ID), "suffrage": peer.Suffrage.String(), "after": after, "delta": after - before, "response_success": success, "callback_finished": true, "completion_signaled": signaled, "completion_identity": correctIdentity, "term": leader.getCurrentTerm()})
		// Clean the completed test invocation using the production cleanup methods;
		// no success/failure response or external read is synthesized.
		delete(leader.leaderState.notify, v)
		for _, rep := range leader.leaderState.replState {
			rep.cleanNotify(v)
		}
	}
}
