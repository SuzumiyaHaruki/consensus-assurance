// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated assurance harness. A stale heartbeat from a deposed leader is held
// inside the node's StableStore write while a higher-term vote is granted; the
// node's own election then runs, and the harness reports the term and
// candidate of the two persisted votes. It prints raw fields only.

package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func assuranceVoteEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

type assuranceVoteAddr struct{ name string }

func (a assuranceVoteAddr) Network() string { return "pipe" }
func (a assuranceVoteAddr) String() string  { return a.name }

type assuranceVoteFabric struct {
	mu     sync.Mutex
	layers map[string]*assuranceVoteLayer
}

func newAssuranceVoteFabric() *assuranceVoteFabric {
	return &assuranceVoteFabric{layers: make(map[string]*assuranceVoteLayer)}
}

func (f *assuranceVoteFabric) newLayer(name string) *assuranceVoteLayer {
	l := &assuranceVoteLayer{fabric: f, name: name, conns: make(chan net.Conn), closed: make(chan struct{})}
	f.mu.Lock()
	f.layers[name] = l
	f.mu.Unlock()
	return l
}

func (f *assuranceVoteFabric) dial(to string, timeout time.Duration) (net.Conn, error) {
	f.mu.Lock()
	l := f.layers[to]
	f.mu.Unlock()
	if l == nil {
		return nil, fmt.Errorf("no pipe endpoint %q", to)
	}
	local, remote := net.Pipe()
	select {
	case l.conns <- local:
		return remote, nil
	case <-l.closed:
		local.Close()
		remote.Close()
		return nil, fmt.Errorf("pipe endpoint %q closed", to)
	case <-time.After(timeout):
		local.Close()
		remote.Close()
		return nil, fmt.Errorf("pipe dial to %q timed out", to)
	}
}

type assuranceVoteLayer struct {
	fabric   *assuranceVoteFabric
	name     string
	conns    chan net.Conn
	closed   chan struct{}
	closeOne sync.Once
}

func (l *assuranceVoteLayer) Accept() (net.Conn, error) {
	select {
	case c := <-l.conns:
		return c, nil
	case <-l.closed:
		return nil, fmt.Errorf("pipe listener %q closed", l.name)
	}
}

func (l *assuranceVoteLayer) Close() error {
	l.closeOne.Do(func() {
		close(l.closed)
		l.fabric.mu.Lock()
		delete(l.fabric.layers, l.name)
		l.fabric.mu.Unlock()
	})
	return nil
}

func (l *assuranceVoteLayer) Addr() net.Addr { return assuranceVoteAddr{l.name} }

func (l *assuranceVoteLayer) Dial(address ServerAddress, timeout time.Duration) (net.Conn, error) {
	return l.fabric.dial(string(address), timeout)
}

type assuranceVoteStore struct {
	*InmemStore
	arm     atomic.Bool
	blocked atomic.Bool
	entered chan struct{}
	release chan struct{}
	mu      sync.Mutex
	writes  []uint64
}

func (s *assuranceVoteStore) SetUint64(key []byte, val uint64) error {
	if string(key) == "CurrentTerm" {
		s.mu.Lock()
		s.writes = append(s.writes, val)
		s.mu.Unlock()
		if s.arm.Load() && s.blocked.CompareAndSwap(false, true) {
			s.entered <- struct{}{}
			<-s.release
		}
	}
	return s.InmemStore.SetUint64(key, val)
}

func (s *assuranceVoteStore) termWrites() []uint64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]uint64, len(s.writes))
	copy(out, s.writes)
	return out
}

type assuranceVoteFSM struct{}

func (assuranceVoteFSM) Apply(*Log) interface{}         { return nil }
func (assuranceVoteFSM) Snapshot() (FSMSnapshot, error) { return assuranceVoteSnapshot{}, nil }
func (assuranceVoteFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceVoteSnapshot struct{}

func (assuranceVoteSnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceVoteSnapshot) Release()                     {}

func assuranceVoteRecord(s *assuranceVoteStore) (uint64, string) {
	term, err := s.GetUint64(keyLastVoteTerm)
	if err != nil {
		term = 0
	}
	cand, err := s.Get(keyLastVoteCand)
	if err != nil {
		cand = nil
	}
	return term, string(cand)
}

func TestAssuranceVoteRecordTermReuse(t *testing.T) {
	const (
		nodeID      = ServerID("f1")
		peerID      = ServerID("d1")
		staleLeader = ServerID("l1")
		staleTerm   = uint64(6)
		higherTerm  = uint64(7)
		op          = "vote-record-term-reuse"
	)

	conf := DefaultConfig()
	conf.LocalID = nodeID
	conf.ProtocolVersion = 3
	conf.HeartbeatTimeout = 200 * time.Millisecond
	conf.ElectionTimeout = 200 * time.Millisecond
	conf.LeaderLeaseTimeout = 200 * time.Millisecond
	conf.CommitTimeout = 200 * time.Millisecond
	conf.SnapshotInterval = time.Hour
	conf.SnapshotThreshold = 100000
	conf.TrailingLogs = 100000
	conf.PreVoteDisabled = true
	conf.LogLevel = "ERROR"

	stable := &assuranceVoteStore{InmemStore: NewInmemStore(), entered: make(chan struct{}, 1), release: make(chan struct{})}
	logs := NewInmemStore()
	snaps := NewInmemSnapshotStore()

	fabric := newAssuranceVoteFabric()
	nodeLayer := fabric.newLayer("f1-pipe")
	senderLayer := fabric.newLayer("l1-pipe")
	nodeTrans := NewNetworkTransport(nodeLayer, 4, 10*time.Second, io.Discard)
	senderTrans := NewNetworkTransport(senderLayer, 4, 10*time.Second, io.Discard)
	defer senderTrans.Close()

	r, err := NewRaft(conf, assuranceVoteFSM{}, logs, stable, snaps, nodeTrans)
	if err != nil {
		assuranceVoteEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": err.Error()})
		t.Fatalf("assurance: NewRaft: %v", err)
	}
	defer func() { r.Shutdown().Error() }()

	bootstrap := Configuration{Servers: []Server{
		{ID: nodeID, Address: nodeTrans.LocalAddr(), Suffrage: Voter},
		{ID: peerID, Address: "d1-pipe", Suffrage: Voter},
	}}
	if err := r.BootstrapCluster(bootstrap).Error(); err != nil {
		assuranceVoteEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "bootstrap: " + err.Error()})
		t.Fatalf("assurance: bootstrap: %v", err)
	}

	staleAddr := senderTrans.EncodePeer(staleLeader, senderTrans.LocalAddr())
	peerAddr := senderTrans.EncodePeer(peerID, "d1-pipe")

	heartbeat := AppendEntriesRequest{
		RPCHeader: RPCHeader{ProtocolVersion: 3, ID: []byte(staleLeader), Addr: staleAddr},
		Term:      staleTerm,
		Leader:    staleAddr,
	}
	var heartbeatResp AppendEntriesResponse
	heartbeatDone := make(chan error, 1)

	stable.arm.Store(true)
	go func() {
		heartbeatDone <- senderTrans.AppendEntries(nodeID, nodeTrans.LocalAddr(), &heartbeat, &heartbeatResp)
	}()
	select {
	case <-stable.entered:
	case <-time.After(10 * time.Second):
		assuranceVoteEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "heartbeat never reached the gated term write"})
		t.Fatalf("assurance: heartbeat did not reach the gated term write")
	}

	voteReq := RequestVoteRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: 3, ID: []byte(peerID), Addr: peerAddr},
		Term:         higherTerm,
		Candidate:    peerAddr,
		LastLogIndex: 1,
		LastLogTerm:  1,
	}
	var voteResp RequestVoteResponse
	if err := senderTrans.RequestVote(nodeID, nodeTrans.LocalAddr(), &voteReq, &voteResp); err != nil {
		assuranceVoteEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "vote request: " + err.Error()})
		t.Fatalf("assurance: vote request: %v", err)
	}
	firstTerm, firstCandidate := assuranceVoteRecord(stable)

	close(stable.release)
	select {
	case err := <-heartbeatDone:
		if err != nil {
			assuranceVoteEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "heartbeat: " + err.Error()})
			t.Fatalf("assurance: heartbeat: %v", err)
		}
	case <-time.After(10 * time.Second):
		assuranceVoteEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "heartbeat response never arrived"})
		t.Fatalf("assurance: heartbeat response never arrived")
	}
	termAfterRelease := r.CurrentTerm()
	stateAfterRelease := r.State().String()

	deadline := time.Now().Add(5 * time.Second)
	var secondTerm uint64
	var secondCandidate string
	sawSecondVote := false
	for time.Now().Before(deadline) {
		term, cand := assuranceVoteRecord(stable)
		termAgain, candAgain := assuranceVoteRecord(stable)
		if term == termAgain && cand == candAgain && cand != "" && cand != firstCandidate {
			secondTerm, secondCandidate, sawSecondVote = term, cand, true
			break
		}
		time.Sleep(time.Millisecond)
	}

	nodeState := r.State().String()
	contextTerm := r.CurrentTerm()

	assuranceVoteEvent(map[string]interface{}{
		"event":               "first_vote_observed",
		"node":                string(nodeID),
		"op":                  op,
		"stage":               "higher-term-vote-before-release",
		"term":                firstTerm,
		"candidate":           firstCandidate,
		"vote_granted":        voteResp.Granted,
		"term_after_release":  termAfterRelease,
		"stale_term":          staleTerm,
		"term_writes":         stable.termWrites(),
		"state_after_release": stateAfterRelease,
		"saw_second_vote":     sawSecondVote,
	})
	assuranceVoteEvent(map[string]interface{}{
		"event":               "second_vote_observed",
		"node":                string(nodeID),
		"op":                  op,
		"stage":               "self-vote-from-own-election",
		"term":                secondTerm,
		"candidate":           secondCandidate,
		"first_term":          firstTerm,
		"first_candidate":     firstCandidate,
		"context_term":        contextTerm,
		"node_state":          nodeState,
		"saw_second_vote":     sawSecondVote,
		"same_candidate":      secondCandidate == firstCandidate,
		"distinct_from_first": secondTerm != firstTerm || secondCandidate != firstCandidate,
	})
}
