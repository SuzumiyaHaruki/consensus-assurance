package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

// Self-contained harness: only this file is copied into the captured package.

func dualEvent(t *testing.T, kind string, fields map[string]interface{}) {
	fields["event"] = kind
	b, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func dualNewestConfigIdx(logs LogStore) uint64 {
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

func dualEntry(logs LogStore, idx uint64) (string, uint64) {
	var l Log
	if idx == 0 || logs.GetLog(idx, &l) != nil {
		return "missing", 0
	}
	return l.Type.String(), l.Term
}

func dualLeaderAmong(rs []*Raft, d time.Duration) *Raft {
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

func dualServers(r *Raft) int {
	f := r.GetConfiguration()
	if err := f.Error(); err != nil {
		return -1
	}
	return len(f.Configuration().Servers)
}

func dualWaitCatchUp(a *Raft, other *Raft, d time.Duration) bool {
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		if other.LastIndex() >= a.LastIndex() {
			return true
		}
		time.Sleep(10 * time.Millisecond)
	}
	return other.LastIndex() >= a.LastIndex()
}

// TestAssurance_DualMajoritiesAfterSilentChange builds a three-voter cluster,
// snapshots it, adds a caught-up nonvoter, then restarts the leader with
// RestoreCommittedLogs so its in-memory configuration is the older {A,B}. That
// stale base turns the next AddVoter into a two-server change ({A,B,C} ->
// {A,B,E}). With the old voter B partitioned, the change commits on A plus the
// promoted nonvoter E. The probe then observes whether the old majority {B,C}
// can elect a leader that truncates A's committed entry once the partition is
// healed.
func TestAssurance_DualMajoritiesAfterSilentChange(t *testing.T) {
	conf := inmemConfig(t)
	conf.HeartbeatTimeout = 300 * time.Millisecond
	conf.ElectionTimeout = 300 * time.Millisecond
	conf.LeaderLeaseTimeout = 300 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 10

	ids := []ServerID{"A", "B", "C", "E"}
	trans := make([]*InmemTransport, len(ids))
	confs := make([]*Config, len(ids))
	logs := make([]*InmemCommitTrackingStore, len(ids))
	stables := make([]*InmemStore, len(ids))
	snaps := make([]*InmemSnapshotStore, len(ids))
	for i, id := range ids {
		_, trans[i] = NewInmemTransport(ServerAddress(id))
		c := *conf
		c.LocalID = id
		// Only the leader that is restarted replays committed logs.
		c.RestoreCommittedLogs = id == "A"
		confs[i] = &c
		logs[i] = NewInmemCommitTrackingStore()
		stables[i] = NewInmemStore()
		snaps[i] = NewInmemSnapshotStore()
	}
	connect := func(ts []*InmemTransport) {
		for i := range ts {
			for j := range ts {
				if i != j {
					ts[i].Connect(ts[j].LocalAddr(), ts[j])
				}
			}
		}
	}
	connect(trans)

	if err := BootstrapCluster(confs[0], logs[0], stables[0], snaps[0], trans[0], Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "A", Address: "A"},
		{Suffrage: Voter, ID: "B", Address: "B"},
	}}); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}

	fsms := make([]*MockFSM, len(ids))
	for i := range ids {
		fsms[i] = new(MockFSM)
	}
	fsmA2 := new(MockFSM)
	rafts := make([]*Raft, len(ids))
	for i := range ids {
		r, err := NewRaft(confs[i], fsms[i], logs[i], stables[i], snaps[i], trans[i])
		if err != nil {
			t.Fatalf("NewRaft %s: %v", ids[i], err)
		}
		rafts[i] = r
	}
	raftA, raftB, raftC, raftE := rafts[0], rafts[1], rafts[2], rafts[3]

	if dualLeaderAmong([]*Raft{raftA, raftB}, 10*time.Second) != raftA {
		t.Fatalf("A did not become leader")
	}
	// The FSM needs something applied before it can snapshot.
	if err := raftA.Apply([]byte("pre0"), 2*time.Second).Error(); err != nil {
		t.Fatalf("pre-apply: %v", err)
	}
	if err := raftA.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	if err := raftA.AddNonvoter("E", "E", 0, 5*time.Second).Error(); err != nil {
		t.Fatalf("AddNonvoter E: %v", err)
	}
	if !dualWaitCatchUp(raftA, raftE, 5*time.Second) {
		t.Fatalf("E did not catch up: E=%d A=%d", raftE.LastIndex(), raftA.LastIndex())
	}
	if err := raftA.AddVoter("C", "C", 0, 5*time.Second).Error(); err != nil {
		t.Fatalf("AddVoter C: %v", err)
	}
	if !dualWaitCatchUp(raftA, raftC, 5*time.Second) {
		t.Fatalf("C did not catch up: C=%d A=%d", raftC.LastIndex(), raftA.LastIndex())
	}
	for i := 0; i < 4; i++ {
		if err := raftA.Apply([]byte(fmt.Sprintf("cmd%d", i)), 2*time.Second).Error(); err != nil {
			t.Fatalf("apply %d: %v", i, err)
		}
	}
	configBeforeRestart := dualNewestConfigIdx(logs[0])
	dualEvent(t, "setup", map[string]interface{}{
		"a_servers":           dualServers(raftA),
		"c_servers":           dualServers(raftC),
		"e_servers":           dualServers(raftE),
		"a_last":              raftA.LastIndex(),
		"a_commit":            raftA.CommitIndex(),
		"e_last":              raftE.LastIndex(),
		"c_last":              raftC.LastIndex(),
		"newest_config_index": configBeforeRestart,
	})

	// Keep the other voters from campaigning while the restarted leader wins again.
	for _, r := range []*Raft{raftB, raftC, raftE} {
		rc := r.ReloadableConfig()
		rc.HeartbeatTimeout = 3 * time.Second
		rc.ElectionTimeout = 3 * time.Second
		if err := r.ReloadConfig(rc); err != nil {
			t.Fatalf("reload: %v", err)
		}
	}

	// Restart A: its configuration now comes from the snapshot, not the log.
	if err := raftA.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown A: %v", err)
	}
	_, transA2 := NewInmemTransport("A")
	transA2.Connect("B", trans[1])
	transA2.Connect("C", trans[2])
	transA2.Connect("E", trans[3])
	trans[1].Connect("A", transA2)
	trans[2].Connect("A", transA2)
	trans[3].Connect("A", transA2)
	raftA, err := NewRaft(confs[0], fsmA2, logs[0], stables[0], snaps[0], transA2)
	if err != nil {
		t.Fatalf("restart A: %v", err)
	}
	if dualLeaderAmong([]*Raft{raftA}, 6*time.Second) != raftA {
		dualEvent(t, "not_reached", map[string]interface{}{
			"reason":       "restarted A did not become leader",
			"a_servers":    dualServers(raftA),
			"a_state":      raftA.State().String(),
		})
		for _, r := range []*Raft{raftA, raftB, raftC, raftE} {
			_ = r.Shutdown()
		}
		return
	}
	dualEvent(t, "stale_leader", map[string]interface{}{
		"a_servers":           dualServers(raftA),
		"a_last":              raftA.LastIndex(),
		"a_commit":            raftA.CommitIndex(),
		"newest_config_index": dualNewestConfigIdx(logs[0]),
	})

	// Partition B from A so the change cannot reach it; C was never A's peer
	// under the stale configuration.
	trans[0] = transA2
	transA2.Disconnect("B")
	trans[1].Disconnect("A")

	changeErr := raftA.AddVoter("E", "E", 0, 2*time.Second).Error()
	xIndex := dualNewestConfigIdx(logs[0])
	committed := xIndex > configBeforeRestart && raftA.CommitIndex() >= xIndex
	entryTypeAtX, entryTermAtX := dualEntry(logs[0], xIndex)
	eTypeAtX, _ := dualEntry(logs[3], xIndex)
	dualEvent(t, "silent_change", map[string]interface{}{
		"change_err":           fmt.Sprintf("%v", changeErr),
		"x_index":              xIndex,
		"committed":            committed,
		"a_commit":             raftA.CommitIndex(),
		"entry_type_at_x":      entryTypeAtX,
		"entry_term_at_x":      entryTermAtX,
		"e_entry_type_at_x":    eTypeAtX,
		"a_servers":            dualServers(raftA),
		"b_log_last":           raftB.LastIndex(),
		"b_servers":            dualServers(raftB),
		"c_servers":            dualServers(raftC),
	})

	// A client write on the {A,B,E} side: committed with A and E.
	writeErr := raftA.Apply([]byte("client-write"), 2*time.Second).Error()
	dualEvent(t, "client_write", map[string]interface{}{
		"x_index":        xIndex,
		"write_applied":  writeErr == nil,
		"write_err":      fmt.Sprintf("%v", writeErr),
		"fsm_a_logs":     len(fsmA2.Logs()),
		"fsm_e_logs":     len(fsms[3].Logs()),
		"applied_a":      raftA.AppliedIndex(),
		"a_commit":       raftA.CommitIndex(),
	})

	// The old majority {B,C} may now elect one of themselves.
	oldSide := dualLeaderAmong([]*Raft{raftB, raftC}, 12*time.Second)
	oldLeaderID := ""
	if oldSide != nil {
		oldLeaderID = string(oldSide.localID)
	}
	dualEvent(t, "old_side_elected", map[string]interface{}{
		"x_index":         xIndex,
		"old_leader":      oldLeaderID,
		"old_leader_term": func() uint64 { if oldSide == nil { return 0 }; return oldSide.CurrentTerm() }(),
		"b_log_last":      raftB.LastIndex(),
		"c_log_last":      raftC.LastIndex(),
		"a_still_leader":  raftA.State() == Leader,
		"a_servers":       dualServers(raftA),
	})

	// Heal the partition and let the higher-term side reach A.
	transA2.Connect("B", trans[1])
	trans[1].Connect("A", transA2)
	time.Sleep(2500 * time.Millisecond)

	afterType, afterTerm := dualEntry(logs[0], xIndex)
	dualEvent(t, "after_heal", map[string]interface{}{
		"x_index":                  xIndex,
		"entry_type_at_x":          afterType,
		"entry_term_at_x":          afterTerm,
		"committed_entry_truncated": afterType != entryTypeAtX,
		"a_last":                   raftA.LastIndex(),
		"a_servers":                dualServers(raftA),
		"a_state":                  raftA.State().String(),
		"fsm_a_logs":               len(fsmA2.Logs()),
		"fsm_b_logs":               len(fsms[1].Logs()),
		"fsm_logs_equal":           len(fsmA2.Logs()) == len(fsms[1].Logs()),
		"applied_a":                raftA.AppliedIndex(),
	})

	for _, r := range []*Raft{raftA, raftB, raftC, raftE} {
		_ = r.Shutdown()
	}
}
