package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func assuranceEmit(t *testing.T, fields map[string]interface{}) {
	b, err := json.Marshal(fields)
	if err != nil {
		return
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssurance_RestoreOnMonotonicStore checks whether a user restore on a
// monotonic log store leaves the store emptied below the snapshot index, so the
// snapshot trigger fires with no new entry and keeps creating snapshots.
func TestAssurance_RestoreOnMonotonicStore(t *testing.T) {
	conf := inmemConfig(t)
	conf.SnapshotInterval = 150 * time.Millisecond
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:         1,
		Bootstrap:     true,
		Conf:          conf,
		MonotonicLogs: true,
	})
	defer c.Close()

	r := c.Leader()
	if err := r.Apply([]byte("one"), conf.HeartbeatTimeout).Error(); err != nil {
		t.Fatalf("apply: %v", err)
	}

	snap := r.Snapshot()
	if err := snap.Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	meta, reader, err := snap.Open()
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer reader.Close()
	meta.Index += 100

	snapsBefore, _ := r.snapshots.List()
	storeBefore, _ := r.logs.LastIndex()
	snapIdxBefore, _ := r.getLastSnapshot()
	assuranceEmit(t, map[string]interface{}{
		"event":               "before_restore",
		"commit_index":        r.getCommitIndex(),
		"applied_index":       r.getLastApplied(),
		"store_last":          storeBefore,
		"snapshot_index":      snapIdxBefore,
		"snapshots_stored":    len(snapsBefore),
		"restore_meta_index":  meta.Index,
		"should_snapshot":     r.shouldSnapshot(),
	})

	restoreErr := r.Restore(meta, reader, 5*time.Second)
	storeAfter, _ := r.logs.LastIndex()
	snapIdxAfter, _ := r.getLastSnapshot()
	assuranceEmit(t, map[string]interface{}{
		"event":            "after_restore",
		"restore_err":      fmt.Sprintf("%v", restoreErr),
		"commit_index":     r.getCommitIndex(),
		"applied_index":    r.getLastApplied(),
		"store_last":       storeAfter,
		"snapshot_index":   snapIdxAfter,
		"store_emptied":    storeAfter < snapIdxAfter,
		"should_snapshot":  r.shouldSnapshot(),
	})

	time.Sleep(700 * time.Millisecond)
	snapsLater, _ := r.snapshots.List()
	storeLater, _ := r.logs.LastIndex()
	snapIdxLater, _ := r.getLastSnapshot()
	assuranceEmit(t, map[string]interface{}{
		"event":            "after_interval",
		"applied_index":    r.getLastApplied(),
		"store_last":       storeLater,
		"snapshot_index":   snapIdxLater,
		"snapshots_stored": len(snapsLater),
		"should_snapshot":  r.shouldSnapshot(),
	})
}
