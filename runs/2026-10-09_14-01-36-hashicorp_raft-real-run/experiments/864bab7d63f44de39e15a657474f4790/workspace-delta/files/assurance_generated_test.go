package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"testing"
	"time"
)

// assuranceMonotonicStore marks an in-memory log store as monotonic, so the
// snapshot-install path resets the log store instead of keeping trailing logs.
type assuranceMonotonicStore struct {
	*InmemStore
}

func (s *assuranceMonotonicStore) IsMonotonic() bool { return true }

type assuranceFSM struct{}

func (assuranceFSM) Apply(*Log) interface{}         { return nil }
func (assuranceFSM) Snapshot() (FSMSnapshot, error) { return assuranceSnapshot{}, nil }
func (assuranceFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceSnapshot struct{}

func (assuranceSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (assuranceSnapshot) Release()                        {}

func assuranceEmit(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func assuranceInstallSnapshot(r *Raft, req *InstallSnapshotRequest, data io.Reader) (*InstallSnapshotResponse, error) {
	respCh := make(chan RPCResponse, 1)
	rpc := RPC{Command: req, Reader: data, RespChan: respCh}
	r.installSnapshot(rpc, req)
	out := <-respCh
	if resp, ok := out.Response.(*InstallSnapshotResponse); ok {
		return resp, out.Error
	}
	return nil, out.Error
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

func TestAssuranceSnapshotInstallLogIdentity(t *testing.T) {
	node := "n1"
	store := &assuranceMonotonicStore{InmemStore: NewInmemStore()}
	seeds := []*Log{
		{Index: 1, Term: 1, Type: LogNoop},
		{Index: 2, Term: 1, Type: LogNoop},
		{Index: 3, Term: 2, Type: LogNoop},
		{Index: 4, Term: 2, Type: LogNoop},
		{Index: 5, Term: 2, Type: LogNoop},
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
	snaps := NewInmemSnapshotStore()
	r, err := NewRaft(conf, assuranceFSM{}, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}
	// Only the FSM goroutine is started; the main loop is not, so the install
	// handler is the sole actor.
	r.goFunc(r.runFSM)
	defer func() { _ = r.Shutdown().Error() }()

	cfg := Configuration{Servers: []Server{{ID: ServerID(node), Address: trans.LocalAddr(), Suffrage: Voter}}}
	r.setLatestConfiguration(cfg, 1)
	r.setCommittedConfiguration(cfg, 1)
	r.setCurrentTerm(3)
	r.setState(Follower)

	cachedBefore, termBefore := r.getLastLog()
	storedBefore, _ := store.LastIndex()
	_ = termBefore

	// A remote snapshot at index 2, below the follower's cached last log index.
	req := &InstallSnapshotRequest{
		RPCHeader:          RPCHeader{ProtocolVersion: 3, ID: []byte(node), Addr: trans.EncodePeer(ServerID(node), trans.LocalAddr())},
		SnapshotVersion:    1,
		Term:               3,
		Leader:             trans.EncodePeer(ServerID(node), trans.LocalAddr()),
		LastLogIndex:       2,
		LastLogTerm:        1,
		Peers:              encodePeers(cfg, trans),
		Configuration:      EncodeConfiguration(cfg),
		ConfigurationIndex: 1,
		Size:               3,
	}
	resp1, installErr := assuranceInstallSnapshot(r, req, strings.NewReader("abc"))
	if resp1 == nil {
		t.Fatalf("no response to install snapshot: %v", installErr)
	}
	cachedAfter, termAfter := r.getLastLog()
	storedAfter, _ := store.LastIndex()
	snapIdx, snapTerm := r.getLastSnapshot()
	lastEntryIdx, lastEntryTerm := r.getLastEntry()

	assuranceEmit(map[string]interface{}{
		"event": "snapshot_installed", "node": node, "success": resp1.Success,
		"install_error": fmt.Sprint(installErr),
		"snapshot_index": req.LastLogIndex,
		"cached_before": cachedBefore, "stored_before": storedBefore,
	})
	assuranceEmit(map[string]interface{}{
		"event": "post_install_identity", "node": node,
		"cached_index": cachedAfter, "cached_term": termAfter,
		"stored_index": storedAfter, "snapshot_index": snapIdx, "snapshot_term": snapTerm,
		"last_entry_index": lastEntryIdx, "last_entry_term": lastEntryTerm,
	})

	// The leader, after a successful install, sends AppendEntries from the
	// snapshot index; an identity-consistent follower accepts them.
	probe := &AppendEntriesRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: 3, ID: []byte(node), Addr: req.Addr},
		Term:         3,
		Leader:       req.Leader,
		PrevLogEntry: 2,
		PrevLogTerm:  1,
		Entries: []*Log{
			{Index: 3, Term: 3, Type: LogNoop},
		},
	}
	resp2 := assuranceAppendEntries(r, probe)
	if resp2 == nil {
		t.Fatalf("no response to probe append")
	}
	assuranceEmit(map[string]interface{}{
		"event": "recovery_probe", "node": node,
		"accepted": resp2.Success, "cached_index": cachedAfter, "stored_index": storedAfter,
		"snapshot_index": snapIdx,
	})
}
