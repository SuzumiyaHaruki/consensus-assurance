// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"sync/atomic"
	"testing"
	"time"
)

// assuranceFailStore wraps a log store and fails one StoreLogs call on demand.
type assuranceFailStore struct {
	LogStore
	fail atomic.Bool
}

func (s *assuranceFailStore) StoreLogs(logs []*Log) error {
	if s.fail.CompareAndSwap(true, false) {
		return fmt.Errorf("assurance injected StoreLogs failure")
	}
	return s.LogStore.StoreLogs(logs)
}

func assuranceEmit(t *testing.T, event map[string]interface{}) {
	b, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	t.Log("CA_EVENT " + string(b))
}

// TestAssuranceAppendStoreFailure asks what a follower is left with when the
// AppendEntries conflict path deletes a suffix and the following StoreLogs
// fails, and whether a later AppendEntries carrying the full log can repair it.
func TestAssuranceAppendStoreFailure(t *testing.T) {
	assuranceAppendStoreTrial(t, "injected-store-failure", true)
	assuranceAppendStoreTrial(t, "control-no-failure", false)
}

func assuranceAppendStoreTrial(t *testing.T, name string, inject bool) {
	conf := inmemConfig(t)
	conf.LocalID = "assurance-B"
	conf.HeartbeatTimeout = 2 * time.Second
	conf.ElectionTimeout = 2 * time.Second
	conf.LeaderLeaseTimeout = 2 * time.Second

	inner := NewInmemStore()
	store := &assuranceFailStore{LogStore: inner}
	_, followerTrans := NewInmemTransport("assurance-B")
	r, err := NewRaft(conf, &MockFSM{}, store, inner, NewInmemSnapshotStore(), followerTrans)
	if err != nil {
		t.Fatalf("new raft: %v", err)
	}
	defer r.Shutdown()

	_, leaderTrans := NewInmemTransport("assurance-A")
	leaderTrans.Connect("assurance-B", followerTrans)

	// A leader at term 1 fills the follower's log with three entries.
	baseline := []*Log{
		{Index: 1, Term: 1, Type: LogCommand, Data: []byte("a")},
		{Index: 2, Term: 1, Type: LogCommand, Data: []byte("b")},
		{Index: 3, Term: 1, Type: LogCommand, Data: []byte("c")},
	}
	// A later leader at term 2 replaces both of those entries, which makes the
	// follower delete its suffix before storing.
	conflict := []*Log{
		{Index: 2, Term: 2, Type: LogCommand, Data: []byte("b2")},
		{Index: 3, Term: 2, Type: LogCommand, Data: []byte("c2")},
	}

	assuranceEmit(t, map[string]interface{}{
		"event":            "assurance_append_store_setup",
		"case":             name,
		"local_id":         string(r.localID),
		"heartbeat_ms":     conf.HeartbeatTimeout.Milliseconds(),
		"election_ms":      conf.ElectionTimeout.Milliseconds(),
		"baseline_entries": len(baseline),
		"conflict_entries": len(conflict),
	})

	resp := &AppendEntriesResponse{}
	req := &AppendEntriesRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: ProtocolVersionMax, ID: []byte("assurance-A"), Addr: []byte("assurance-A")},
		Term:         1,
		PrevLogEntry: 0,
		PrevLogTerm:  0,
		Entries:      baseline,
	}
	callErr := leaderTrans.AppendEntries("assurance-B", "assurance-B", req, resp)
	if callErr != nil {
		t.Fatalf("%s baseline append: %v", name, callErr)
	}

	// Arm the failure, then send the conflicting suffix.
	store.fail.Store(inject)
	resp2 := &AppendEntriesResponse{}
	req2 := &AppendEntriesRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: ProtocolVersionMax, ID: []byte("assurance-A"), Addr: []byte("assurance-A")},
		Term:         2,
		PrevLogEntry: 1,
		PrevLogTerm:  1,
		Entries:      conflict,
	}
	err2 := leaderTrans.AppendEntries("assurance-B", "assurance-B", req2, resp2)
	assuranceEmit(t, map[string]interface{}{
		"event":                 "assurance_append_store_conflict",
		"case":                  name,
		"failure_armed":         inject,
		"rpc_error":             errString(err2),
		"resp_success":          resp2.Success,
		"resp_last_log":         resp2.LastLog,
		"in_memory_last_index":  r.getLastIndex(),
		"store_last_index":      storeLastIndex(inner),
		"store_has_index_2":     storeHasIndex(inner, 2),
	})

	time.Sleep(50 * time.Millisecond)

	// A leader whose replication stair has reached the start of its log sends
	// the whole log; for a consistent follower this is a plain re-append.
	resp3 := &AppendEntriesResponse{}
	req3 := &AppendEntriesRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: ProtocolVersionMax, ID: []byte("assurance-A"), Addr: []byte("assurance-A")},
		Term:         2,
		PrevLogEntry: 0,
		PrevLogTerm:  0,
		Entries:      baseline,
	}
	err3 := leaderTrans.AppendEntries("assurance-B", "assurance-B", req3, resp3)
	assuranceEmit(t, map[string]interface{}{
		"event":                 "assurance_append_store_repair",
		"case":                  name,
		"failure_armed":         false,
		"rpc_error":             errString(err3),
		"resp_success":          resp3.Success,
		"resp_last_log":         resp3.LastLog,
		"in_memory_last_index":  r.getLastIndex(),
		"store_last_index":      storeLastIndex(inner),
		"store_has_index_2":     storeHasIndex(inner, 2),
	})

	// A leader whose nextIndex for this peer still points past the deleted
	// suffix appends the next entry: the conflict loop trusts the stale
	// in-memory last index and never reads the gap the store now holds.
	resp4 := &AppendEntriesResponse{}
	req4 := &AppendEntriesRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: ProtocolVersionMax, ID: []byte("assurance-A"), Addr: []byte("assurance-A")},
		Term:         2,
		PrevLogEntry: 3,
		PrevLogTerm:  1,
		Entries:      []*Log{{Index: 4, Term: 2, Type: LogCommand, Data: []byte("d")}},
	}
	err4 := leaderTrans.AppendEntries("assurance-B", "assurance-B", req4, resp4)
	assuranceEmit(t, map[string]interface{}{
		"event":                "assurance_append_store_tip_append",
		"case":                 name,
		"rpc_error":            errString(err4),
		"resp_success":         resp4.Success,
		"resp_last_log":        resp4.LastLog,
		"in_memory_last_index": r.getLastIndex(),
		"store_last_index":     storeLastIndex(inner),
		"store_has_index_2":    storeHasIndex(inner, 2),
		"store_has_index_4":    storeHasIndex(inner, 4),
	})
}

func errString(err error) string {
	if err == nil {
		return "nil"
	}
	return err.Error()
}

func storeLastIndex(store LogStore) uint64 {
	idx, err := store.LastIndex()
	if err != nil {
		return 0
	}
	return idx
}

func storeHasIndex(store LogStore, idx uint64) bool {
	var l Log
	return store.GetLog(idx, &l) == nil
}
