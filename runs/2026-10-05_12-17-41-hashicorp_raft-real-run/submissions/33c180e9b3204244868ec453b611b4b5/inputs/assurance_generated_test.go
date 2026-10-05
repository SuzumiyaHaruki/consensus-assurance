package raft

import (
	"encoding/json"
	"fmt"
	"testing"
)

func assuranceTriggerEmit(t *testing.T, fields map[string]interface{}) {
	blob, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal CA_EVENT: %v", err)
	}
	fmt.Println("CA_EVENT " + string(blob))
}

// TestAssuranceSnapshotTriggerAfterClearedLog restores a node from a snapshot
// while its log store holds nothing, so the last snapshot index is above the
// log store's last index, and then asks the real periodic trigger whether a new
// snapshot is due.
func TestAssuranceSnapshotTriggerAfterClearedLog(t *testing.T) {
	const node = ServerID("assurance-node")
	const snapIndex = 4
	const snapTerm = 1

	configuration := Configuration{Servers: []Server{{Suffrage: Voter, ID: node, Address: ServerAddress(node)}}}

	store := NewInmemStore() // empty log store
	_, trans := NewInmemTransport(ServerAddress(node))

	// Place a snapshot in the store so NewRaft performs a real restore and sets
	// the last snapshot coordinate above the empty log.
	snaps := NewInmemSnapshotStore()
	sink, err := snaps.Create(1, snapIndex, snapTerm, configuration, 1, trans)
	if err != nil {
		t.Fatalf("create snapshot: %v", err)
	}
	payload, err := encodeMsgPack([][]byte{[]byte("snapshot-state")})
	if err != nil {
		t.Fatalf("encode payload: %v", err)
	}
	if _, err := sink.Write(payload.Bytes()); err != nil {
		t.Fatalf("write snapshot: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Fatalf("close snapshot: %v", err)
	}

	conf := inmemConfig(t)
	conf.skipStartup = true
	conf.LocalID = node

	r, err := NewRaft(conf, &MockFSM{}, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}

	logLast, err := store.LastIndex()
	if err != nil {
		t.Fatalf("store LastIndex: %v", err)
	}
	snapIdx, snapTrm := r.getLastSnapshot()
	if snapIdx != snapIndex || snapTrm != snapTerm {
		t.Fatalf("precondition: restored snapshot is (%d,%d), want (%d,%d)", snapIdx, snapTrm, snapIndex, snapTerm)
	}
	if logLast != 0 {
		t.Fatalf("precondition: log store last index is %d, want 0", logLast)
	}

	assuranceTriggerEmit(t, map[string]interface{}{
		"event":                "snapshot_state",
		"node":                 string(node),
		"restored":             true,
		"log_store_last_index": logLast,
		"snapshot_index":       snapIdx,
		"threshold":            r.config().SnapshotThreshold,
	})
	assuranceTriggerEmit(t, map[string]interface{}{
		"event":                "trigger_observed",
		"node":                 string(node),
		"restored":             true,
		"snapshot_due":         r.shouldSnapshot(),
		"log_store_last_index": logLast,
		"snapshot_index":       snapIdx,
	})
}
