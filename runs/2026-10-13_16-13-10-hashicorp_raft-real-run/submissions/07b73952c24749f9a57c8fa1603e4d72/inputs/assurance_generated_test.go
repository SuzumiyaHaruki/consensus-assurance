package raft

import (
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

// TestAssurance_TermRegressionNaturalTiming asks how often the interleaving
// behind the durable term regression happens on its own, with no instrumented
// store holding anything open: the node is kept cycling between being deposed
// by empty heartbeats and starting its own election, while the heartbeat stream
// continues, and the term is sampled continuously for a fall below the highest
// term the node has already adopted. Any fall observed here is a monotonicity
// violation under natural timing; no fall in the window bounds the rate rather
// than refuting the mechanism.
func TestAssurance_TermRegressionNaturalTiming(t *testing.T) {
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

	maxAdopted := node.getCurrentTerm()
	deliveries := 0
	failed := 0
	samples := 0
	falls := 0
	firstFall := ""
	deadline := time.Now().Add(6 * time.Second)

	for time.Now().Before(deadline) {
		// Let an election start: stop pushing for about one election interval.
		time.Sleep(60 * time.Millisecond)
		// Then push a short burst of heartbeats, each a few terms higher, which
		// is when a write can land inside an election's read-modify-write.
		for i := 0; i < 12 && time.Now().Before(deadline); i++ {
			term := node.getCurrentTerm()
			deliveries++
			if resp, err := trans.deliverHeartbeat(newHeartbeat(term+3), 2*time.Second); err == nil && resp.Success {
				if adopted := node.getCurrentTerm(); adopted > maxAdopted {
					maxAdopted = adopted
				}
			} else {
				failed++
			}
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
			time.Sleep(2 * time.Millisecond)
		}
	}

	finalTerm := node.getCurrentTerm()
	finalState := node.getState().String()
	persisted, _ := store.GetUint64(keyCurrentTerm)

	fmt.Printf("CA_EVENT {\"event\":\"term_regression_natural\",\"node_addr\":%q,\"deliveries\":%d,"+
		"\"failed_deliveries\":%d,\"samples\":%d,\"falls\":%d,\"first_fall\":%q,"+
		"\"max_adopted\":%d,\"final_term\":%d,\"final_persisted\":%d,\"final_state\":%q}\n",
		string(addr), deliveries, failed, samples, falls, firstFall,
		maxAdopted, finalTerm, persisted, finalState)

	_ = node.Shutdown().Error()
}
