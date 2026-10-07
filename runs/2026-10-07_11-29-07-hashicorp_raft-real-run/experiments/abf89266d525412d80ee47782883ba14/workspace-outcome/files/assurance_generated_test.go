// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated assurance harness. It drives one heartbeat-shaped AppendEntries
// through Raft.processHeartbeat, the callback NewRaft registers through
// Transport.SetHeartbeatHandler, while the node's main goroutine handles a
// second, higher-term AppendEntries on a separate connection.

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

// assuranceEvent writes one CA_EVENT record for the trusted runner.
func assuranceEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

// assurancePipeAddr names one simulated stream endpoint.
type assurancePipeAddr struct{ name string }

func (a assurancePipeAddr) Network() string { return "pipe" }
func (a assurancePipeAddr) String() string  { return a.name }

// assurancePipeNet is a socket-free fabric of net.Pipe endpoint pairs. It only
// substitutes StreamLayer; NetworkTransport itself is the real implementation.
type assurancePipeNet struct {
	mu     sync.Mutex
	layers map[string]*assurancePipeLayer
}

func newAssurancePipeNet() *assurancePipeNet {
	return &assurancePipeNet{layers: make(map[string]*assurancePipeLayer)}
}

func (n *assurancePipeNet) newLayer(name string) *assurancePipeLayer {
	l := &assurancePipeLayer{net: n, name: name, conns: make(chan net.Conn), closed: make(chan struct{})}
	n.mu.Lock()
	n.layers[name] = l
	n.mu.Unlock()
	return l
}

func (n *assurancePipeNet) dial(to string, timeout time.Duration) (net.Conn, error) {
	n.mu.Lock()
	l := n.layers[to]
	n.mu.Unlock()
	if l == nil {
		return nil, fmt.Errorf("no such pipe endpoint %q", to)
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

// assurancePipeLayer implements StreamLayer over assurancePipeNet.
type assurancePipeLayer struct {
	net      *assurancePipeNet
	name     string
	conns    chan net.Conn
	closed   chan struct{}
	closeOne sync.Once
}

func (l *assurancePipeLayer) Accept() (net.Conn, error) {
	select {
	case c := <-l.conns:
		return c, nil
	case <-l.closed:
		return nil, fmt.Errorf("pipe listener %q closed", l.name)
	}
}

func (l *assurancePipeLayer) Close() error {
	l.closeOne.Do(func() {
		close(l.closed)
		l.net.mu.Lock()
		delete(l.net.layers, l.name)
		l.net.mu.Unlock()
	})
	return nil
}

func (l *assurancePipeLayer) Addr() net.Addr { return assurancePipeAddr{l.name} }

func (l *assurancePipeLayer) Dial(address ServerAddress, timeout time.Duration) (net.Conn, error) {
	return l.net.dial(string(address), timeout)
}

// assuranceGatedStore is an InmemStore that records CurrentTerm writes and can
// hold exactly one of them inside StableStore.SetUint64, i.e. after the caller
// decided to adopt a term and before it publishes that term in memory.
type assuranceGatedStore struct {
	*InmemStore
	arm     atomic.Bool
	blocked atomic.Bool
	entered chan struct{}
	release chan struct{}
	mu      sync.Mutex
	writes  []uint64
}

func (s *assuranceGatedStore) SetUint64(key []byte, val uint64) error {
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

func (s *assuranceGatedStore) termWrites() []uint64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]uint64, len(s.writes))
	copy(out, s.writes)
	return out
}

type assuranceFSM struct {
	mu      sync.Mutex
	applied []uint64
}

func (f *assuranceFSM) Apply(l *Log) interface{} {
	f.mu.Lock()
	f.applied = append(f.applied, l.Index)
	f.mu.Unlock()
	return nil
}

func (f *assuranceFSM) appliedIndexes() []uint64 {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]uint64, len(f.applied))
	copy(out, f.applied)
	return out
}

func (f *assuranceFSM) Snapshot() (FSMSnapshot, error) { return assuranceFSMSnapshot{}, nil }

func (f *assuranceFSM) Restore(rc io.ReadCloser) error { return nil }

type assuranceFSMSnapshot struct{}

func (assuranceFSMSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }

func (assuranceFSMSnapshot) Release() {}

// TestAssuranceHeartbeatTermContext drives one heartbeat-shaped AppendEntries
// through the registered transport callback while a separate main-loop
// AppendEntries adopts a higher term, then reports the term context that is in
// effect afterwards.
func TestAssuranceHeartbeatTermContext(t *testing.T) {
	const (
		nodeID     = ServerID("f1")
		staleID    = ServerID("l1")
		higherID   = ServerID("l2")
		staleTerm  = uint64(5)
		higherTerm = uint64(6)
		op         = "heartbeat-vs-append"
	)

	conf := DefaultConfig()
	conf.LocalID = nodeID
	conf.ProtocolVersion = 3
	conf.HeartbeatTimeout = 20 * time.Second
	conf.ElectionTimeout = 20 * time.Second
	conf.LeaderLeaseTimeout = 20 * time.Second
	conf.CommitTimeout = 20 * time.Second
	conf.SnapshotInterval = time.Hour
	conf.SnapshotThreshold = 100000
	conf.TrailingLogs = 100000
	conf.LogLevel = "ERROR"

	stable := &assuranceGatedStore{InmemStore: NewInmemStore(), entered: make(chan struct{}, 1), release: make(chan struct{})}
	logs := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	fsm := &assuranceFSM{}

	fabric := newAssurancePipeNet()
	followerLayer := fabric.newLayer("f1-pipe")
	leaderLayer := fabric.newLayer("l1-pipe")
	followerTrans := NewNetworkTransport(followerLayer, 4, 10*time.Second, io.Discard)
	leaderTrans := NewNetworkTransport(leaderLayer, 4, 10*time.Second, io.Discard)
	defer leaderTrans.Close()

	r, err := NewRaft(conf, fsm, logs, stable, snaps, followerTrans)
	if err != nil {
		assuranceEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": err.Error()})
		t.Fatalf("assurance: NewRaft: %v", err)
	}
	defer func() { r.Shutdown().Error() }()

	bootstrap := Configuration{Servers: []Server{
		{ID: nodeID, Address: followerTrans.LocalAddr(), Suffrage: Voter},
		{ID: staleID, Address: leaderTrans.LocalAddr(), Suffrage: Voter},
	}}
	if err := r.BootstrapCluster(bootstrap).Error(); err != nil {
		assuranceEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "bootstrap: " + err.Error()})
		t.Fatalf("assurance: bootstrap: %v", err)
	}

	// AdmittedRequests are the two AppendEntries RPCs of this prefix: a stale
	// heartbeat from the previous leader and a higher-term request whose
	// completion the node reports to its sender.
	heartbeat := AppendEntriesRequest{
		RPCHeader: RPCHeader{ProtocolVersion: 3, ID: []byte(staleID), Addr: leaderTrans.EncodePeer(staleID, leaderTrans.LocalAddr())},
		Term:      staleTerm,
		Leader:    leaderTrans.EncodePeer(staleID, leaderTrans.LocalAddr()),
	}
	higher := AppendEntriesRequest{
		RPCHeader:         RPCHeader{ProtocolVersion: 3, ID: []byte(higherID), Addr: leaderTrans.EncodePeer(higherID, leaderTrans.LocalAddr())},
		Term:              higherTerm,
		Leader:            leaderTrans.EncodePeer(higherID, leaderTrans.LocalAddr()),
		LeaderCommitIndex: 1,
	}

	// Arm the gate so the first CurrentTerm write after this point (the
	// heartbeat's) is held inside StableStore.
	stable.arm.Store(true)

	var heartbeatResp AppendEntriesResponse
	heartbeatDone := make(chan error, 1)
	go func() {
		heartbeatDone <- leaderTrans.AppendEntries(nodeID, followerTrans.LocalAddr(), &heartbeat, &heartbeatResp)
	}()

	select {
	case <-stable.entered:
	case <-time.After(10 * time.Second):
		assuranceEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "heartbeat never reached the gated term write"})
		t.Fatalf("assurance: heartbeat did not reach the gated term write")
	}

	// While the heartbeat is parked, a second connection carries a request
	// whose term is higher, so the main goroutine adopts it and reports it.
	var higherResp AppendEntriesResponse
	if err := leaderTrans.AppendEntries(nodeID, followerTrans.LocalAddr(), &higher, &higherResp); err != nil {
		assuranceEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "higher-term append: " + err.Error()})
		t.Fatalf("assurance: higher-term append: %v", err)
	}

	// Let the parked stale write finish and publish its term in memory.
	close(stable.release)
	select {
	case err := <-heartbeatDone:
		if err != nil {
			assuranceEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "heartbeat: " + err.Error()})
			t.Fatalf("assurance: heartbeat: %v", err)
		}
	case <-time.After(10 * time.Second):
		assuranceEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "heartbeat response never arrived"})
		t.Fatalf("assurance: heartbeat response never arrived")
	}

	contextTerm := r.CurrentTerm()
	contextLeader, contextLeaderID := r.LeaderWithID()
	storedTerm, storedErr := stable.GetUint64([]byte("CurrentTerm"))
	storedDetail := "unknown"
	if storedErr == nil {
		storedDetail = fmt.Sprintf("%d", storedTerm)
	}

	assuranceEvent(map[string]interface{}{
		"event":   "term_advanced",
		"node":    string(nodeID),
		"op":      op,
		"term":    higherResp.Term,
		"success": higherResp.Success,
	})
	assuranceEvent(map[string]interface{}{
		"event":          "term_context_observed",
		"node":           string(nodeID),
		"op":             op,
		"context_term":   contextTerm,
		"stored_terms":   stable.termWrites(),
		"stored_term":    storedDetail,
		"stale_term":     staleTerm,
		"leader_id":      string(contextLeaderID),
		"leader_address": string(contextLeader),
	})
}
