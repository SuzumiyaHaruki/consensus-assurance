package raft

import (
	"bytes"
	"encoding/json"
	"fmt"
	"testing"
)

// assuranceMonotonicStore is the real in-memory LogStore/StableStore marked as
// monotonically indexed, so installSnapshot takes the removeOldLogs branch that
// clears the log store outright.
type assuranceMonotonicStore struct {
	*InmemStore
}

func (s *assuranceMonotonicStore) IsMonotonic() bool { return true }

func assuranceSnapEmit(t *testing.T, fields map[string]interface{}) {
	blob, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(blob))
}

// TestAssuranceInstallSnapshotStaleWatermark gives a follower a log watermark
// above the snapshot it is about to install, installs a snapshot below that
// watermark on a monotonic store (so the log is cleared), and then reports the
// follower's own watermark next to the installed snapshot index and the store.
func TestAssuranceInstallSnapshotStaleWatermark(t *testing.T) {
	const node = ServerID("assurance-node")
	const snapIndex = 4
	const snapTerm = 1

	store := &assuranceMonotonicStore{InmemStore: NewInmemStore()}
	seed := make([]*Log, 0, 10)
	for i := uint64(1); i <= 10; i++ {
		seed = append(seed, &Log{Index: i, Term: 1, Type: LogCommand, Data: []byte("entry")})
	}
	if err := store.InmemStore.StoreLogs(seed); err != nil {
		t.Fatalf("seed store: %v", err)
	}

	// A well-formed FSM payload: MockFSM.Restore decodes it as [][]byte.
	payload, err := encodeMsgPack([][]byte{[]byte("snapshot-state")})
	if err != nil {
		t.Fatalf("encode snapshot payload: %v", err)
	}
	snapshotBytes := payload.Bytes()

	conf := inmemConfig(t)
	conf.skipStartup = true
	conf.LocalID = node
	_, trans := NewInmemTransport(ServerAddress(node))

	r, err := NewRaft(conf, &MockFSM{}, store, store, NewInmemSnapshotStore(), trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}
	defer func() { _ = r.Shutdown() }()
	// Run the real FSM consumer so the snapshot restore installed by the handler
	// can complete; the main loop and the snapshotter stay stopped.
	r.goFunc(r.runFSM)

	if last, term := r.getLastLog(); last != 10 || term != 1 {
		t.Fatalf("precondition: log watermark is (%d,%d), want (10,1)", last, term)
	}

	assuranceSnapEmit(t, map[string]interface{}{"event": "install_request", "node": string(node)})

	configuration := Configuration{Servers: []Server{{Suffrage: Voter, ID: node, Address: ServerAddress(node)}}}
	req := &InstallSnapshotRequest{
		RPCHeader:          r.getRPCHeader(),
		SnapshotVersion:    1,
		Term:               r.getCurrentTerm() + 1,
		LastLogIndex:       snapIndex,
		LastLogTerm:        snapTerm,
		Size:               int64(len(snapshotBytes)),
		Configuration:      EncodeConfiguration(configuration),
		ConfigurationIndex: 1,
	}
	ch := make(chan RPCResponse, 1)
	r.installSnapshot(RPC{Command: req, Reader: bytes.NewReader(snapshotBytes), RespChan: ch}, req)
	rr := <-ch
	resp, _ := rr.Response.(*InstallSnapshotResponse)
	if rr.Error != nil || resp == nil || !resp.Success {
		t.Fatalf("installSnapshot did not succeed: err=%v resp=%+v", rr.Error, resp)
	}

	raftLast, raftTerm := r.getLastLog()
	raftIndex := r.getLastIndex()
	snapIdx, snapTrm := r.getLastSnapshot()
	applied := r.getLastApplied()
	storeLast, _ := store.LastIndex()

	assuranceSnapEmit(t, map[string]interface{}{
		"event":             "store_after_install",
		"node":              string(node),
		"install_succeeded": true,
		"store_last_index":  storeLast,
		"snapshot_index":    snapIdx,
		"applied_index":     applied,
	})
	assuranceSnapEmit(t, map[string]interface{}{
		"event":               "watermark_observed",
		"node":                string(node),
		"install_succeeded":   true,
		"raft_last_log_index": raftLast,
		"raft_last_log_term":  raftTerm,
		"raft_last_index":     raftIndex,
		"snapshot_index":      snapIdx,
		"snapshot_term":       snapTrm,
		"store_last_index":    storeLast,
		"applied_index":       applied,
	})
}
