package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func quorumEvent(t *testing.T, kind string, fields map[string]interface{}) {
	fields["event"] = kind
	b, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func waitLeaderAmong(rs []*Raft, d time.Duration) int {
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		for i, r := range rs {
			if r.State() == Leader {
				return i
			}
		}
		time.Sleep(5 * time.Millisecond)
	}
	return -1
}

func waitAllConfigured(rs []*Raft, want int, d time.Duration) bool {
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		ok := true
		for _, r := range rs {
			f := r.GetConfiguration()
			if err := f.Error(); err != nil || len(f.Configuration().Servers) != want {
				ok = false
				break
			}
		}
		if ok {
			return true
		}
		time.Sleep(10 * time.Millisecond)
	}
	return false
}

func fullConfigCount(rs []*Raft, want int) int {
	n := 0
	for _, r := range rs {
		f := r.GetConfiguration()
		if err := f.Error(); err == nil && len(f.Configuration().Servers) == want {
			n++
		}
	}
	return n
}

func configSizes(rs []*Raft) []int {
	out := make([]int, 0, len(rs))
	for _, r := range rs {
		f := r.GetConfiguration()
		if err := f.Error(); err != nil {
			out = append(out, -1)
			continue
		}
		out = append(out, len(f.Configuration().Servers))
	}
	return out
}

// TestAssurance_ClusterWideRestartWithoutSnapshot restarts every voter of a
// three-voter cluster at once from durable state that has never been
// snapshotted, with RestoreCommittedLogs enabled and (control) disabled, and
// observes whether the cluster can elect a leader and whether each node still
// knows the configuration.
func TestAssurance_ClusterWideRestartWithoutSnapshot(t *testing.T) {
	for _, mode := range []string{"restore_on", "restore_off"} {
		runClusterRestartCase(t, mode, mode == "restore_on")
	}
}

func runClusterRestartCase(t *testing.T, mode string, restore bool) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = restore
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 10

	addrs := []ServerAddress{"A", "B", "C"}
	trans := make([]*InmemTransport, 3)
	confs := make([]*Config, 3)
	logs := make([]*InmemCommitTrackingStore, 3)
	stables := make([]*InmemStore, 3)
	snaps := make([]*InmemSnapshotStore, 3)
	for i, a := range addrs {
		_, trans[i] = NewInmemTransport(a)
		c := *conf
		c.LocalID = ServerID(a)
		confs[i] = &c
		logs[i] = NewInmemCommitTrackingStore()
		stables[i] = NewInmemStore()
		snaps[i] = NewInmemSnapshotStore()
	}
	for i := 0; i < 3; i++ {
		for j := 0; j < 3; j++ {
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

	rafts := make([]*Raft, 3)
	for i := 0; i < 3; i++ {
		r, err := NewRaft(confs[i], new(MockFSM), logs[i], stables[i], snaps[i], trans[i])
		if err != nil {
			t.Fatalf("[%s] NewRaft %d: %v", mode, i, err)
		}
		rafts[i] = r
	}

	firstLeader := waitLeaderAmong(rafts, 10*time.Second)
	if firstLeader < 0 {
		t.Fatalf("[%s] no initial leader", mode)
	}
	if !waitAllConfigured(rafts, 3, 5*time.Second) {
		t.Fatalf("[%s] nodes did not converge on the configuration: %v", mode, configSizes(rafts))
	}
	for i := 0; i < 10; i++ {
		if err := rafts[firstLeader].Apply([]byte(fmt.Sprintf("cmd%d", i)), 2*time.Second).Error(); err != nil {
			t.Fatalf("[%s] apply %d: %v", mode, i, err)
		}
	}
	staged := make([]uint64, 3)
	for i := 0; i < 3; i++ {
		staged[i], _ = logs[i].GetCommitIndex()
	}
	quorumEvent(t, "pre_restart_"+mode, map[string]interface{}{
		"mode":              mode,
		"servers_before":    configSizes(rafts),
		"staged_commit_idx": fmt.Sprintf("%v", staged),
	})

	// Restart every voter at once, as in a rolling cold restart of the cluster.
	for i := 0; i < 3; i++ {
		if err := rafts[i].Shutdown().Error(); err != nil {
			t.Fatalf("[%s] shutdown %d: %v", mode, i, err)
		}
	}
	trans2 := make([]*InmemTransport, 3)
	for i, a := range addrs {
		_, trans2[i] = NewInmemTransport(a)
	}
	for i := 0; i < 3; i++ {
		for j := 0; j < 3; j++ {
			if i != j {
				trans2[i].Connect(addrs[j], trans2[j])
			}
		}
	}
	restarted := make([]*Raft, 3)
	for i := 0; i < 3; i++ {
		r, err := NewRaft(confs[i], new(MockFSM), logs[i], stables[i], snaps[i], trans2[i])
		if err != nil {
			t.Fatalf("[%s] restart %d: %v", mode, i, err)
		}
		restarted[i] = r
	}

	// Fair opportunity to campaign: many election timeouts (50ms configured).
	leaderAfter := waitLeaderAmong(restarted, 6*time.Second)
	quorumEvent(t, "post_restart_"+mode, map[string]interface{}{
		"mode":             mode,
		"servers_after":    configSizes(restarted),
		"any_leader":       leaderAfter >= 0,
		"leader_index":     leaderAfter,
		"nodes_with_full_config": fullConfigCount(restarted, 3),
	})

	// Third phase for the failing mode: the operator restarts the same three
	// nodes once more, this time with RestoreCommittedLogs disabled, using the
	// same durable stores and fresh transports.
	if restore {
		for i := 0; i < 3; i++ {
			if err := restarted[i].Shutdown().Error(); err != nil {
				t.Fatalf("[%s] shutdown for recovery %d: %v", mode, i, err)
			}
		}
		trans3 := make([]*InmemTransport, 3)
		for i, a := range addrs {
			_, trans3[i] = NewInmemTransport(a)
		}
		for i := 0; i < 3; i++ {
			for j := 0; j < 3; j++ {
				if i != j {
					trans3[i].Connect(addrs[j], trans3[j])
				}
			}
		}
		recovered := make([]*Raft, 3)
		for i := 0; i < 3; i++ {
			c := *confs[i]
			c.RestoreCommittedLogs = false
			r, err := NewRaft(&c, new(MockFSM), logs[i], stables[i], snaps[i], trans3[i])
			if err != nil {
				t.Fatalf("[%s] recovery restart %d: %v", mode, i, err)
			}
			recovered[i] = r
		}
		leaderAfterRecovery := waitLeaderAmong(recovered, 8*time.Second)
		quorumEvent(t, "operator_restart_"+mode, map[string]interface{}{
			"mode":                   mode,
			"servers_after":          configSizes(recovered),
			"nodes_with_full_config": fullConfigCount(recovered, 3),
			"any_leader":             leaderAfterRecovery >= 0,
			"leader_index":           leaderAfterRecovery,
		})
		for i := 0; i < 3; i++ {
			_ = recovered[i].Shutdown().Error()
		}
		return
	}

	for i := 0; i < 3; i++ {
		_ = restarted[i].Shutdown().Error()
	}
}
