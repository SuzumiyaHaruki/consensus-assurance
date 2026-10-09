package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

type assuranceRecoveryFSM struct{}

func (assuranceRecoveryFSM) Apply(*Log) interface{}          { return nil }
func (assuranceRecoveryFSM) Snapshot() (FSMSnapshot, error)  { return assuranceRecoverySnapshot{}, nil }
func (assuranceRecoveryFSM) Restore(io.ReadCloser) error     { return nil }

type assuranceRecoverySnapshot struct{}

func (assuranceRecoverySnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (assuranceRecoverySnapshot) Release()                        {}

func assuranceEmit(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func assuranceSeedSnapshot(t *testing.T, store *FileSnapshotStore, term, index uint64, cfg Configuration, trans Transport) {
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

// TestAssuranceStartupRestorePicksNewestSnapshot checks whether startup recovery
// adopts the snapshot with the highest applied index when the retained pair is
// inversely ordered by (term, index).
func TestAssuranceStartupRestorePicksNewestSnapshot(t *testing.T) {
	node := "n1"
	dir := t.TempDir()
	snaps, err := NewFileSnapshotStore(dir, 2, nil)
	if err != nil {
		t.Fatalf("NewFileSnapshotStore: %v", err)
	}
	_, trans := NewInmemTransport(NewInmemAddr())
	cfg := Configuration{}

	// High last-entry term, lower index, then higher index with a lower term.
	assuranceSeedSnapshot(t, snaps, 9, 50, cfg, trans)
	assuranceSeedSnapshot(t, snaps, 4, 80, cfg, trans)
	metas, err := snaps.List()
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	maxIndex := metas[0].Index
	for _, m := range metas {
		if m.Index > maxIndex {
			maxIndex = m.Index
		}
	}

	store := NewInmemStore() // empty log and stable store: recovery must come from a snapshot
	conf := DefaultConfig()
	conf.LocalID = ServerID(node)
	conf.ProtocolVersion = 3
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 100 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.SnapshotThreshold = 100000
	conf.skipStartup = true

	r, err := NewRaft(conf, assuranceRecoveryFSM{}, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}
	applied := r.AppliedIndex()
	snapIdx, _ := r.getLastSnapshot()
	newestAdopted := applied == maxIndex

	assuranceEmit(map[string]interface{}{
		"event": "snapshots_prepared", "node": node,
		"retained": len(metas), "max_index": maxIndex, "first_listed_index": metas[0].Index,
	})
	assuranceEmit(map[string]interface{}{
		"event": "startup_recovery", "node": node,
		"applied_index": applied, "snapshot_index": snapIdx, "max_index": maxIndex,
		"newest_adopted": newestAdopted,
	})
}
