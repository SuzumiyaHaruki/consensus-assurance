package raft

import (
	"fmt"
	"io"
	"sync"
	"testing"
	"time"
)

// stallReader is the freeze handshake: its first Read signals and then blocks
// until released, so a handler that reads from it cannot return.
type stallReader struct {
	started chan struct{}
	release chan struct{}
	once    sync.Once
}

func (s *stallReader) Read(p []byte) (int, error) {
	s.once.Do(func() { close(s.started) })
	<-s.release
	return 0, io.ErrUnexpectedEOF
}

// fastPathTransport forwards everything to an in-memory transport but, like the
// network transport, installs and honours a heartbeat handler: a strictly empty
// AppendEntries request is dispatched to that handler on the caller's
// goroutine, and the response is returned to the caller. The in-memory
// transport's own SetHeartbeatHandler is a no-op, which is why this wrapper
// exists.
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

// deliverHeartbeat mirrors the network transport's classification and dispatch.
func (t *fastPathTransport) deliverHeartbeat(req *AppendEntriesRequest) (*AppendEntriesResponse, error) {
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
	r := <-respCh
	if r.Error != nil {
		return nil, r.Error
	}
	resp, ok := r.Response.(*AppendEntriesResponse)
	if !ok {
		return nil, fmt.Errorf("unexpected heartbeat response type")
	}
	return resp, nil
}

// TestAssurance_HeartbeatFastPathThread asks whether the heartbeat fast path
// runs appendEntries outside the main thread, by occupying the main loop
// deterministically and then delivering one empty heartbeat with a higher term
// the way a fast-path transport would, on the caller's goroutine.
func TestAssurance_HeartbeatFastPathThread(t *testing.T) {
	addr, itrans := NewInmemTransport("")
	conf := inmemConfig(t)
	conf.LocalID = ServerID(addr)
	trans := &fastPathTransport{InmemTransport: itrans}
	store := NewInmemStore()
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

	// Occupy the main loop through the public Restore path.
	reader := &stallReader{started: make(chan struct{}), release: make(chan struct{})}
	restoreErr := make(chan error, 1)
	go func() {
		restoreErr <- node.Restore(&SnapshotMeta{Version: 1, ID: "assurance-fastpath", Index: 1, Term: 1, Size: 1}, reader, 0)
	}()
	handshake := "inside_restore_read"
	select {
	case <-reader.started:
	case <-time.After(5 * time.Second):
		handshake = "timeout"
	}

	termBefore := node.getCurrentTerm()
	stateBefore := node.getState().String()

	peerAddr := trans.EncodePeer(ServerID("peer-1"), ServerAddress("peer-1"))
	req := &AppendEntriesRequest{
		RPCHeader: RPCHeader{
			ProtocolVersion: conf.ProtocolVersion,
			ID:              []byte("peer-1"),
			Addr:            peerAddr,
		},
		Term:   termBefore + 1,
		Leader: peerAddr,
	}

	hbErr := ""
	hbSuccess := false
	if resp, err := trans.deliverHeartbeat(req); err != nil {
		hbErr = err.Error()
	} else {
		hbSuccess = resp.Success
	}

	// Sampled while the main loop is still inside the restore handler.
	termDuring := node.getCurrentTerm()
	stateDuring := node.getState().String()

	close(reader.release)
	restoreResult := ""
	select {
	case err := <-restoreErr:
		if err != nil {
			restoreResult = err.Error()
		}
	case <-time.After(3 * time.Second):
		restoreResult = "restore still blocked"
	}

	termAfterLoop := node.getCurrentTerm()
	stateAfterLoop := node.getState().String()

	fmt.Printf("CA_EVENT {\"event\":\"heartbeat_fast_path\",\"node_addr\":%q,\"freeze_handshake\":%q,"+
		"\"heartbeat_err\":%q,\"heartbeat_success\":%t,\"heartbeat_term\":%d,"+
		"\"term_before\":%d,\"state_before\":%q,\"term_while_loop_blocked\":%d,"+
		"\"state_while_loop_blocked\":%q,\"term_after_release\":%d,\"state_after_release\":%q,"+
		"\"restore_after_release\":%q}\n",
		string(addr), handshake, hbErr, hbSuccess, req.Term,
		termBefore, stateBefore, termDuring, stateDuring,
		termAfterLoop, stateAfterLoop, restoreResult)

	_ = node.Shutdown().Error()
}
