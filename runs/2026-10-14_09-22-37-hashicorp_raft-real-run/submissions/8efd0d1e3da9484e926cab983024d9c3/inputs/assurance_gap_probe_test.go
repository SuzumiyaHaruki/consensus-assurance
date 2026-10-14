package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func gapEvent(t *testing.T, kind string, fields map[string]interface{}) {
	fields["event"] = kind
	b, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func serversOf(r *Raft) map[string]bool {
	out := map[string]bool{}
	f := r.GetConfiguration()
	if err := f.Error(); err != nil {
		return out
	}
	for _, s := range f.Configuration().Servers {
		out[string(s.ID)] = true
	}
	return out
}

func newestConfigEntryIdx(logs LogStore) uint64 {
	first, err := logs.FirstIndex()
	if err != nil {
		return 0
	}
	last, err := logs.LastIndex()
	if err != nil {
		return 0
	}
	for i := last; i >= first && i > 0; i-- {
		var l Log
		if logs.GetLog(i, &l) == nil && l.Type == LogConfiguration {
			return i
		}
	}
	return 0
}

func waitAnyLeader(rs []*Raft, d time.Duration) *Raft {
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		for _, r := range rs {
			if r.State() == Leader {
				return r
			}
		}
		time.Sleep(5 * time.Millisecond)
	}
	return nil
}

// TestAssurance_StaleConfigurationAfterRestart creates a two-voter cluster,
// snapshots it, then commits a configuration change that adds a third voter
// (which never runs, since two acks are a quorum of three). It then restarts the
// leader and observes whether the restarted node still knows the newest
// committed configuration, and what configuration it bases a later change on.
func TestAssurance_StaleConfigurationAfterRestart(t *testing.T) {
	for _, mode := range []string{"restore_on", "restore_off"} {
		runStaleConfigCase(t, mode, mode == "restore_on")
	}
}

func runStaleConfigCase(t *testing.T, mode string, restore bool) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = restore
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 10

	addrA, transA := NewInmemTransport(ServerAddress("A"))
	confA := *conf
	confA.LocalID = ServerID(addrA)
	logsA := NewInmemCommitTrackingStore()
	stableA := NewInmemStore()
	snapsA := NewInmemSnapshotStore()

	if err := BootstrapCluster(&confA, logsA, stableA, snapsA, transA, Configuration{Servers: []Server{
		{Suffrage: Voter, ID: ServerID(addrA), Address: addrA},
		{Suffrage: Voter, ID: ServerID("B"), Address: ServerAddress("B")},
	}}); err != nil {
		t.Fatalf("[%s] bootstrap: %v", mode, err)
	}

	rA, err := NewRaft(&confA, new(MockFSM), logsA, stableA, snapsA, transA)
	if err != nil {
		t.Fatalf("[%s] NewRaft A: %v", mode, err)
	}

	addrB, transB := NewInmemTransport(ServerAddress("B"))
	transA.Connect(ServerAddress("B"), transB)
	transB.Connect(ServerAddress("A"), transA)
	confB := *conf
	confB.LocalID = ServerID(addrB)
	logsB := NewInmemCommitTrackingStore()
	stableB := NewInmemStore()
	snapsB := NewInmemSnapshotStore()
	rB, err := NewRaft(&confB, new(MockFSM), logsB, stableB, snapsB, transB)
	if err != nil {
		t.Fatalf("[%s] NewRaft B: %v", mode, err)
	}

	leader := waitAnyLeader([]*Raft{rA, rB}, 8*time.Second)
	if leader == nil {
		t.Fatalf("[%s] no leader elected", mode)
	}
	leaderIsA := leader == rA

	for i := 0; i < 5; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("cmd%d", i)), 2*time.Second).Error(); err != nil {
			t.Fatalf("[%s] apply %d: %v", mode, i, err)
		}
	}
	if err := leader.Snapshot().Error(); err != nil {
		t.Fatalf("[%s] snapshot: %v", mode, err)
	}
	snapListA, err := snapsA.List()
	if err != nil {
		t.Fatalf("[%s] list snapshots A: %v", mode, err)
	}

	// Add a third voter that never runs; two acks (A and B) are a quorum of three.
	if err := rA.AddVoter(ServerID("C"), ServerAddress("C"), 0, 5*time.Second).Error(); err != nil {
		t.Fatalf("[%s] AddVoter C: %v", mode, err)
	}
	// Commit further entries so the configuration change is no longer the
	// newest log entry: this is what puts it inside the persisted commit index.
	for i := 0; i < 4; i++ {
		if err := rA.Apply([]byte(fmt.Sprintf("after%d", i)), 2*time.Second).Error(); err != nil {
			t.Fatalf("[%s] apply after %d: %v", mode, i, err)
		}
	}

	before := serversOf(rA)
	staged, err := logsA.GetCommitIndex()
	if err != nil {
		t.Fatalf("[%s] GetCommitIndex A: %v", mode, err)
	}
	lastIdx, _ := logsA.LastIndex()

	gapEvent(t, "pre_restart", map[string]interface{}{
		"mode":              mode,
		"leader_is_A":       leaderIsA,
		"servers_before":    len(before),
		"contains_c_before": before["C"],
		"snapshot_count_A":  len(snapListA),
		"log_last_index":    lastIdx,
		"staged_commit_idx": staged,
		"newest_config_idx": newestConfigEntryIdx(logsA),
	})

	if err := rA.Shutdown().Error(); err != nil {
		t.Fatalf("[%s] shutdown A: %v", mode, err)
	}

	// Restart A on the same durable stores with a fresh transport.
	_, transA2 := NewInmemTransport(addrA)
	transA2.Connect(ServerAddress("B"), transB)
	rA2, err := NewRaft(&confA, new(MockFSM), logsA, stableA, snapsA, transA2)
	if err != nil {
		t.Fatalf("[%s] second NewRaft A: %v", mode, err)
	}
	after := serversOf(rA2)
	viewB := serversOf(rB)

	gapEvent(t, "post_restart", map[string]interface{}{
		"mode":              mode,
		"servers_after":     len(after),
		"contains_c_after":  after["C"],
		"servers_view_B":    len(viewB),
		"last_applied_A":    rA2.AppliedIndex(),
		"commit_index_A":    rA2.CommitIndex(),
		"log_last_index":    lastIdx,
		"staged_commit":     staged,
		"snapshot_count_A":  len(snapListA),
		"newest_config_idx": newestConfigEntryIdx(logsA),
	})

	// Optional continuation: if the restarted node can lead again, base a
	// configuration change on whatever configuration it believes it has.
	leader2 := waitAnyLeader([]*Raft{rA2, rB}, 8*time.Second)
	stableLeader := false
	deadline := time.Now().Add(8 * time.Second)
	for time.Now().Before(deadline) && leader2 == rA2 {
		if rA2.State() == Leader {
			time.Sleep(300 * time.Millisecond)
			if rA2.State() == Leader {
				stableLeader = true
				break
			}
		}
		time.Sleep(20 * time.Millisecond)
	}
	gapEvent(t, "post_restart_leader", map[string]interface{}{
		"mode":            mode,
		"leader_is_A":     leader2 == rA2,
		"stable_A_leader": stableLeader,
	})
	if stableLeader {
		err := rA2.AddVoter(ServerID("E"), ServerAddress("E"), 0, 5*time.Second).Error()
		afterChange := serversOf(rA2)
		if err == nil {
			// Give B a moment to observe the entry as well.
			deadline := time.Now().Add(2 * time.Second)
			for time.Now().Before(deadline) {
				if serversOf(rB)["E"] {
					break
				}
				time.Sleep(10 * time.Millisecond)
			}
		}
		gapEvent(t, "after_config_change", map[string]interface{}{
			"mode":                 mode,
			"change_err":           fmt.Sprintf("%v", err),
			"servers_after_change": len(afterChange),
			"contains_c_final":     afterChange["C"],
			"contains_e_final":     afterChange["E"],
			"view_B_contains_c":    serversOf(rB)["C"],
			"view_B_contains_e":    serversOf(rB)["E"],
		})
	} else {
		gapEvent(t, "after_config_change", map[string]interface{}{
			"mode":       mode,
			"skipped":    true,
			"leader_is_A": leader2 == rA2,
		})
	}

	_ = rA2.Shutdown().Error()
	_ = rB.Shutdown().Error()
}
