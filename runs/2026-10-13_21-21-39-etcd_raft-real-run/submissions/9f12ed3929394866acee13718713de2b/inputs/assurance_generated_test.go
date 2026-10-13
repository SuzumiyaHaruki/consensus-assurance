package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	pb "go.etcd.io/raft/v3/raftpb"
)

// caEvent emits a single machine-parsable event line.
func caEvent(t *testing.T, v map[string]any) {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceSnapshotRepair measures the two producers that can take a
// follower's Progress out of StateSnapshot: a peer MsgAppResp that reports the
// snapshot applied, and an application report delivered as MsgSnapStatus.
func TestAssuranceSnapshotRepair(t *testing.T) {
	ms := newTestMemoryStorage(withPeers(1, 2, 3))
	ms.Append([]*pb.Entry{
		{Term: new(uint64(1)), Index: new(uint64(1))},
		{Term: new(uint64(1)), Index: new(uint64(2)), Data: []byte("x")},
	})
	if _, err := ms.CreateSnapshot(2, nil, nil); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	if err := ms.Compact(2); err != nil {
		t.Fatalf("compact: %v", err)
	}
	r := newTestRaft(1, 3, 1, ms)
	r.becomeCandidate()
	r.becomeLeader()
	pr := r.trk.Progress[2]
	pr.Match, pr.Next, pr.RecentActive = 1, 2, true
	sent := r.maybeSendAppend(2, false)
	caEvent(t, map[string]any{
		"event":        "snap_setup",
		"alias":        "snapshot_progress",
		"first_index":  r.raftLog.firstIndex(),
		"sent":         sent,
		"state":        pr.State.String(),
		"match":        pr.Match,
		"pending_snap": pr.PendingSnapshot,
		"paused":       pr.IsPaused(),
	})

	// Repair A: the follower reports that it applied the snapshot.
	_ = r.Step(&pb.Message{From: new(uint64(2)), Type: pb.MsgAppResp.Enum(), Index: new(uint64(2))})
	caEvent(t, map[string]any{
		"event":       "snap_repair_a",
		"alias":       "snapshot_progress",
		"state_after": pr.State.String(),
		"match":       pr.Match,
		"paused":      pr.IsPaused(),
	})

	// Repair B: a fresh follower whose application reports the snapshot failed.
	r2 := newTestRaft(1, 3, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r2.becomeCandidate()
	r2.becomeLeader()
	prB := r2.trk.Progress[3]
	prB.BecomeSnapshot(1)
	caEvent(t, map[string]any{
		"event":        "snap_before_b",
		"alias":        "snapshot_report",
		"state":        prB.State.String(),
		"pending_snap": prB.PendingSnapshot,
	})
	_ = r2.Step(&pb.Message{From: new(uint64(3)), Type: pb.MsgSnapStatus.Enum(), Reject: new(true)})
	caEvent(t, map[string]any{
		"event":        "snap_repair_b",
		"alias":        "snapshot_report",
		"state_after":  prB.State.String(),
		"pending_snap": prB.PendingSnapshot,
		"paused":       prB.MsgAppFlowPaused,
	})
}
