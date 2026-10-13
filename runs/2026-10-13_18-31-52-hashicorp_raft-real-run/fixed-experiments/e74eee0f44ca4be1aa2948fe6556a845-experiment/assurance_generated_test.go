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

// TestAssurance_RedundantSnapshotAtUnchangedIndex checks what the trigger does
// once the store sits below the snapshot index: each trigger creates another
// snapshot at the same index while no new entry has been applied.
func TestAssurance_RedundantSnapshotAtUnchangedIndex(t *testing.T) {
	conf := inmemConfig(t)
	conf.TrailingLogs = 0
	conf.SnapshotThreshold = 10000
	conf.SnapshotInterval = 100 * time.Millisecond
	c := MakeCluster(1, t, conf)
	defer c.Close()

	r := c.rafts[0]
	deadline := time.Now().Add(3 * time.Second)
	for r.State() != Leader && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if err := r.Apply([]byte("one"), conf.HeartbeatTimeout).Error(); err != nil {
		t.Fatalf("apply: %v", err)
	}
	if err := r.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}

	snaps, _ := r.snapshots.List()
	storeLast, _ := r.logs.LastIndex()
	snapIdx, _ := r.getLastSnapshot()
	applied := r.getLastApplied()
	assuranceEmit(t, map[string]interface{}{
		"event":            "emptied_state",
		"store_last":       storeLast,
		"snapshot_index":   snapIdx,
		"applied_index":    applied,
		"snapshots_stored": len(snaps),
		"should_snapshot":  r.shouldSnapshot(),
	})

	start := time.Now()
	for i := 0; i < 6; i++ {
		time.Sleep(200 * time.Millisecond)
		snaps, _ := r.snapshots.List()
		snapIdx, _ := r.getLastSnapshot()
		assuranceEmit(t, map[string]interface{}{
			"event":            "interval_sample",
			"round":            i + 1,
			"elapsed_ms":       time.Since(start).Milliseconds(),
			"store_last":       func() uint64 { v, _ := r.logs.LastIndex(); return v }(),
			"snapshot_index":   snapIdx,
			"applied_index":    r.getLastApplied(),
			"snapshots_stored": len(snaps),
			"should_snapshot":  r.shouldSnapshot(),
		})
	}
	_ = fmt.Sprintf
}
