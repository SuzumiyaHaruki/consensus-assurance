package raft

import (
	"bytes"
	"fmt"
	"sync"
	"testing"
	"time"
)

// fastPathTransport forwards everything to an in-memory transport but, like the
// network transport, installs and honours a heartbeat handler: a strictly empty
// AppendEntries request is dispatched to that handler on the caller's goroutine
// and the response comes back on the supplied channel.
type fastPathTransport struct {
	*InmemTransport

	hbLock sync.Mutex
	hbFn   func(RPC)
}

func (t *fastPathTransport) SetHeartbeatHandler(cb func(RPC)) {
	t.hbLock.Lock()
	t.hbFn = cb
	t.hbLock.Unlock()
}

func (t *fastPathTransport) deliverHeartbeat(req *AppendEntriesRequest, wait time.Duration) (*AppendEntriesResponse, error) {
	t.hbLock.Lock()
	fn := t.hbFn
	t.hbLock.Unlock()
	if fn == nil {
		return nil, fmt.Errorf("no heartbeat handler installed")
	}
	if !(req.Term != 0 && req.RPCHeader.Addr != nil &&
		req.PrevLogEntry == 0 && req.PrevLogTerm == 0 &&
		len(req.Entries) == 0 && req.LeaderCommitIndex == 0) {
		return nil, fmt.Errorf("request would not be classified as a heartbeat")
	}
	respCh := make(chan RPCResponse, 1)
	fn(RPC{Command: req, RespChan: respCh})
	select {
	case r := <-respCh:
		if r.Error != nil {
			return nil, r.Error
		}
		resp, ok := r.Response.(*AppendEntriesResponse)
		if !ok {
			return nil, fmt.Errorf("unexpected heartbeat response type")
		}
		return resp, nil
	case <-time.After(wait):
		return nil, fmt.Errorf("no response within %s", wait)
	}
}

// termGateStore behaves like the in-memory store but can be armed so that the
// next write of the current term is held open: the writer signals on entered
// and waits for release before the write is applied. It widens an existing
// window (the write that follows the main loop's read-modify-write of the
// term) without changing any production code.
type termGateStore struct {
	*InmemStore

	mu      sync.Mutex
	armed   bool
	entered chan struct{}
	release chan struct{}
}

func (s *termGateStore) arm() {
	s.mu.Lock()
	s.armed = true
	s.mu.Unlock()
}

func (s *termGateStore) SetUint64(key []byte, val uint64) error {
	if bytes.Equal(key, keyCurrentTerm) {
		s.mu.Lock()
		armed := s.armed
		s.armed = false
		s.mu.Unlock()
		if armed {
			close(s.entered)
			<-s.release
		}
	}
	return s.InmemStore.SetUint64(key, val)
}

// TestAssurance_TermRegressionWitness asks whether the off-main-thread term
// write of the heartbeat fast path can be overwritten by the main loop's own
// election: the election reads the current term, computes the next one and then
// writes it, with nothing guarding the pair, so a higher term written from the
// fast path in between is lost and the node ends up at a term it had already
// left, durably.
func TestAssurance_TermRegressionWitness(t *testing.T) {
	addr, itrans := NewInmemTransport("")
	conf := inmemConfig(t)
	conf.LocalID = ServerID(addr)
	trans := &fastPathTransport{InmemTransport: itrans}
	store := &termGateStore{
		InmemStore: NewInmemStore(),
		entered:    make(chan struct{}),
		release:    make(chan struct{}),
	}
	snaps := NewInmemSnapshotStore()
	fsm := &MockFSM{}
	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       ServerID(addr),
		Address:  addr,
	}}}

	if err := BootstrapCluster(conf, store, store, snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	node, err := NewRaft(conf, fsm, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("new raft: %v", err)
	}

	limit := time.Now().Add(5 * time.Second)
	for time.Now().Before(limit) && node.getState() != Leader {
		time.Sleep(10 * time.Millisecond)
	}
	if node.getState() != Leader {
		t.Fatalf("single node did not reach Leader state")
	}

	peerAddr := trans.EncodePeer(ServerID("peer-1"), ServerAddress("peer-1"))
	newHeartbeat := func(term uint64) *AppendEntriesRequest {
		return &AppendEntriesRequest{
			RPCHeader: RPCHeader{
				ProtocolVersion: conf.ProtocolVersion,
				ID:              []byte("peer-1"),
				Addr:            peerAddr,
			},
			Term:   term,
			Leader: peerAddr,
		}
	}

	// Step down the node with a higher term so that its own election timer will
	// start an election, which is the main-loop path we want to hold open.
	termAsLeader := node.getCurrentTerm()
	deposeErr := ""
	if _, err := trans.deliverHeartbeat(newHeartbeat(termAsLeader+1), 3*time.Second); err != nil {
		deposeErr = err.Error()
	}

	// Arm the gate immediately, before the follower's election timer can fire,
	// so the next term write the main loop makes is the one that is held open.
	store.arm()
	time.Sleep(120 * time.Millisecond)
	termBeforeElection := node.getCurrentTerm()
	stateBeforeElection := node.getState().String()

	gateOpened := false
	select {
	case <-store.entered:
		gateOpened = true
	case <-time.After(5 * time.Second):
	}
	termInsideElection := node.getCurrentTerm()

	// One empty heartbeat with a much higher term, delivered on this goroutine
	// while the main loop is held inside its term write.
	highTerm := termInsideElection + 10
	hbErr := ""
	hbSuccess := false
	if resp, err := trans.deliverHeartbeat(newHeartbeat(highTerm), 3*time.Second); err != nil {
		hbErr = err.Error()
	} else {
		hbSuccess = resp.Success
	}
	termAfterHeartbeat := node.getCurrentTerm()
	persistedAfterHeartbeat, _ := store.GetUint64(keyCurrentTerm)

	// Let the main loop's election write finish.
	close(store.release)
	time.Sleep(200 * time.Millisecond)

	termAfterRelease := node.getCurrentTerm()
	persistedAfterRelease, _ := store.GetUint64(keyCurrentTerm)
	stateAfterRelease := node.getState().String()

	fmt.Printf("CA_EVENT {\"event\":\"term_regression\",\"node_addr\":%q,"+
		"\"depose_err\":%q,\"term_as_leader\":%d,\"term_before_election\":%d,"+
		"\"state_before_election\":%q,\"gate_opened\":%t,\"term_inside_election\":%d,"+
		"\"heartbeat_err\":%q,\"heartbeat_success\":%t,\"heartbeat_term\":%d,"+
		"\"term_after_heartbeat\":%d,\"persisted_after_heartbeat\":%d,"+
		"\"term_after_release\":%d,\"persisted_after_release\":%d,\"state_after_release\":%q}\n",
		string(addr), deposeErr, termAsLeader, termBeforeElection, stateBeforeElection,
		gateOpened, termInsideElection, hbErr, hbSuccess, highTerm,
		termAfterHeartbeat, persistedAfterHeartbeat,
		termAfterRelease, persistedAfterRelease, stateAfterRelease)

	_ = node.Shutdown().Error()
}
