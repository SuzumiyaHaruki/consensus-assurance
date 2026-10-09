package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

// assuranceFailStore wraps an in-memory LogStore so a single StoreLogs call can
// be made to fail after a DeleteRange has already succeeded.
type assuranceFailStore struct {
	*InmemStore
	failNext bool
	failed   bool
}

func (s *assuranceFailStore) StoreLogs(logs []*Log) error {
	if s.failNext {
		s.failNext = false
		s.failed = true
		return fmt.Errorf("assurance: simulated StoreLogs failure")
	}
	return s.InmemStore.StoreLogs(logs)
}

type assuranceFSM struct{}

func (assuranceFSM) Apply(*Log) interface{}          { return nil }
func (assuranceFSM) Snapshot() (FSMSnapshot, error)  { return assuranceSnapshot{}, nil }
func (assuranceFSM) Restore(io.ReadCloser) error     { return nil }

type assuranceSnapshot struct{}

func (assuranceSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (assuranceSnapshot) Release()                        {}

func assuranceEmit(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func assuranceAppendEntries(r *Raft, req *AppendEntriesRequest) *AppendEntriesResponse {
	respCh := make(chan RPCResponse, 1)
	rpc := RPC{Command: req, RespChan: respCh}
	r.appendEntries(rpc, req)
	out := <-respCh
	if resp, ok := out.Response.(*AppendEntriesResponse); ok {
		return resp
	}
	return nil
}

func TestAssuranceFollowerLogIdentityAfterTruncationFailure(t *testing.T) {
	node := "n1"
	store := &assuranceFailStore{InmemStore: NewInmemStore()}
	seeds := []*Log{
		{Index: 1, Term: 1, Type: LogNoop},
		{Index: 2, Term: 1, Type: LogNoop},
		{Index: 3, Term: 2, Type: LogNoop},
	}
	if err := store.InmemStore.StoreLogs(seeds); err != nil {
		t.Fatalf("seed logs: %v", err)
	}

	conf := DefaultConfig()
	conf.LocalID = ServerID(node)
	conf.ProtocolVersion = 3
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 100 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.SnapshotThreshold = 100000
	conf.skipStartup = true

	_, trans := NewInmemTransport(NewInmemAddr())
	r, err := NewRaft(conf, assuranceFSM{}, store, store, NewInmemSnapshotStore(), trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}
	r.setCurrentTerm(2)
	r.setState(Follower)
	r.setLeader("", "")

	cachedBefore, termBefore := r.getLastLog()
	leaderAddr := trans.EncodePeer(ServerID(node), trans.LocalAddr())

	// Conflicting AppendEntries: entry at index 2 has term 3 while the stored
	// entry has term 1, so DeleteRange(2,3) runs; then StoreLogs fails.
	conflict := &AppendEntriesRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: 3, ID: []byte(node), Addr: leaderAddr},
		Term:         3,
		Leader:       leaderAddr,
		PrevLogEntry: 1,
		PrevLogTerm:  1,
		Entries: []*Log{
			{Index: 2, Term: 3, Type: LogNoop},
			{Index: 3, Term: 3, Type: LogNoop},
		},
	}
	store.failNext = true
	resp1 := assuranceAppendEntries(r, conflict)
	if resp1 == nil {
		t.Fatalf("no response to conflict append")
	}
	if !store.failed {
		t.Fatalf("simulated StoreLogs failure did not trigger")
	}

	cachedIdx, cachedTerm := r.getLastLog()
	storedIdx, _ := store.LastIndex()
	assuranceEmit(map[string]interface{}{
		"event": "conflict_suffix", "node": node,
		"truncated_to": 1, "store_logs_failed": true,
		"resp_success": resp1.Success,
	})
	assuranceEmit(map[string]interface{}{
		"event": "store_logs_failed", "node": node, "truncated_to": 1,
	})
	assuranceEmit(map[string]interface{}{
		"event": "cache_identity", "node": node,
		"cached_index": cachedIdx, "cached_term": cachedTerm,
		"stored_index": storedIdx,
		"consistent":   cachedIdx == storedIdx,
		"cached_before": cachedBefore, "term_before": termBefore,
	})

	// A subsequent, otherwise valid AppendEntries that starts at the truncated
	// index. A healthy follower accepts it; a stale cache makes GetLog(index)
	// fail on the removed entry and the request is rejected.
	probe := &AppendEntriesRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: 3, ID: []byte(node), Addr: leaderAddr},
		Term:         3,
		Leader:       leaderAddr,
		PrevLogEntry: 1,
		PrevLogTerm:  1,
		Entries: []*Log{
			{Index: 2, Term: 3, Type: LogNoop},
		},
	}
	resp2 := assuranceAppendEntries(r, probe)
	if resp2 == nil {
		t.Fatalf("no response to probe append")
	}
	assuranceEmit(map[string]interface{}{
		"event": "append_probe", "node": node,
		"accepted": resp2.Success, "cached_index": cachedIdx, "stored_index": storedIdx,
	})
}
