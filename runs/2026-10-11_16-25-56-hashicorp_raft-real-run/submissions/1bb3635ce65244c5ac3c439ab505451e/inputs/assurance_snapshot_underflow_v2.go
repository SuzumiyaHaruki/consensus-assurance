package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func caEmit(t *testing.T, ev map[string]interface{}) {
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func caSnapshotView(r *Raft) (count int, newestID string, newestIndex uint64) {
	snaps, err := r.snapshots.List()
	if err != nil || len(snaps) == 0 {
		return 0, "", 0
	}
	return len(snaps), snaps[0].ID, snaps[0].Index
}

func caLastSnapshotIndex(r *Raft) uint64 {
	idx, _ := r.getLastSnapshot()
	return idx
}

func caLogStoreLast(r *Raft) uint64 {
	idx, _ := r.logs.LastIndex()
	return idx
}

// TestAssuranceSnapshotIndexUnderflow drives a real InstallSnapshot recovery and
// then observes whether the recovered node's own automatic snapshot condition
// stays true while it is idle and isolated, i.e. whether a fresh snapshot is
// created repeatedly at the same index with no new applied entries.
func TestAssuranceSnapshotIndexUnderflowControlCorrelated(t *testing.T) {
	conf := inmemConfig(t)
	conf.SnapshotInterval = 40 * time.Millisecond
	conf.SnapshotThreshold = 20
	conf.TrailingLogs = 5

	c := MakeCluster(3, t, conf)
	defer c.Close()

	leader := c.Leader()
	if leader == nil {
		t.Fatalf("no leader elected")
	}
	var victim *Raft
	for _, r := range c.rafts {
		if r != leader {
			victim = r
			break
		}
	}
	if victim == nil {
		t.Fatalf("no follower available")
	}

	apply := func(prefix string, n int) {
		var last Future
		for i := 0; i < n; i++ {
			last = leader.Apply([]byte(fmt.Sprintf("%s-%d", prefix, i)), 0)
		}
		if last != nil {
			if err := last.Error(); err != nil {
				t.Fatalf("apply %s: %v", prefix, err)
			}
		}
	}

	// Prefix: warm traffic so every node snapshots (SnapshotThreshold=20,
	// TrailingLogs=5), then isolate one follower and keep writing so the leader
	// compacts past that follower's next index.
	apply("warm", 60)
	time.Sleep(400 * time.Millisecond)

	logBefore := caLogStoreLast(victim)
	snapBefore := caLastSnapshotIndex(victim)

	c.Disconnect(victim.localAddr)
	apply("behind", 140)
	time.Sleep(400 * time.Millisecond)

	c.FullyConnect()
	time.Sleep(700 * time.Millisecond)

	logAfter := caLogStoreLast(victim)
	snapAfter := caLastSnapshotIndex(victim)
	caEmit(t, map[string]interface{}{
		"event":                            "recovery_state",
		"node":                             string(victim.localID),
		"snapshot_index_before_isolation":  snapBefore,
		"log_store_last_before_isolation":  logBefore,
		"snapshot_index_after_reconnect":   snapAfter,
		"log_store_last_after_reconnect":   logAfter,
		"log_store_below_snapshot_index":   snapAfter > logAfter,
		"snapshot_advanced_over_log_store": snapAfter > logAfter && snapAfter > snapBefore,
	})

	// Isolate the recovered node so that any further snapshot in its store must
	// come from its own snapshot goroutine, not from another InstallSnapshot.
	c.Disconnect(victim.localAddr)

	_, vID0, vIdx0 := caSnapshotView(victim)
	vApplied0 := victim.getLastApplied()
	lApplied0 := leader.getLastApplied()
	_, lID0, lIdx0 := caSnapshotView(leader)

	caEmit(t, map[string]interface{}{
		"event":                "window_start",
		"node":                 string(victim.localID),
		"role":                 "recovered-node",
		"snapshot_index":       vIdx0,
		"newest_snapshot_id":   vID0,
		"log_store_last":       caLogStoreLast(victim),
		"last_snapshot_index":  caLastSnapshotIndex(victim),
		"should_snapshot":      victim.shouldSnapshot(),
		"applied_index":        vApplied0,
		"snapshot_threshold":   conf.SnapshotThreshold,
		"snapshot_interval_ms": conf.SnapshotInterval.Milliseconds(),
	})
	caEmit(t, map[string]interface{}{
		"event":               "control_window_start",
		"node":                string(leader.localID),
		"role":                "leader-control",
		"snapshot_index":      lIdx0,
		"newest_snapshot_id":  lID0,
		"log_store_last":      caLogStoreLast(leader),
		"last_snapshot_index": caLastSnapshotIndex(leader),
		"should_snapshot":     leader.shouldSnapshot(),
		"applied_index":       lApplied0,
	})

	seen := map[string]map[string]bool{
		string(victim.localID): {},
		string(leader.localID): {},
	}
	deadline := time.Now().Add(900 * time.Millisecond)
	ticks := 0
	for time.Now().Before(deadline) {
		for _, r := range []*Raft{victim, leader} {
			if _, id, _ := caSnapshotView(r); id != "" {
				seen[string(r.localID)][id] = true
			}
		}
		ticks++
		time.Sleep(40 * time.Millisecond)
	}

	for _, r := range []*Raft{victim, leader} {
		id := string(r.localID)
		_, newestID, newestIndex := caSnapshotView(r)
		appliedNow := r.getLastApplied()
		distinct := len(seen[id])
		endEvent := "recovered_window_end"
		if r != victim {
			endEvent = "control_window_end"
		}
		caEmit(t, map[string]interface{}{
			"event":                                endEvent,
			"node":                                 id,
			"role":                                 map[bool]string{true: "recovered-node", false: "leader-control"}[r == victim],
			"distinct_snapshot_ids":                distinct,
			"snapshot_created_without_new_entries": distinct >= 2 && appliedNow == map[bool]uint64{true: vApplied0, false: lApplied0}[r == victim],
			"newest_snapshot_id":                   newestID,
			"newest_snapshot_index":                newestIndex,
			"snapshot_index":                       newestIndex,
			"log_store_last":                       caLogStoreLast(r),
			"last_snapshot_index":                  caLastSnapshotIndex(r),
			"should_snapshot":                      r.shouldSnapshot(),
			"applied_index":                        appliedNow,
			"applied_delta":                        appliedNow - map[bool]uint64{true: vApplied0, false: lApplied0}[r == victim],
			"ticks":                                ticks,
		})
	}
}
