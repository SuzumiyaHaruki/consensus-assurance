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

// TestAssurance_SnapshotDeltaAfterCompaction checks whether a node whose log
// store was emptied by compaction still reports that it should snapshot,
// although its snapshot index already covers every committed entry.
func TestAssurance_SnapshotDeltaAfterCompaction(t *testing.T) {
	conf := inmemConfig(t)
	conf.TrailingLogs = 0
	conf.SnapshotThreshold = 10000
	conf.SnapshotInterval = time.Hour
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
	if err := r.Apply([]byte("two"), conf.HeartbeatTimeout).Error(); err != nil {
		t.Fatalf("apply: %v", err)
	}
	com := r.getCommitIndex()
	storeLast, _ := r.logs.LastIndex()
	snapIdx, _ := r.getLastSnapshot()
	assuranceEmit(t, map[string]interface{}{
		"event":           "control_before_snapshot",
		"commit_index":    com,
		"store_last":      storeLast,
		"snapshot_index":  snapIdx,
		"should_snapshot": r.shouldSnapshot(),
	})

	snapErr := r.Snapshot().Error()
	storeLast2, _ := r.logs.LastIndex()
	snapIdx2, _ := r.getLastSnapshot()
	assuranceEmit(t, map[string]interface{}{
		"event":           "after_snapshot_and_compaction",
		"snapshot_err":    fmt.Sprintf("%v", snapErr),
		"commit_index":    r.getCommitIndex(),
		"applied_index":   r.getLastApplied(),
		"store_last":      storeLast2,
		"snapshot_index":  snapIdx2,
		"store_emptied":   storeLast2 < snapIdx2,
		"should_snapshot": r.shouldSnapshot(),
	})
}
