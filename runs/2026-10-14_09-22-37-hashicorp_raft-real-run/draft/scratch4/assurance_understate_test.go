package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

// Self-contained harness: only this file is copied into the captured package.

func underEvent(t *testing.T, kind string, fields map[string]interface{}) {
	fields["event"] = kind
	b, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func underServers(r *Raft) int {
	f := r.GetConfiguration()
	if err := f.Error(); err != nil {
		return -1
	}
	return len(f.Configuration().Servers)
}

func underHasServer(r *Raft, id ServerID) bool {
	f := r.GetConfiguration()
	if err := f.Error(); err != nil {
		return false
	}
	for _, s := range f.Configuration().Servers {
		if s.ID == id {
			return true
		}
	}
	return false
}

func underLeaderAmong(rs []*Raft, d time.Duration) *Raft {
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

// TestAssurance_ForgottenAddedVoterUnderstatesQuorum adds a fourth voter, then
// restarts the leader with RestoreCommittedLogs (and without it as a control) so
// the restarted node may forget the added voter, and observes whether it then
// accepts a write that only two of the four committed voters have received.
func TestAssurance_ForgottenAddedVoterUnderstatesQuorum(t *testing.T) {
	for _, mode := range []string{"restore_on", "restore_off"} {
		runUnderstateCase(t, mode, mode == "restore_on")
	}
}

func runUnderstateCase(t *testing.T, mode string, restore bool) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = restore
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 10

	addrs := []ServerAddress{"A", "B", "C", "D"}
	trans := make([]*InmemTransport, len(addrs))
	confs := make([]*Config, len(addrs))
	logs := make([]*InmemCommitTrackingStore, len(addrs))
	stables := make([]*InmemStore, len(addrs))
	snaps := make([]*InmemSnapshotStore, len(addrs))
	for i, a := range addrs {
		_, trans[i] = NewInmemTransport(a)
		c := *conf
		c.LocalID = ServerID(a)
		if a == "D" {
			// D is not the subject of this probe: keep its own restart path normal.
			c.RestoreCommittedLogs = false
		}
		confs[i] = &c
		logs[i] = NewInmemCommitTrackingStore()
		stables[i] = NewInmemStore()
		snaps[i] = NewInmemSnapshotStore()
	}
	for i := range addrs {
		for j := range addrs {
			if i != j {
				trans[i].Connect(addrs[j], trans[j])
			}
		}
	}

	cfg := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "A", Address: "A"},
		{Suffrage: Voter, ID: "B", Address: "B"},
		{Suffrage: Voter, ID: "C", Address: "C"},
	}}
	if err := BootstrapCluster(confs[0], logs[0], stables[0], snaps[0], trans[0], cfg); err != nil {
		t.Fatalf("[%s] bootstrap: %v", mode, err)
	}
	rafts := make([]*Raft, len(addrs))
	for i := range addrs {
		r, err := NewRaft(confs[i], new(MockFSM), logs[i], stables[i], snaps[i], trans[i])
		if err != nil {
			t.Fatalf("[%s] NewRaft %d: %v", mode, i, err)
		}
		rafts[i] = r
	}
	raftA, raftB, raftC, raftD := rafts[0], rafts[1], rafts[2], rafts[3]
	if underLeaderAmong(rafts, 10*time.Second) != raftA {
		t.Fatalf("[%s] A did not become leader", mode)
	}
	if err := raftA.Apply([]byte("pre0"), 2*time.Second).Error(); err != nil {
		t.Fatalf("[%s] pre-apply: %v", mode, err)
	}
	if err := raftA.Snapshot().Error(); err != nil {
		t.Fatalf("[%s] snapshot: %v", mode, err)
	}
	// Add the fourth voter and let it catch up; the committed configuration is
	// then {A,B,C,D} with a quorum of three.
	if err := raftA.AddVoter("D", "D", 0, 5*time.Second).Error(); err != nil {
		t.Fatalf("[%s] AddVoter D: %v", mode, err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) && raftD.LastIndex() < raftA.LastIndex() {
		time.Sleep(10 * time.Millisecond)
	}
	for i := 0; i < 2; i++ {
		if err := raftA.Apply([]byte(fmt.Sprintf("after%d", i)), 2*time.Second).Error(); err != nil {
			t.Fatalf("[%s] apply after %d: %v", mode, i, err)
		}
	}
	staged, err := logs[0].GetCommitIndex()
	if err != nil {
		t.Fatalf("[%s] GetCommitIndex: %v", mode, err)
	}
	underEvent(t, "before_restart_"+mode, map[string]interface{}{
		"mode":              mode,
		"a_servers":         underServers(raftA),
		"a_has_d":           underHasServer(raftA, "D"),
		"d_servers":         underServers(raftD),
		"staged_commit_idx": staged,
		"a_log_last":        raftA.LastIndex(),
		"snapshots":         func() int { l, _ := snaps[0].List(); return len(l) }(),
	})

	// Keep the other voters from stealing the post-restart election.
	for _, r := range []*Raft{raftB, raftC, raftD} {
		rc := r.ReloadableConfig()
		rc.HeartbeatTimeout = 3 * time.Second
		rc.ElectionTimeout = 3 * time.Second
		if err := r.ReloadConfig(rc); err != nil {
			t.Fatalf("[%s] reload: %v", mode, err)
		}
	}

	if err := raftA.Shutdown().Error(); err != nil {
		t.Fatalf("[%s] shutdown A: %v", mode, err)
	}
	_, transA2 := NewInmemTransport("A")
	for i := 1; i < len(addrs); i++ {
		transA2.Connect(addrs[i], trans[i])
		trans[i].Connect("A", transA2)
	}
	raftA, err = NewRaft(confs[0], new(MockFSM), logs[0], stables[0], snaps[0], transA2)
	if err != nil {
		t.Fatalf("[%s] restart A: %v", mode, err)
	}
	underEvent(t, "after_restart_"+mode, map[string]interface{}{
		"mode":      mode,
		"a_servers": underServers(raftA),
		"a_has_d":   underHasServer(raftA, "D"),
		"d_servers": underServers(raftD),
		"b_servers": underServers(raftB),
	})

	aIsLeader := underLeaderAmong([]*Raft{raftA}, 4*time.Second) == raftA
	underEvent(t, "split_setup_"+mode, map[string]interface{}{
		"mode":        mode,
		"a_is_leader": aIsLeader,
		"a_servers":   underServers(raftA),
		"a_log_last":  raftA.LastIndex(),
	})
	// Only A and B stay connected: two of the four committed voters.
	for _, i := range []int{2, 3} {
		transA2.Disconnect(addrs[i])
		trans[i].Disconnect("A")
	}
	fut := raftA.Apply([]byte("two-of-four-write"), 2*time.Second)
	writeErr := fut.Error()
	fields := map[string]interface{}{
		"mode":          mode,
		"write_applied": writeErr == nil,
		"write_err":     fmt.Sprintf("%v", writeErr),
		"a_state":       raftA.State().String(),
		"a_commit":      raftA.CommitIndex(),
		"a_applied":     raftA.AppliedIndex(),
		"b_log_last":    raftB.LastIndex(),
		"c_log_last":    raftC.LastIndex(),
		"d_log_last":    raftD.LastIndex(),
		"a_servers":     underServers(raftA),
	}
	if writeErr == nil {
		idx := fut.Index()
		holds := 0
		for _, r := range []*Raft{raftA, raftB, raftC, raftD} {
			if r.LastIndex() >= idx {
				holds++
			}
		}
		fields["entry_index"] = idx
		fields["voters_holding_entry"] = holds
		// The committed configuration has four voters, so three must hold it.
		fields["entry_on_committed_quorum"] = holds >= 3
	}
	underEvent(t, "split_write_"+mode, fields)

	// Repair phase (failing mode only): take the stale leader away, let the
	// correctly configured members lead, and see whether a later configuration
	// entry restores the forgotten voter on the restarted node.
	if restore {
		if err := raftA.Shutdown().Error(); err != nil {
			t.Fatalf("[%s] shutdown stale A: %v", mode, err)
		}
		for _, r := range []*Raft{raftB, raftC, raftD} {
			rc := r.ReloadableConfig()
			rc.HeartbeatTimeout = 50 * time.Millisecond
			rc.ElectionTimeout = 50 * time.Millisecond
			if err := r.ReloadConfig(rc); err != nil {
				t.Fatalf("[%s] reload for repair: %v", mode, err)
			}
		}
		// Reconnect C and D to the rest of the cluster for the election.
		for _, i := range []int{2, 3} {
			for j := range addrs {
				if j == 0 {
					continue // A is down and will be restarted separately
				}
				if i != j {
					trans[i].Connect(addrs[j], trans[j])
					trans[j].Connect(addrs[i], trans[i])
				}
			}
		}
		repairLeader := underLeaderAmong([]*Raft{raftB, raftC, raftD}, 10*time.Second)
		underEvent(t, "repair_setup_"+mode, map[string]interface{}{
			"mode":          mode,
			"repair_leader": func() string { if repairLeader == nil { return "" }; return string(repairLeader.localID) }(),
			"b_servers":     underServers(raftB),
			"d_servers":     underServers(raftD),
		})
		if repairLeader != nil {
			addErr := repairLeader.AddVoter("E", "E", 0, 5*time.Second).Error()
			// Restart A (its configuration again comes from the snapshot) and let
			// the leader replicate the new configuration entry to it.
			_, transA3 := NewInmemTransport("A")
			transA3.Connect("B", trans[1])
			transA3.Connect("C", trans[2])
			transA3.Connect("D", trans[3])
			trans[1].Connect("A", transA3)
			trans[2].Connect("A", transA3)
			trans[3].Connect("A", transA3)
			raftA, err = NewRaft(confs[0], new(MockFSM), logs[0], stables[0], snaps[0], transA3)
			if err != nil {
				t.Fatalf("[%s] restart A for repair: %v", mode, err)
			}
			deadline := time.Now().Add(6 * time.Second)
			for time.Now().Before(deadline) && underServers(raftA) < 5 {
				time.Sleep(20 * time.Millisecond)
			}
			underEvent(t, "repair_"+mode, map[string]interface{}{
				"mode":            mode,
				"e_added_ok":      addErr == nil,
				"a_servers_after": underServers(raftA),
				"a_has_d":         underHasServer(raftA, "D"),
				"a_has_e":         underHasServer(raftA, "E"),
				"a_log_last":      raftA.LastIndex(),
			})
		}
	}

	for _, r := range []*Raft{raftA, raftB, raftC, raftD} {
		_ = r.Shutdown()
	}
}
