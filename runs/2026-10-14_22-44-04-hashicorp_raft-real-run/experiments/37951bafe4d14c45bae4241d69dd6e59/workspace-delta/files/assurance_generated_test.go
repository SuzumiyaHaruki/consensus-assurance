// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

func liveStallEmit(fields map[string]interface{}) {
	b, err := json.Marshal(fields)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceLiveRestoreCommittedLogsStall reaches the constructor stall through
// ordinary cluster operations: a follower that has been running with
// Config.RestoreCommittedLogs enabled accumulates a staged commit index far above
// its last snapshot, is shut down, and is then restarted with a small
// MaxAppendEntries so its replay needs more batches than the FSM mutation channel
// holds; the same restart without the feature is the control.
func TestAssuranceLiveRestoreCommittedLogsStall(t *testing.T) {
	const mode = "live_restart_after_long_gap"
	ids := []ServerID{"A", "B", "C"}

	newConf := func(id ServerID, restoreCommitted bool, maxAppend int) *Config {
		c := DefaultConfig()
		c.LocalID = id
		c.HeartbeatTimeout = 50 * time.Millisecond
		c.ElectionTimeout = 50 * time.Millisecond
		c.LeaderLeaseTimeout = 50 * time.Millisecond
		c.CommitTimeout = 5 * time.Millisecond
		c.SnapshotInterval = 10 * time.Minute
		c.MaxAppendEntries = maxAppend
		c.Logger = hclog.NewNullLogger()
		c.RestoreCommittedLogs = restoreCommitted
		return c
	}

	trans := map[ServerID]*InmemTransport{}
	logs := map[ServerID]*InmemCommitTrackingStore{}
	stable := map[ServerID]*InmemStore{}
	snaps := map[ServerID]*InmemSnapshotStore{}
	rafts := map[ServerID]*Raft{}
	for _, id := range ids {
		_, tr := NewInmemTransport(ServerAddress(id))
		trans[id] = tr
		logs[id] = NewInmemCommitTrackingStore()
		stable[id] = NewInmemStore()
		snaps[id] = NewInmemSnapshotStore()
	}
	connect := func(a, b ServerID) {
		trans[a].Connect(ServerAddress(b), trans[b])
		trans[b].Connect(ServerAddress(a), trans[a])
	}
	for i := range ids {
		for j := range ids {
			if i != j {
				connect(ids[i], ids[j])
			}
		}
	}
	start := func(id ServerID, restoreCommitted bool, maxAppend int) *Raft {
		r, err := NewRaft(newConf(id, restoreCommitted, maxAppend), new(MockFSM), logs[id], stable[id], snaps[id], trans[id])
		if err != nil {
			t.Fatalf("%s: NewRaft: %v", id, err)
		}
		rafts[id] = r
		return r
	}

	cfg := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "A", Address: "A"},
		{Suffrage: Voter, ID: "B", Address: "B"},
		{Suffrage: Voter, ID: "C", Address: "C"},
	}}
	if err := BootstrapCluster(newConf("A", true, 64), logs["A"], stable["A"], snaps["A"], trans["A"], cfg); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	start("A", true, 64)
	start("B", true, 64)
	start("C", true, 64)

	waitLeader := func(candidates []ServerID, d time.Duration) ServerID {
		deadline := time.Now().Add(d)
		for time.Now().Before(deadline) {
			for _, id := range candidates {
				if r := rafts[id]; r != nil && r.State() == Leader {
					return id
				}
			}
			time.Sleep(10 * time.Millisecond)
		}
		return ""
	}
	if waitLeader([]ServerID{"A", "B", "C"}, 10*time.Second) == "" {
		t.Fatalf("no leader")
	}
	if rafts["B"].State() != Leader {
		leader := waitLeader([]ServerID{"A", "C"}, 10*time.Second)
		if leader != "" {
			_ = rafts[leader].LeadershipTransferToServer("B", "B").Error()
		}
		deadline := time.Now().Add(10 * time.Second)
		for time.Now().Before(deadline) && rafts["B"].State() != Leader {
			time.Sleep(10 * time.Millisecond)
		}
	}
	leader := rafts["B"]
	if leader.State() != Leader {
		t.Fatalf("B is not leader, state %v", leader.State())
	}

	// A few committed entries, then a user snapshot on A so its snapshot stays early.
	for i := 0; i < 5; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("early-%d", i)), 3*time.Second).Error(); err != nil {
			t.Fatalf("early apply: %v", err)
		}
	}
	// Let A apply the early entries before it snapshots (Barrier is leader-only).
	appliedDeadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(appliedDeadline) && rafts["A"].AppliedIndex() < 4 {
		time.Sleep(10 * time.Millisecond)
	}
	if rafts["A"].AppliedIndex() < 2 {
		t.Fatalf("A applied nothing before snapshot: %d", rafts["A"].AppliedIndex())
	}
	if err := rafts["A"].Snapshot().Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	snapList, _ := snaps["A"].List()
	if len(snapList) == 0 {
		t.Fatalf("no snapshot on A")
	}
	snapshotIndex := snapList[0].Index

	// Commit enough further entries that A's staged commit index is far above its
	// snapshot while its own snapshots stay where they are.
	const extra = 250
	for i := 0; i < extra; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("bulk-%d", i)), 5*time.Second).Error(); err != nil {
			t.Fatalf("bulk apply %d: %v", i, err)
		}
	}
	// Wait until A has staged a commit index far enough above its snapshot.
	deadline := time.Now().Add(15 * time.Second)
	stagedCommit, _ := logs["A"].GetCommitIndex()
	for time.Now().Before(deadline) && stagedCommit < snapshotIndex+150 {
		time.Sleep(20 * time.Millisecond)
		stagedCommit, _ = logs["A"].GetCommitIndex()
	}
	lastLog, _ := logs["A"].LastIndex()
	entriesToReplay := stagedCommit - snapshotIndex

	liveStallEmit(map[string]interface{}{
		"event":               "fixture",
		"mode":                mode,
		"local_id":            "A",
		"snapshot_index":      snapshotIndex,
		"staged_commit_index": stagedCommit,
		"log_last_index":      lastLog,
		"entries_to_replay":   entriesToReplay,
		"gap_over_channel":    entriesToReplay > 128,
		"cluster_ids":         "A,B,C",
		"leader":              "B",
	})

	// A goes down while the other two keep a quorum.
	if sf := rafts["A"].Shutdown(); sf != nil {
		_ = sf.Error()
	}
	deadline = time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) && leader.State() != Leader {
		time.Sleep(20 * time.Millisecond)
	}
	clusterAlive := leader.State() == Leader

	// Restart A on the same stores, once with the feature and a small batch size,
	// once without the feature, each in its own goroutine with a bounded window.
	attempt := func(name string, restoreCommitted bool, maxAppend int, window time.Duration) (bool, uint64) {
		_, newTrans := NewInmemTransport(ServerAddress("A"))
		trans["A"] = newTrans
		for _, id := range ids {
			if id != "A" {
				trans[id].Disconnect("A")
				connect("A", id)
			}
		}
		done := make(chan *Raft, 1)
		go func() {
			r, err := NewRaft(newConf("A", restoreCommitted, maxAppend), new(MockFSM), logs["A"], stable["A"], snaps["A"], newTrans)
			if err != nil {
				done <- nil
				return
			}
			done <- r
		}()
		select {
		case r := <-done:
			if r == nil {
				liveStallEmit(map[string]interface{}{"event": name, "mode": mode, "local_id": "A", "newraft_returned": true, "error": "NewRaft returned an error"})
				return true, 0
			}
			rafts["A"] = r
			liveStallEmit(map[string]interface{}{
				"event":                  name,
				"mode":                   mode,
				"local_id":               "A",
				"newraft_returned":       true,
				"state":                  r.State().String(),
				"last_applied":           r.getLastApplied(),
				"applied_at_snapshot":    r.getLastApplied() == snapshotIndex,
				"fsm_mutate_capacity":    cap(r.fsmMutateCh),
				"replay_exceeds_channel": entriesToReplay > uint64(cap(r.fsmMutateCh)),
			})
			return true, r.getLastApplied()
		case <-time.After(window):
			liveStallEmit(map[string]interface{}{
				"event":            name,
				"mode":             mode,
				"local_id":         "A",
				"newraft_returned": false,
				"window_ms":        window.Milliseconds(),
			})
			return false, 0
		}
	}

	returned, _ := attempt("stalled_restart", true, 1, 5*time.Second)
	liveStallEmit(map[string]interface{}{
		"event":                    "cluster_status",
		"mode":                     mode,
		"local_id":                 "A",
		"cluster_alive_without_a":  clusterAlive,
		"stalled_restart_returned": returned,
	})
	if !returned {
		controlReturned, controlApplied := attempt("control_restart", false, 1, 10*time.Second)
		liveStallEmit(map[string]interface{}{
			"event":                "control_restart_summary",
			"mode":                 mode,
			"local_id":             "A",
			"control_returned":     controlReturned,
			"control_last_applied": controlApplied,
			"snapshot_index":       snapshotIndex,
		})
	}

	for _, id := range ids {
		if r := rafts[id]; r != nil {
			if sf := r.Shutdown(); sf != nil {
				_ = sf.Error()
			}
		}
	}
}
