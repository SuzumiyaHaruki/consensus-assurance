// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated assurance harness. It repeats the interleaving that the first
// check exercised - a heartbeat-shaped AppendEntries whose term write is held
// while a higher-term AppendEntries is handled - but with the production
// NetworkTransport over the real TCP stream layer instead of an in-process
// substitute, and it skips when that transport cannot bind. It reports raw
// fields only.

package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func assuranceTCPEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

type assuranceTCPFSM struct{}

func (assuranceTCPFSM) Apply(*Log) interface{}         { return nil }
func (assuranceTCPFSM) Snapshot() (FSMSnapshot, error) { return assuranceTCPSnapshot{}, nil }
func (assuranceTCPFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceTCPSnapshot struct{}

func (assuranceTCPSnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceTCPSnapshot) Release()                     {}

// assuranceTCPStore holds exactly one CurrentTerm write inside SetUint64.
type assuranceTCPStore struct {
	*InmemStore
	arm     atomic.Bool
	blocked atomic.Bool
	entered chan struct{}
	release chan struct{}
	mu      sync.Mutex
	writes  []uint64
}

func (s *assuranceTCPStore) SetUint64(key []byte, val uint64) error {
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

func (s *assuranceTCPStore) termWrites() []uint64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]uint64, len(s.writes))
	copy(out, s.writes)
	return out
}

func TestAssuranceHeartbeatTermContextOverTCP(t *testing.T) {
	const (
		op         = "heartbeat-vs-append-over-tcp"
		staleTerm  = uint64(5)
		higherTerm = uint64(6)
	)
	nodeID := ServerID("tcp-follower")

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

	followerTrans, err := NewTCPTransport("127.0.0.1:0", nil, 2, 5*time.Second, io.Discard)
	if err != nil {
		t.Skipf("assurance: tcp transport unavailable on the loopback interface: %v", err)
	}
	defer followerTrans.Close()
	senderTrans, err := NewTCPTransport("127.0.0.1:0", nil, 2, 5*time.Second, io.Discard)
	if err != nil {
		t.Skipf("assurance: tcp transport unavailable on the loopback interface: %v", err)
	}
	defer senderTrans.Close()

	stable := &assuranceTCPStore{InmemStore: NewInmemStore(), entered: make(chan struct{}, 1), release: make(chan struct{})}
	r, err := NewRaft(conf, assuranceTCPFSM{}, NewInmemStore(), stable, NewInmemSnapshotStore(), followerTrans)
	if err != nil {
		assuranceTCPEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": err.Error()})
		t.Fatalf("assurance: NewRaft: %v", err)
	}
	defer func() { r.Shutdown().Error() }()

	bootstrap := Configuration{Servers: []Server{
		{ID: nodeID, Address: followerTrans.LocalAddr(), Suffrage: Voter},
		{ID: ServerID("leader"), Address: senderTrans.LocalAddr(), Suffrage: Voter},
	}}
	if err := r.BootstrapCluster(bootstrap).Error(); err != nil {
		assuranceTCPEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "bootstrap: " + err.Error()})
		t.Fatalf("assurance: bootstrap: %v", err)
	}

	leaderAddr := senderTrans.EncodePeer("leader", senderTrans.LocalAddr())
	heartbeat := AppendEntriesRequest{
		RPCHeader: RPCHeader{ProtocolVersion: 3, ID: []byte("leader"), Addr: leaderAddr},
		Term:      staleTerm,
		Leader:    leaderAddr,
	}
	higher := AppendEntriesRequest{
		RPCHeader:         RPCHeader{ProtocolVersion: 3, ID: []byte("leader-2"), Addr: leaderAddr},
		Term:              higherTerm,
		Leader:            leaderAddr,
		LeaderCommitIndex: 1,
	}

	stable.arm.Store(true)
	var heartbeatResp AppendEntriesResponse
	heartbeatDone := make(chan error, 1)
	go func() {
		heartbeatDone <- senderTrans.AppendEntries(nodeID, followerTrans.LocalAddr(), &heartbeat, &heartbeatResp)
	}()
	select {
	case <-stable.entered:
	case <-time.After(10 * time.Second):
		assuranceTCPEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "heartbeat never reached the gated term write"})
		t.Fatalf("assurance: heartbeat did not reach the gated term write")
	}

	var higherResp AppendEntriesResponse
	if err := senderTrans.AppendEntries(nodeID, followerTrans.LocalAddr(), &higher, &higherResp); err != nil {
		assuranceTCPEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "higher-term append: " + err.Error()})
		t.Fatalf("assurance: higher-term append: %v", err)
	}

	close(stable.release)
	select {
	case err := <-heartbeatDone:
		if err != nil {
			assuranceTCPEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(nodeID), "op": op, "detail": "heartbeat: " + err.Error()})
			t.Fatalf("assurance: heartbeat: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatalf("assurance: heartbeat response never arrived")
	}

	contextTerm := r.CurrentTerm()
	assuranceTCPEvent(map[string]interface{}{
		"event":   "term_advanced",
		"node":    string(nodeID),
		"op":      op,
		"term":    higherResp.Term,
		"success": higherResp.Success,
		"stale_term_from_transport": staleTerm,
	})
	assuranceTCPEvent(map[string]interface{}{
		"event":        "term_context_observed",
		"node":         string(nodeID),
		"op":           op,
		"context_term": contextTerm,
		"store_writes": stable.termWrites(),
		"transport":    "tcp",
		"local_addr":   string(followerTrans.LocalAddr()),
	})
}
