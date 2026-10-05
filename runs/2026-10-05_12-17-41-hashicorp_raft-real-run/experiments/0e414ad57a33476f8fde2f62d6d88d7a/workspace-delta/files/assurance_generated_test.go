package raft

import (
	"encoding/json"
	"fmt"
	"sync"
	"testing"
)

// assuranceFailStore is the real in-memory LogStore/StableStore with a single
// controllable failure injected into StoreLogs. Reads, DeleteRange and the
// stable key/value behaviour are the unmodified InmemStore implementation.
type assuranceFailStore struct {
	*InmemStore
	mu   sync.Mutex
	fail bool
}

func (s *assuranceFailStore) StoreLogs(logs []*Log) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.fail {
		return fmt.Errorf("injected StoreLogs failure")
	}
	return s.InmemStore.StoreLogs(logs)
}

func (s *assuranceFailStore) arm() {
	s.mu.Lock()
	s.fail = true
	s.mu.Unlock()
}

func assuranceEmit(t *testing.T, fields map[string]interface{}) {
	blob, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(blob))
}

// TestAssuranceTruncateStoreFailureWatermark drives a follower that has already
// lost a conflicting suffix and whose store then rejects the replacement write,
// and reports the follower's in-memory log watermark next to the store's.
func TestAssuranceTruncateStoreFailureWatermark(t *testing.T) {
	const node = ServerID("assurance-node")

	store := &assuranceFailStore{InmemStore: NewInmemStore()}
	seed := []*Log{
		{Index: 1, Term: 1, Type: LogCommand, Data: []byte("one")},
		{Index: 2, Term: 1, Type: LogCommand, Data: []byte("two")},
		{Index: 3, Term: 2, Type: LogCommand, Data: []byte("three")},
	}
	if err := store.InmemStore.StoreLogs(seed); err != nil {
		t.Fatalf("seed store: %v", err)
	}

	conf := inmemConfig(t)
	conf.skipStartup = true
	conf.LocalID = node
	_, trans := NewInmemTransport(ServerAddress(node))

	r, err := NewRaft(conf, &MockFSM{}, store, store, NewInmemSnapshotStore(), trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}
	defer func() { _ = r.Shutdown() }()

	if last, _ := store.LastIndex(); last != 3 {
		t.Fatalf("precondition: seeded store last index is %d, want 3", last)
	}
	if last, term := r.getLastLog(); last != 3 || term != 2 {
		t.Fatalf("precondition: raft log watermark is (%d,%d), want (3,2)", last, term)
	}

	// Admission of the operation whose completion is observed.
	assuranceEmit(t, map[string]interface{}{"event": "append_request", "node": string(node)})

	// The store will now reject the replacement entries while still allowing the
	// conflict deletion that happens first inside appendEntries.
	store.arm()

	req := &AppendEntriesRequest{
		RPCHeader:         r.getRPCHeader(),
		Term:              r.getCurrentTerm() + 1,
		PrevLogEntry:      2,
		PrevLogTerm:       1,
		Entries:           []*Log{{Index: 3, Term: 5, Type: LogCommand, Data: []byte("replacement")}},
		LeaderCommitIndex: 0,
	}
	ch := make(chan RPCResponse, 1)
	r.appendEntries(RPC{Command: req, RespChan: ch}, req)
	resp, _ := (<-ch).Response.(*AppendEntriesResponse)

	raftLast, raftTerm := r.getLastLog()
	raftIndex := r.getLastIndex()
	storeLast, _ := store.LastIndex()

	assuranceEmit(t, map[string]interface{}{
		"event":            "store_after_failure",
		"node":             string(node),
		"write_failed":     !resp.Success,
		"store_last_index": storeLast,
	})
	assuranceEmit(t, map[string]interface{}{
		"event":               "watermark_observed",
		"node":                string(node),
		"write_failed":        !resp.Success,
		"raft_last_log_index": raftLast,
		"raft_last_log_term":  raftTerm,
		"raft_last_index":     raftIndex,
		"store_last_index":    storeLast,
		"reported_success":    resp.Success,
	})
}
