package raft

import (
	"fmt"
	"sync"
	"testing"
	"time"
)

// fastPathTransport forwards everything to an in-memory transport but, like the
// network transport, installs and honours a heartbeat handler: a strictly empty
// AppendEntries request is dispatched to that handler on the caller's
// goroutine, and the caller then waits for a response on the channel it
// supplied, which is what the network transport's connection goroutine does.
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

// deliverHeartbeat mirrors the network transport's classification, dispatch and
// response wait. It returns the response or an error, including when no
// response arrives inside the given bound.
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

// TestAssurance_HeartbeatAfterShutdown asks what the fast path does with an
// accepted heartbeat once the node has been shut down while its transport is
// still open, which is the state a caller leaves the node in when it does not
// wait on the shutdown future.
func TestAssurance_HeartbeatAfterShutdown(t *testing.T) {
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

	// Control: the same delivery path while the node is live.
	termBefore := node.getCurrentTerm()
	controlErr := ""
	controlSuccess := false
	if resp, err := trans.deliverHeartbeat(newHeartbeat(termBefore+1), 3*time.Second); err != nil {
		controlErr = err.Error()
	} else {
		controlSuccess = resp.Success
	}
	termAfterControl := node.getCurrentTerm()
	stateAfterControl := node.getState().String()

	// Shut the node down but leave its transport open, then deliver one more
	// heartbeat on the same fast path.
	shutdownFuture := node.Shutdown()
	time.Sleep(200 * time.Millisecond)

	termAfterShutdown := node.getCurrentTerm()
	stateAfterShutdown := node.getState().String()

	postErr := ""
	postSuccess := false
	postWaitStart := time.Now()
	if resp, err := trans.deliverHeartbeat(newHeartbeat(termAfterShutdown+1), 2*time.Second); err != nil {
		postErr = err.Error()
	} else {
		postSuccess = resp.Success
	}
	postWaitMs := time.Since(postWaitStart).Milliseconds()
	termAfterPost := node.getCurrentTerm()

	fmt.Printf("CA_EVENT {\"event\":\"heartbeat_after_shutdown\",\"node_addr\":%q,"+
		"\"control_err\":%q,\"control_success\":%t,\"term_before\":%d,\"term_after_control\":%d,"+
		"\"state_after_control\":%q,\"term_after_shutdown\":%d,\"state_after_shutdown\":%q,"+
		"\"post_shutdown_err\":%q,\"post_shutdown_success\":%t,\"post_shutdown_wait_ms\":%d,"+
		"\"term_after_post\":%d}\n",
		string(addr), controlErr, controlSuccess, termBefore, termAfterControl,
		stateAfterControl, termAfterShutdown, stateAfterShutdown,
		postErr, postSuccess, postWaitMs, termAfterPost)

	_ = shutdownFuture.Error()
}
