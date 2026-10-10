package raft

import (
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"testing"

	"github.com/hashicorp/go-hclog"
)

type assuranceFailingStore struct {
	LogStore

	mu      sync.Mutex
	fail    bool
	failed  int
	failMax int
}

func (s *assuranceFailingStore) StoreLogs(logs []*Log) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.fail {
		s.failed++
		if s.failed <= s.failMax {
			return errors.New("injected StoreLogs failure")
		}
		s.fail = false
	}
	return s.LogStore.StoreLogs(logs)
}

func (s *assuranceFailingStore) failNext(count int) {
	s.mu.Lock()
	s.fail = true
	s.failMax = count
	s.mu.Unlock()
}

func (s *assuranceFailingStore) failedCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.failed
}

func assuranceAppendFailureEmit(t *testing.T, value map[string]interface{}) {
	t.Helper()
	encoded, err := json.Marshal(value)
	if err != nil {
		t.Fatalf("encode event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(encoded))
}

func TestAssuranceAppendFailureKeepsLastLogConsistent(t *testing.T) {
	conf := DefaultConfig()
	conf.ProtocolVersion = ProtocolVersionMax
	conf.LocalID = ServerID("assurance-append-failure-follower")
	conf.Logger = hclog.NewNullLogger()
	conf.skipStartup = true

	store := NewInmemStore()
	snap := NewInmemSnapshotStore()
	address, transport := NewInmemTransport("")
	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       conf.LocalID,
		Address:  address,
	}}}
	if err := BootstrapCluster(conf, store, store, snap, transport, configuration); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	if err := store.StoreLog(&Log{Index: 2, Term: 1, Type: LogCommand, Data: []byte("old-2")}); err != nil {
		t.Fatalf("store 2: %v", err)
	}
	if err := store.StoreLog(&Log{Index: 3, Term: 2, Type: LogCommand, Data: []byte("old-3")}); err != nil {
		t.Fatalf("store 3: %v", err)
	}

	failing := &assuranceFailingStore{LogStore: store}
	raft, err := NewRaft(conf, &MockFSM{}, failing, store, snap, transport)
	if err != nil {
		t.Fatalf("new raft: %v", err)
	}

	assuranceAppendFailureEmit(t, map[string]interface{}{
		"event":              "append_setup",
		"node_id":            string(conf.LocalID),
		"operation":          "AppendEntriesStoreFailure",
		"initial_last_index": uint64(3),
		"initial_last_term":  uint64(2),
		"failure_model":      "StoreLogs fails after conflicting suffix deletion",
	})

	failing.failNext(1)
	request := &AppendEntriesRequest{
		RPCHeader: RPCHeader{
			ProtocolVersion: ProtocolVersionMax,
			ID:              []byte("assurance-leader"),
			Addr:            []byte("assurance-leader"),
		},
		Term:         3,
		PrevLogEntry: 0,
		PrevLogTerm:  0,
		Entries: []*Log{{
			Index: 2,
			Term:  3,
			Type:  LogCommand,
			Data:  []byte("new-2"),
		}},
	}
	rpc := RPC{Command: request, RespChan: make(chan RPCResponse, 1)}
	raft.appendEntries(rpc, request)

	cachedIndex, cachedTerm := raft.getLastLog()
	actualIndex, actualErr := failing.LastIndex()
	var conflicting Log
	conflictingErr := failing.GetLog(2, &conflicting)

	assuranceAppendFailureEmit(t, map[string]interface{}{
		"event":                      "append_failure",
		"node_id":                    string(conf.LocalID),
		"operation":                  "AppendEntriesStoreFailure",
		"store_logs_failed":          failing.failedCount() > 0,
		"cached_last_index":          cachedIndex,
		"cached_last_term":           cachedTerm,
		"actual_last_index":          actualIndex,
		"actual_last_index_error":    fmt.Sprint(actualErr),
		"conflicting_entry_readable": conflictingErr == nil,
		"cached_matches_store":       cachedIndex == actualIndex,
	})
}
