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
// and waits for release before the write is applied.
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

// TestAssurance_TermRegressionControl is the control for the term-regression
// witness: the same node, the same instrumented store and the same held-open
// election write, with the one thing missing that the witness had - the empty
// heartbeat delivered on the fast path during the hold. If the term still fell
// after the release without that heartbeat, the regression would belong to the
// instrumentation rather than to the off-main-thread write, and the witness
// account would have to be withdrawn.
func TestAssurance_TermRegressionControl(t *testing.T) {
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

	// Depose the node so that its own election timer starts an election.
	termAsLeader := node.getCurrentTerm()
	deposeErr := ""
	if _, err := trans.deliverHeartbeat(newHeartbeat(termAsLeader+1), 3*time.Second); err != nil {
		deposeErr = err.Error()
	}
	store.arm()
	time.Sleep(120 * time.Millisecond)
	termBeforeHold := node.getCurrentTerm()
	stateBeforeHold := node.getState().String()

	gateOpened := false
	select {
	case <-store.entered:
		gateOpened = true
	case <-time.After(5 * time.Second):
	}
	termWhileHeld := node.getCurrentTerm()
	persistedWhileHeld, _ := store.GetUint64(keyCurrentTerm)

	// No heartbeat is delivered here: the held write is simply released.
	close(store.release)
	time.Sleep(200 * time.Millisecond)

	termAfterRelease := node.getCurrentTerm()
	persistedAfterRelease, _ := store.GetUint64(keyCurrentTerm)
	stateAfterRelease := node.getState().String()

	fmt.Printf("CA_EVENT {\"event\":\"term_control_no_heartbeat\",\"node_addr\":%q,"+
		"\"depose_err\":%q,\"term_as_leader\":%d,\"term_before_hold\":%d,"+
		"\"state_before_hold\":%q,\"gate_opened\":%t,\"term_while_held\":%d,"+
		"\"persisted_while_held\":%d,\"term_after_release\":%d,"+
		"\"persisted_after_release\":%d,\"state_after_release\":%q}\n",
		string(addr), deposeErr, termAsLeader, termBeforeHold, stateBeforeHold,
		gateOpened, termWhileHeld, persistedWhileHeld,
		termAfterRelease, persistedAfterRelease, stateAfterRelease)

	_ = node.Shutdown().Error()
}
