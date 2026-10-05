package raft

import (
	"encoding/json"
	"fmt"
	"testing"
)

func assuranceRollbackEmit(t *testing.T, fields map[string]interface{}) {
	blob, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(blob))
}

// TestAssuranceConfigRollbackAfterTruncation builds a follower whose log carries
// a committed configuration at index 1 and an uncommitted configuration at
// index 3, then drives a well-formed conflicting append at index 3 so the
// handler truncates the suffix and resets the latest configuration to the
// committed one, and reports the configuration state it keeps.
func TestAssuranceConfigRollbackAfterTruncation(t *testing.T) {
	const node = ServerID("assurance-node")
	const other = ServerID("assurance-other")

	committedCfg := Configuration{Servers: []Server{{Suffrage: Voter, ID: node, Address: ServerAddress(node)}}}
	uncommittedCfg := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: node, Address: ServerAddress(node)},
		{Suffrage: Nonvoter, ID: other, Address: ServerAddress(other)},
	}}

	store := NewInmemStore()
	if err := store.StoreLogs([]*Log{
		{Index: 1, Term: 1, Type: LogConfiguration, Data: EncodeConfiguration(committedCfg)},
		{Index: 2, Term: 2, Type: LogCommand, Data: []byte("command")},
		{Index: 3, Term: 2, Type: LogConfiguration, Data: EncodeConfiguration(uncommittedCfg)},
	}); err != nil {
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

	if r.configurations.latestIndex != 3 || r.configurations.committedIndex != 1 {
		t.Fatalf("precondition: latest/committed configuration indexes are %d/%d, want 3/1",
			r.configurations.latestIndex, r.configurations.committedIndex)
	}

	assuranceRollbackEmit(t, map[string]interface{}{
		"event": "truncation_request",
		"node":  string(node),
	})

	req := &AppendEntriesRequest{
		RPCHeader:         r.getRPCHeader(),
		Term:              r.getCurrentTerm() + 1,
		PrevLogEntry:      2,
		PrevLogTerm:       2,
		Entries:           []*Log{{Index: 3, Term: 9, Type: LogCommand, Data: []byte("replacement")}},
		LeaderCommitIndex: 0,
	}
	ch := make(chan RPCResponse, 1)
	r.appendEntries(RPC{Command: req, RespChan: ch}, req)
	rr := <-ch
	resp, _ := rr.Response.(*AppendEntriesResponse)
	if rr.Error != nil || resp == nil || !resp.Success {
		t.Fatalf("appendEntries did not succeed: err=%v resp=%+v", rr.Error, resp)
	}

	var entry3 Log
	err3 := store.GetLog(3, &entry3)
	entry3Type := -1
	if err3 == nil {
		entry3Type = int(entry3.Type)
	}

	latestIdx := r.configurations.latestIndex
	committedIdx := r.configurations.committedIndex
	published := r.getLatestConfiguration()

	assuranceRollbackEmit(t, map[string]interface{}{
		"event":                "config_after_truncation",
		"node":                 string(node),
		"truncation_succeeded": true,
		"committed_index":      committedIdx,
		"latest_index":         latestIdx,
		"last_log_index":       r.getLastIndex(),
	})
	assuranceRollbackEmit(t, map[string]interface{}{
		"event":                "config_observed",
		"node":                 string(node),
		"truncation_succeeded": true,
		"latest_index":         latestIdx,
		"committed_index":      committedIdx,
		"published_servers":    len(published.Servers),
		"entry3_type":          entry3Type,
		"entry3_term":          entry3.Term,
		"last_log_index":       r.getLastIndex(),
	})
}
