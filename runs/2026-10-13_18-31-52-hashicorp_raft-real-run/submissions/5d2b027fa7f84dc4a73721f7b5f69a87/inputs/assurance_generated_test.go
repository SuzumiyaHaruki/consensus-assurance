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

// TestAssurance_InstallSnapshotSnapshotDelta drives a fresh node to receive an
// InstallSnapshot from the leader and then samples its own snapshot trigger.
func TestAssurance_InstallSnapshotSnapshotDelta(t *testing.T) {
	conf := inmemConfig(t)
	conf.TrailingLogs = 0
	c := MakeCluster(2, t, conf)
	defer c.Close()

	leader := c.Leader()
	if err := leader.Apply([]byte("a"), conf.HeartbeatTimeout).Error(); err != nil {
		t.Fatalf("apply a: %v", err)
	}
	if err := leader.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	if err := leader.Apply([]byte("b"), conf.HeartbeatTimeout).Error(); err != nil {
		t.Fatalf("apply b: %v", err)
	}
	leaderSnap, _ := leader.getLastSnapshot()
	assuranceEmit(t, map[string]interface{}{
		"event":          "leader_prepared",
		"leader_id":      string(leader.localID),
		"snapshot_index": leaderSnap,
		"commit_index":   leader.getCommitIndex(),
	})

	c1 := MakeClusterNoBootstrap(1, t, nil)
	defer c1.Close()
	c.Merge(c1)
	c.FullyConnect()

	target := c1.rafts[0]
	future := leader.AddVoter(target.localID, target.localAddr, 0, 0)
	addErr := future.Error()

	// Let the new voter catch up fully, then isolate it so the leader can
	// snapshot and compact with no entries left above the snapshot index.
	time.Sleep(500 * time.Millisecond)
	c.Disconnect(target.localAddr)
	for i := 0; i < 3; i++ {
		if err := leader.Apply([]byte("x"), conf.HeartbeatTimeout).Error(); err != nil {
			t.Fatalf("apply x: %v", err)
		}
	}
	if err := leader.Snapshot().Error(); err != nil {
		t.Fatalf("second snapshot: %v", err)
	}
	quietSnap, _ := leader.getLastSnapshot()
	assuranceEmit(t, map[string]interface{}{
		"event":            "leader_snapshot_while_target_isolated",
		"leader_snapshot":  quietSnap,
		"leader_last_log":  leader.getLastIndex(),
		"target_isolation": string(target.localAddr),
	})
	c.FullyConnect()

	deadline := time.Now().Add(5 * time.Second)
	var installedIdx uint64
	for time.Now().Before(deadline) {
		installedIdx, _ = target.getLastSnapshot()
		if installedIdx >= quietSnap && quietSnap > 0 {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	time.Sleep(150 * time.Millisecond)
	storeLast, _ := target.logs.LastIndex()
	snapIdx, _ := target.getLastSnapshot()
	assuranceEmit(t, map[string]interface{}{
		"event":              "target_after_install",
		"addvoter_err":       fmt.Sprintf("%v", addErr),
		"target_id":          string(target.localID),
		"installed_index":    installedIdx,
		"store_last":         storeLast,
		"snapshot_index":     snapIdx,
		"applied_index":      target.getLastApplied(),
		"commit_index":       target.getCommitIndex(),
		"store_emptied":      storeLast < snapIdx,
		"should_snapshot":    target.shouldSnapshot(),
		"snapshot_threshold": conf.SnapshotThreshold,
	})
}
