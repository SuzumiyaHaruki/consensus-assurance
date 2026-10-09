package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

type assuranceFSM2 struct{}

func (assuranceFSM2) Apply(*Log) interface{}            { return nil }
func (assuranceFSM2) Snapshot() (FSMSnapshot, error)    { return assuranceSnapshot2{}, nil }
func (assuranceFSM2) Restore(io.ReadCloser) error       { return nil }

type assuranceSnapshot2 struct{}

func (assuranceSnapshot2) Persist(sink SnapshotSink) error { return sink.Close() }
func (assuranceSnapshot2) Release()                        {}

func assuranceEmit(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func assuranceAppendEntriesCall(r *Raft, req *AppendEntriesRequest) (*AppendEntriesResponse, error) {
	respCh := make(chan RPCResponse, 1)
	rpc := RPC{Command: req, RespChan: respCh}
	r.appendEntries(rpc, req)
	out := <-respCh
	if resp, ok := out.Response.(*AppendEntriesResponse); ok {
		return resp, out.Error
	}
	return nil, out.Error
}

// TestAssuranceAppendConfigErrorLeavesStaleCache exercises the second error
// return of appendEntries: entries are stored successfully, but a configuration
// entry fails to decode, so the handler returns before setLastLog updates the
// cached last log identity.
func TestAssuranceAppendConfigErrorLeavesStaleCache(t *testing.T) {
	node := "n1"
	store := NewInmemStore()
	seeds := []*Log{
		{Index: 1, Term: 1, Type: LogNoop},
		{Index: 2, Term: 1, Type: LogNoop},
		{Index: 3, Term: 2, Type: LogNoop},
	}
	if err := store.StoreLogs(seeds); err != nil {
		t.Fatalf("seed logs: %v", err)
	}

	_, trans := NewInmemTransport(NewInmemAddr())
	localAddr := trans.LocalAddr()
	conf := DefaultConfig()
	conf.LocalID = ServerID(localAddr)
	conf.ProtocolVersion = 2 // with < 3 the LocalID must be the network address
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 100 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.SnapshotThreshold = 100000
	conf.skipStartup = true

	r, err := NewRaft(conf, assuranceFSM2{}, store, store, NewInmemSnapshotStore(), trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}
	r.setCurrentTerm(2)
	r.setState(Follower)
	r.setLeader("", "")

	cachedBefore, _ := r.getLastLog()
	leaderAddr := trans.EncodePeer(ServerID(localAddr), localAddr)

	// A conflicting entry that will be stored, then fail configuration decoding.
	conflict := &AppendEntriesRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: 2, ID: []byte(localAddr), Addr: leaderAddr},
		Term:         3,
		Leader:       leaderAddr,
		PrevLogEntry: 1,
		PrevLogTerm:  1,
		Entries: []*Log{
			{Index: 2, Term: 3, Type: LogAddPeerDeprecated, Data: []byte{0xC1, 0xC1}},
		},
	}
	resp1, err1 := assuranceAppendEntriesCall(r, conflict)
	if resp1 == nil {
		t.Fatalf("no response to conflict append: %v", err1)
	}
	cachedAfter, cachedTerm := r.getLastLog()
	storedAfter, _ := store.LastIndex()
	consistent := cachedAfter == storedAfter

	assuranceEmit(map[string]interface{}{
		"event": "config_entry_error", "node": node,
		"rpc_error": fmt.Sprint(err1), "success": resp1.Success,
		"cached_before": cachedBefore,
	})
	assuranceEmit(map[string]interface{}{
		"event": "error_path_identity", "node": node,
		"cached_index": cachedAfter, "cached_term": cachedTerm,
		"stored_index": storedAfter, "consistent": consistent,
	})

	// The leader retries the next entry from the follower's surviving prefix; a
	// consistent follower stores it, a stale cache makes GetLog fail on the
	// removed index and the request is rejected.
	probe := &AppendEntriesRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: 2, ID: []byte(localAddr), Addr: leaderAddr},
		Term:         3,
		Leader:       leaderAddr,
		PrevLogEntry: 2,
		PrevLogTerm:  3,
		Entries: []*Log{
			{Index: 3, Term: 3, Type: LogNoop},
		},
	}
	resp2, err2 := assuranceAppendEntriesCall(r, probe)
	if resp2 == nil {
		t.Fatalf("no response to probe append: %v", err2)
	}
	assuranceEmit(map[string]interface{}{
		"event": "error_path_probe", "node": node,
		"accepted": resp2.Success, "cached_index": cachedAfter, "stored_index": storedAfter,
	})
}
