package raft

import (
	"encoding/json"
	"fmt"
	"testing"
)

func assuranceEmit(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func assuranceMakeSnapshot(t *testing.T, store *FileSnapshotStore, term, index uint64, cfg Configuration, trans Transport) {
	t.Helper()
	sink, err := store.Create(1, index, term, cfg, 1, trans)
	if err != nil {
		t.Fatalf("create snapshot (term=%d index=%d): %v", term, index, err)
	}
	if _, err := sink.Write([]byte("state")); err != nil {
		t.Fatalf("write snapshot: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Fatalf("close snapshot: %v", err)
	}
}

// TestAssuranceSnapshotListOrder checks the SnapshotStore contract statement
// that List returns snapshots in descending order with the highest index first
// against FileSnapshotStore's ordering when two retained snapshots have
// inversely ordered (term, index) positions.
func TestAssuranceSnapshotListOrder(t *testing.T) {
	node := "n1"
	dir := t.TempDir()
	store, err := NewFileSnapshotStore(dir, 2, nil)
	if err != nil {
		t.Fatalf("NewFileSnapshotStore: %v", err)
	}
	_, trans := NewInmemTransport(NewInmemAddr())
	cfg := Configuration{}

	// First snapshot: high last-entry term, lower index.
	assuranceMakeSnapshot(t, store, 9, 50, cfg, trans)
	// Second snapshot: higher index but lower last-entry term.
	assuranceMakeSnapshot(t, store, 4, 80, cfg, trans)

	metas, err := store.List()
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	if len(metas) != 2 {
		t.Fatalf("expected both snapshots retained, got %d", len(metas))
	}
	firstIndex := metas[0].Index
	secondIndex := metas[1].Index
	maxIndex := metas[0].Index
	for _, m := range metas {
		if m.Index > maxIndex {
			maxIndex = m.Index
		}
	}
	highestFirst := firstIndex == maxIndex

	assuranceEmit(map[string]interface{}{
		"event": "snapshots_created", "node": node,
		"retained": len(metas), "both_retained": len(metas) == 2,
		"max_index": maxIndex,
	})
	assuranceEmit(map[string]interface{}{
		"event": "list_order", "node": node,
		"first_index": firstIndex, "second_index": secondIndex, "max_index": maxIndex,
		"highest_first": highestFirst,
		"first_term":    metas[0].Term, "second_term": metas[1].Term,
	})
}
