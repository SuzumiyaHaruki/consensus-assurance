// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated assurance harness. It builds the two-leader overlap of one term
// with the same prefix as the committed-entry harness, records the sitting
// leader's claim, and then observes both leaders' published states and terms
// after a window in which the two leaders are kept from reaching each other. It
// reports raw fields only.

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

func assuranceTwoEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

type assuranceTwoAddr struct{ name string }

func (a assuranceTwoAddr) Network() string { return "pipe" }
func (a assuranceTwoAddr) String() string  { return a.name }

type assuranceTwoFabric struct {
	mu      sync.Mutex
	layers  map[string]*assuranceTwoLayer
	blocked map[string]bool
}

func newAssuranceTwoFabric() *assuranceTwoFabric {
	return &assuranceTwoFabric{layers: make(map[string]*assuranceTwoLayer), blocked: make(map[string]bool)}
}

func (f *assuranceTwoFabric) newLayer(name string) *assuranceTwoLayer {
	l := &assuranceTwoLayer{fabric: f, name: name, conns: make(chan net.Conn), closed: make(chan struct{})}
	f.mu.Lock()
	f.layers[name] = l
	f.mu.Unlock()
	return l
}

func (f *assuranceTwoFabric) block(name string, v bool) {
	f.mu.Lock()
	f.blocked[name] = v
	f.mu.Unlock()
}

func (f *assuranceTwoFabric) dial(to string, timeout time.Duration) (net.Conn, error) {
	f.mu.Lock()
	l, blocked := f.layers[to], f.blocked[to]
	f.mu.Unlock()
	if blocked {
		return nil, fmt.Errorf("pipe endpoint %q unreachable", to)
	}
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

type assuranceTwoLayer struct {
	fabric   *assuranceTwoFabric
	name     string
	conns    chan net.Conn
	closed   chan struct{}
	closeOne sync.Once
}

func (l *assuranceTwoLayer) Accept() (net.Conn, error) {
	select {
	case c := <-l.conns:
		return c, nil
	case <-l.closed:
		return nil, fmt.Errorf("pipe listener %q closed", l.name)
	}
}

func (l *assuranceTwoLayer) Close() error {
	l.closeOne.Do(func() {
		close(l.closed)
		l.fabric.mu.Lock()
		delete(l.fabric.layers, l.name)
		l.fabric.mu.Unlock()
	})
	return nil
}

func (l *assuranceTwoLayer) Addr() net.Addr { return assuranceTwoAddr{l.name} }

func (l *assuranceTwoLayer) Dial(address ServerAddress, timeout time.Duration) (net.Conn, error) {
	return l.fabric.dial(string(address), timeout)
}

// assuranceTwoStore holds exactly one CurrentTerm write inside SetUint64.
type assuranceTwoStore struct {
	*InmemStore
	arm     atomic.Bool
	blocked atomic.Bool
	entered chan struct{}
	release chan struct{}
}

func (s *assuranceTwoStore) SetUint64(key []byte, val uint64) error {
	if string(key) == "CurrentTerm" && s.arm.Load() && s.blocked.CompareAndSwap(false, true) {
		s.entered <- struct{}{}
		<-s.release
	}
	return s.InmemStore.SetUint64(key, val)
}

type assuranceTwoFSM struct {
	mu      sync.Mutex
	applied map[uint64]string
}

func newAssuranceTwoFSM() *assuranceTwoFSM { return &assuranceTwoFSM{applied: make(map[uint64]string)} }

func (f *assuranceTwoFSM) Apply(l *Log) interface{} {
	if l.Type == LogCommand {
		f.mu.Lock()
		f.applied[l.Index] = string(l.Data)
		f.mu.Unlock()
	}
	return nil
}

func (f *assuranceTwoFSM) appliedAt(index uint64) string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.applied[index]
}

func (f *assuranceTwoFSM) Snapshot() (FSMSnapshot, error) { return assuranceTwoSnapshot{}, nil }
func (f *assuranceTwoFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceTwoSnapshot struct{}

func (assuranceTwoSnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceTwoSnapshot) Release()                     {}

// assuranceTwoWatch records the instant a node advertises a state change, and
// what the other node's own published state and term were at that instant.
type assuranceTwoWatch struct {
	mu        sync.Mutex
	other     *Raft
	state     string
	term      uint64
	otherSt   string
	otherTerm uint64
	fired     bool
}

func (w *assuranceTwoWatch) filter(o *Observation) bool {
	if st, ok := o.Data.(RaftState); ok && st == Leader {
		w.mu.Lock()
		if !w.fired {
			w.fired = true
			w.state, w.term = "Leader", o.Raft.CurrentTerm()
			if w.other != nil {
				w.otherSt, w.otherTerm = w.other.State().String(), w.other.CurrentTerm()
			}
		}
		w.mu.Unlock()
	}
	return false
}

func (w *assuranceTwoWatch) snapshot() (bool, string, uint64, string, uint64) {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.fired, w.state, w.term, w.otherSt, w.otherTerm
}

func assuranceTwoWaitFor(t *testing.T, what string, cond func() bool, limit time.Duration) bool {
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if cond() {
			return true
		}
		time.Sleep(200 * time.Microsecond)
	}
	return false
}

func TestAssuranceTwoLeadersOneTerm(t *testing.T) {
	const (
		op    = "two-leaders-one-term"
		cls   = "three-voter-stale-follower"
		term  = uint64(2) // the stale heartbeat's term; the election that follows proposes one above it
		ghost = ServerID("g1")
	)
	dID, eID, tID := ServerID("d1"), ServerID("e1"), ServerID("t1")

	fabric := newAssuranceTwoFabric()
	dLayer, eLayer, tLayer, gLayer := fabric.newLayer("d1-pipe"), fabric.newLayer("e1-pipe"), fabric.newLayer("t1-pipe"), fabric.newLayer("g1-pipe")
	dTrans := NewNetworkTransport(dLayer, 4, 10*time.Second, io.Discard)
	eTrans := NewNetworkTransport(eLayer, 4, 10*time.Second, io.Discard)
	tTrans := NewNetworkTransport(tLayer, 4, 10*time.Second, io.Discard)
	gTrans := NewNetworkTransport(gLayer, 4, 10*time.Second, io.Discard)
	defer func() { dTrans.Close(); eTrans.Close(); tTrans.Close(); gTrans.Close() }()

	config := Configuration{Servers: []Server{
		{ID: dID, Address: dTrans.LocalAddr(), Suffrage: Voter},
		{ID: eID, Address: eTrans.LocalAddr(), Suffrage: Voter},
		{ID: tID, Address: tTrans.LocalAddr(), Suffrage: Voter},
	}}
	entry := &Log{Index: 1, Term: 1, Type: LogConfiguration, Data: EncodeConfiguration(config)}

	// d and e are already past the bootstrap term: they observed term 2 without
	// voting, which is what a node that lost an election and stayed a follower
	// would carry.
	seeded := func(conf *Config, id ServerID) (LogStore, StableStore) {
		logs, stable := NewInmemStore(), NewInmemStore()
		if err := logs.StoreLog(entry); err != nil {
			t.Fatalf("assurance: store log: %v", err)
		}
		if err := stable.SetUint64(keyCurrentTerm, term); err != nil {
			t.Fatalf("assurance: seed term: %v", err)
		}
		return logs, stable
	}
	cfgFor := func(id ServerID, heartbeat, election time.Duration) *Config {
		conf := DefaultConfig()
		conf.LocalID = id
		conf.ProtocolVersion = 3
		conf.PreVoteDisabled = true
		conf.HeartbeatTimeout = heartbeat
		conf.ElectionTimeout = election
		conf.LeaderLeaseTimeout = 2 * time.Second
		conf.CommitTimeout = 30 * time.Second
		conf.SnapshotInterval = time.Hour
		conf.SnapshotThreshold = 100000
		conf.TrailingLogs = 100000
		conf.LogLevel = "ERROR"
		return conf
	}

	dLogs, dStable := seeded(cfgFor(dID, 0, 0), dID)
	eLogs, eStable := seeded(cfgFor(eID, 0, 0), eID)
	dFSM, eFSM, tFSM := newAssuranceTwoFSM(), newAssuranceTwoFSM(), newAssuranceTwoFSM()
	dConf := cfgFor(dID, 1*time.Second, 2*time.Second)
	dConf.LeaderLeaseTimeout = 1 * time.Second
	d, err := NewRaft(dConf, dFSM, dLogs, dStable, NewInmemSnapshotStore(), dTrans)
	if err != nil {
		t.Fatalf("assurance: NewRaft d: %v", err)
	}
	defer func() { d.Shutdown().Error() }()
	e, err := NewRaft(cfgFor(eID, 30*time.Second, 30*time.Second), eFSM, eLogs, eStable, NewInmemSnapshotStore(), eTrans)
	if err != nil {
		t.Fatalf("assurance: NewRaft e: %v", err)
	}
	defer func() { e.Shutdown().Error() }()

	tStable := &assuranceTwoStore{InmemStore: NewInmemStore(), entered: make(chan struct{}, 1), release: make(chan struct{})}
	tNode, err := NewRaft(cfgFor(tID, 30*time.Second, 30*time.Second), tFSM, NewInmemStore(), tStable, NewInmemSnapshotStore(), tTrans)
	if err != nil {
		t.Fatalf("assurance: NewRaft t: %v", err)
	}
	defer func() { tNode.Shutdown().Error() }()
	if err := tNode.BootstrapCluster(config).Error(); err != nil {
		t.Fatalf("assurance: bootstrap t: %v", err)
	}

	watch := &assuranceTwoWatch{other: d}
	tNode.RegisterObserver(NewObserver(nil, false, watch.filter))

	// Hold the stale heartbeat's term write on the lagging node, then keep e out
	// of the election that follows so its vote record for that term stays empty.
	tStable.arm.Store(true)
	ghostAddr := gTrans.EncodePeer(ghost, gTrans.LocalAddr())
	heartbeat := AppendEntriesRequest{
		RPCHeader: RPCHeader{ProtocolVersion: 3, ID: []byte(ghost), Addr: ghostAddr},
		Term:      term,
		Leader:    ghostAddr,
	}
	var heartbeatResp AppendEntriesResponse
	heartbeatDone := make(chan error, 1)
	go func() {
		heartbeatDone <- gTrans.AppendEntries(tID, tTrans.LocalAddr(), &heartbeat, &heartbeatResp)
	}()
	select {
	case <-tStable.entered:
	case <-time.After(10 * time.Second):
		assuranceTwoEvent(map[string]interface{}{"event": "assurance_setup_failed", "op": op, "detail": "stale heartbeat never reached the gated write"})
		t.Fatalf("assurance: stale heartbeat did not reach the gated write")
	}
	fabric.block("e1-pipe", true)

	if !assuranceTwoWaitFor(t, "d leader", func() bool { return d.State() == Leader }, 5*time.Second) {
		assuranceTwoEvent(map[string]interface{}{"event": "assurance_setup_failed", "op": op, "detail": "d did not become leader"})
		t.Fatalf("assurance: d did not become leader")
	}
	firstTerm := d.CurrentTerm()
	firstState := d.State().String()
	firstPeers := fmt.Sprintf("e=%s t=%s", e.State().String(), tNode.State().String())

	// Lengthen the leader's own intervals so the corruption window is wide.
	reload := d.ReloadableConfig()
	reload.HeartbeatTimeout = 5 * time.Second
	reload.ElectionTimeout = 5 * time.Second
	if err := d.ReloadConfig(reload); err != nil {
		t.Fatalf("assurance: reload: %v", err)
	}
	time.Sleep(400 * time.Millisecond)

	// Publish the stale term on the lagging node: it now sits one below the term
	// it voted in.
	close(tStable.release)
	select {
	case err := <-heartbeatDone:
		if err != nil {
			assuranceTwoEvent(map[string]interface{}{"event": "assurance_setup_failed", "op": op, "detail": "stale heartbeat: " + err.Error()})
			t.Fatalf("assurance: stale heartbeat: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatalf("assurance: stale heartbeat response never arrived")
	}
	termAfterRelease := tNode.CurrentTerm()
	fabric.block("e1-pipe", false)

	// The leader transfers to the lagging node, which proposes the term it has
	// already voted in and can still win a vote from the voter that abstained.
	fabric.block("d1-pipe", true)
	transferErr := d.LeadershipTransferToServer(tID, tTrans.LocalAddr()).Error()
	secondLeader := assuranceTwoWaitFor(t, "t leader", func() bool { return tNode.State() == Leader }, 5*time.Second)

	fired, state, secondTerm, otherState, otherTerm := watch.snapshot()
	assuranceTwoEvent(map[string]interface{}{
		"event":       "first_leader_adopted",
		"cluster":     cls,
		"op":          op,
		"node":        string(dID),
		"term":        firstTerm,
		"state":       firstState,
		"peer_states": firstPeers,
	})
	assuranceTwoEvent(map[string]interface{}{
		"event":                 "second_leader_observed",
		"cluster":               cls,
		"op":                    op,
		"node":                  string(tID),
		"term":                  secondTerm,
		"state":                 state,
		"witness_recorded":      fired,
		"other_node_state":      otherState,
		"other_node_term":       otherTerm,
		"other_node_now":        d.State().String(),
		"other_node_term_now":   d.CurrentTerm(),
		"term_after_release":    termAfterRelease,
		"transfer_error":        fmt.Sprintf("%v", transferErr),
		"second_leader_reached": secondLeader,
		"final_voter_states":    fmt.Sprintf("e=%s d=%s", e.State().String(), d.State().String()),
	})
	overlapStart := time.Now()
	assuranceTwoEvent(map[string]interface{}{
		"event":   "leader_claim_observed",
		"cluster": cls,
		"op":      op,
		"node":    string(dID),
		"term":    d.CurrentTerm(),
		"state":   d.State().String(),
	})

	// Keep the two leaders from settling the term while the consequence is
	// observed: neither can reach the other, while both can reach the third
	// voter. The leader that started the transfer stops rejecting client work
	// once its transfer attempt times out.
	fabric.block("t1-pipe", true)
	time.Sleep(6 * time.Second)

	applyFuture := d.Apply([]byte("from-d"), 5*time.Second)
	applyErr := applyFuture.Error()
	applyIndex := applyFuture.Index()
	time.Sleep(500 * time.Millisecond)

	var leaderEntry, replicaEntry Log
	leaderErr := dLogs.GetLog(applyIndex, &leaderEntry)
	replicaErr := eLogs.GetLog(applyIndex, &replicaEntry)
	leaderState := "unknown"
	if leaderErr == nil {
		leaderState = leaderEntry.Type.String()
	}
	replicaState := "unknown"
	if replicaErr == nil {
		replicaState = replicaEntry.Type.String()
	}

	assuranceTwoEvent(map[string]interface{}{
		"event":                 "command_acknowledged",
		"cluster":               cls,
		"op":                    op,
		"node":                  string(dID),
		"index":                 applyIndex,
		"command":               "from-d",
		"acknowledge_error":     fmt.Sprintf("%v", applyErr),
		"leader_log_type":       leaderState,
		"leader_log_term":       leaderEntry.Term,
		"leader_log_data":       string(leaderEntry.Data),
		"leader_state":          d.State().String(),
		"leader_commit_index":   d.CommitIndex(),
		"applied_on_leader":     dFSM.appliedAt(applyIndex),
	})
	assuranceTwoEvent(map[string]interface{}{
		"event":             "replica_entry_observed",
		"cluster":           cls,
		"op":                op,
		"node":              string(eID),
		"index":             applyIndex,
		"log_type":          replicaState,
		"log_term":          replicaEntry.Term,
		"log_data":          string(replicaEntry.Data),
		"applied_on_replica": eFSM.appliedAt(applyIndex),
		"replica_state":     e.State().String(),
		"replica_commit":    e.CommitIndex(),
		"replica_last_index": e.LastIndex(),
	})

	// The two leaders stay apart for the rest of the prefix, so the overlap can
	// be observed over a window rather than at the instant it was created.
	time.Sleep(5 * time.Second)
	window := time.Since(overlapStart)
	assuranceTwoEvent(map[string]interface{}{
		"event":               "persistence_observed",
		"cluster":             cls,
		"op":                  op,
		"first_leader_node":   string(dID),
		"first_leader_state":  d.State().String(),
		"first_leader_term":   d.CurrentTerm(),
		"second_leader_node":  string(tID),
		"second_leader_state": tNode.State().String(),
		"second_leader_term":  tNode.CurrentTerm(),
		"third_voter_state":   e.State().String(),
		"window_seconds":      int(window.Seconds()),
	})
}
