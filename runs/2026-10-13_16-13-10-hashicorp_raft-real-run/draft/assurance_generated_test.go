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

// slowTermStore is the in-memory store with a simulated durable write latency
// on the current-term key, which is the write that sits inside the candidate
// path's read-modify-write. A store that fsyncs on a busy disk behaves this
// way; the delay is a property of the environment, not a hook that holds a
// particular write open.
type slowTermStore struct {
	*InmemStore
	termWrite time.Duration
}

func (s *slowTermStore) SetUint64(key []byte, val uint64) error {
	if bytes.Equal(key, keyCurrentTerm) && s.termWrite > 0 {
		time.Sleep(s.termWrite)
	}
	return s.InmemStore.SetUint64(key, val)
}

// TestAssurance_TermRegressionSlowStore asks whether the natural rate of the
// term-regression interleaving rises when the election's term write is slow,
// which is the direction the earlier negative pointed at: the window is as wide
// as the store's write latency rather than a couple of instructions, and every
// heartbeat delivered during that latency is written inside it.
func TestAssurance_TermRegressionSlowStore(t *testing.T) {
	const termWrite = 3 * time.Millisecond

	addr, itrans := NewInmemTransport("")
	conf := inmemConfig(t)
	conf.LocalID = ServerID(addr)
	trans := &fastPathTransport{InmemTransport: itrans}
	store := &slowTermStore{InmemStore: NewInmemStore(), termWrite: termWrite}
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

	limit := time.Now().Add(10 * time.Second)
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

	maxAdopted := node.getCurrentTerm()
	deliveries := 0
	failed := 0
	samples := 0
	falls := 0
	firstFall := ""
	deadline := time.Now().Add(8 * time.Second)

	for time.Now().Before(deadline) {
		term := node.getCurrentTerm()
		deliveries++
		if resp, err := trans.deliverHeartbeat(newHeartbeat(term+3), 5*time.Second); err == nil && resp.Success {
			if adopted := node.getCurrentTerm(); adopted > maxAdopted {
				maxAdopted = adopted
			}
		} else {
			failed++
		}
		// Sample repeatedly after each delivery so a lower term written when a
		// pending slow write lands is seen before the next election raises it.
		for i := 0; i < 6 && time.Now().Before(deadline); i++ {
			cur := node.getCurrentTerm()
			samples++
			if cur > maxAdopted {
				maxAdopted = cur
			}
			if cur < maxAdopted {
				falls++
				if firstFall == "" {
					firstFall = fmt.Sprintf("adopted=%d observed=%d after %d deliveries", maxAdopted, cur, deliveries)
				}
			}
			time.Sleep(300 * time.Microsecond)
		}
	}

	finalTerm := node.getCurrentTerm()
	finalState := node.getState().String()
	persisted, _ := store.GetUint64(keyCurrentTerm)

	fmt.Printf("CA_EVENT {\"event\":\"term_regression_slow_store\",\"node_addr\":%q,"+
		"\"term_write_ms\":%d,\"deliveries\":%d,\"failed_deliveries\":%d,\"samples\":%d,"+
		"\"falls\":%d,\"first_fall\":%q,\"max_adopted\":%d,\"final_term\":%d,"+
		"\"final_persisted\":%d,\"final_state\":%q}\n",
		string(addr), termWrite.Milliseconds(), deliveries, failed, samples,
		falls, firstFall, maxAdopted, finalTerm, persisted, finalState)

	_ = node.Shutdown().Error()
}
