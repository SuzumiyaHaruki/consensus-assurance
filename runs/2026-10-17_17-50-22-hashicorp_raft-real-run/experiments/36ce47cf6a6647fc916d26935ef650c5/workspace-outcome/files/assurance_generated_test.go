package raft

// Construction notes:
//   * Five real nodes over in-memory transports: voters A, B, C and non-voters
//     D, E, all bootstrapped with the same configuration and a recording FSM.
//   * The leader writes "v1" and every node applies it. The leader is then
//     partitioned from the two other voters and keeps only the non-voters
//     reachable, so the committed voter quorum cannot answer it.
//   * Immediately after the partition the old leader is asked to verify itself,
//     which is the check a caller performs before serving a read. The trigger
//     keeps the non-voters reachable; the control also cuts them, leaving the old
//     leader with no possible supporter.
//   * The two remaining voters then elect a new leader and commit "v2". Once that
//     has happened the old leader is asked to verify itself again and its state
//     machine is read.
//   * The decisive observation is whether verification can still succeed after
//     the majority has moved on, which is what a stale verified read needs.

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"testing"
	"time"
)

func srEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

type srFSM struct {
	mu   sync.Mutex
	vals []string
}

func (f *srFSM) Apply(l *Log) interface{} {
	f.mu.Lock()
	f.vals = append(f.vals, string(l.Data))
	f.mu.Unlock()
	return nil
}

func (f *srFSM) last() string {
	f.mu.Lock()
	defer f.mu.Unlock()
	if len(f.vals) == 0 {
		return ""
	}
	return f.vals[len(f.vals)-1]
}

func (f *srFSM) Snapshot() (FSMSnapshot, error) { return &srSnap{}, nil }
func (f *srFSM) Restore(io.ReadCloser) error    { return nil }

type srSnap struct{}

func (s *srSnap) Persist(SnapshotSink) error { return nil }
func (s *srSnap) Release()                   {}

func srWaitLeader(t *testing.T, nodes []*Raft, want *Raft, timeout time.Duration) *Raft {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		for _, r := range nodes {
			if r == want {
				continue
			}
			if st := r.State(); st == Leader {
				return r
			}
		}
		time.Sleep(20 * time.Millisecond)
	}
	return nil
}

func srVerify(r *Raft, timeout time.Duration) (bool, string, bool) {
	done := make(chan error, 1)
	go func() { done <- r.VerifyLeader().Error() }()
	select {
	case err := <-done:
		if err != nil {
			return false, err.Error(), true
		}
		return true, "", true
	case <-time.After(timeout):
		return false, "no completion", false
	}
}

func srRun(t *testing.T, caseName string, cutNonvoters bool) {
	base := inmemConfig(t)
	// The lease may not exceed the heartbeat timeout. All members share a
	// one-second heartbeat and lease; the voters' election timeouts are staggered
	// so that, whichever member leads, the two remaining voters do not campaign in
	// lockstep and split the vote after the partition.
	base.HeartbeatTimeout = time.Second
	base.LeaderLeaseTimeout = time.Second
	electionTimeouts := map[string]time.Duration{
		"A": 1100 * time.Millisecond,
		"B": 2 * time.Second,
		"C": 3 * time.Second,
		"D": 3 * time.Second,
		"E": 3 * time.Second,
	}

	ids := []string{"A", "B", "C", "D", "E"}
	addrs := make(map[string]ServerAddress, len(ids))
	trans := make(map[string]*InmemTransport, len(ids))
	for _, id := range ids {
		a, tr := NewInmemTransport(ServerAddress(id))
		addrs[id] = a
		trans[id] = tr
	}
	for _, i := range ids {
		for _, j := range ids {
			if i != j {
				trans[i].Connect(addrs[j], trans[j])
			}
		}
	}

	servers := []Server{
		{Suffrage: Voter, ID: "A", Address: addrs["A"]},
		{Suffrage: Voter, ID: "B", Address: addrs["B"]},
		{Suffrage: Voter, ID: "C", Address: addrs["C"]},
		{Suffrage: Nonvoter, ID: "D", Address: addrs["D"]},
		{Suffrage: Nonvoter, ID: "E", Address: addrs["E"]},
	}
	cfg := Configuration{Servers: servers}

	nodes := make(map[string]*Raft, len(ids))
	fsms := make(map[string]*srFSM, len(ids))
	stores := make(map[string]*InmemStore, len(ids))
	snaps := make(map[string]*InmemSnapshotStore, len(ids))
	for _, id := range ids {
		conf := *base
		conf.LocalID = ServerID(id)
		conf.ElectionTimeout = electionTimeouts[id]
		store := NewInmemStore()
		snap := NewInmemSnapshotStore()
		if err := BootstrapCluster(&conf, store, store, snap, trans[id], cfg); err != nil {
			t.Fatalf("bootstrap %s: %v", id, err)
		}
		fsm := &srFSM{}
		r, err := NewRaft(&conf, fsm, store, store, snap, trans[id])
		if err != nil {
			t.Fatalf("raft %s: %v", id, err)
		}
		defer func(r *Raft) { _ = r.Shutdown().Error() }(r)
		nodes[id] = r
		fsms[id] = fsm
		stores[id] = store
		snaps[id] = snap
	}

	all := []*Raft{nodes["A"], nodes["B"], nodes["C"], nodes["D"], nodes["E"]}
	leader := srWaitLeader(t, all, nil, 10*time.Second)
	if leader == nil {
		t.Fatalf("no leader formed")
	}
	leaderID := string(leader.localID)

	if err := leader.Apply([]byte("v1"), 3*time.Second).Error(); err != nil {
		t.Fatalf("initial apply: %v", err)
	}
	time.Sleep(300 * time.Millisecond)

	// Partition the leader from the other two voters, and optionally from the
	// non-voters as well.
	leaderTrans := trans[leaderID]
	for _, id := range ids {
		if id == leaderID {
			continue
		}
		isVoter := id == "A" || id == "B" || id == "C"
		// Always cut the other voters; in the control, cut the non-voters too.
		if isVoter || cutNonvoters {
			leaderTrans.Disconnect(addrs[id])
			trans[id].Disconnect(addrs[leaderID])
		}
	}

	srEmit(t, map[string]interface{}{
		"event":               "sr_case_" + caseName,
		"case":                caseName,
		"members":             5,
		"voters":              3,
		"nonvoters":           2,
		"leader":              leaderID,
		"voters_reachable":    1,
		"nonvoters_reachable": map[bool]int{true: 0, false: 2}[cutNonvoters],
		"initial_value":       "v1",
		"leader_value":        fsms[leaderID].last(),
	})

	// While the old leader still believes it leads: verify, then write.
	cutAt := time.Now()
	verifyOK, verifyErr, verifyCompleted := srVerify(leader, 2*time.Second)
	msToVerify := int(time.Since(cutAt) / time.Millisecond)

	// The majority side elects a new leader and commits a different value.
	newLeader := srWaitLeader(t, all, leader, 12*time.Second)
	newLeaderID := ""
	newApplyOK := false
	newValue := ""
	if newLeader != nil {
		newLeaderID = string(newLeader.localID)
		newApplyOK = newLeader.Apply([]byte("v2"), 3*time.Second).Error() == nil
		time.Sleep(300 * time.Millisecond)
		newValue = fsms[newLeaderID].last()
	}
	msToNewLeader := -1
	if newLeaderID != "" {
		msToNewLeader = int(time.Since(cutAt) / time.Millisecond)
	}

	// Can the old leader still verify itself now that the majority has a leader?
	verifyAfterOK, verifyAfterErr, _ := srVerify(leader, 2*time.Second)
	oldValueBeforeHeal := fsms[leaderID].last()

	// Heal the partition and let the new leader's log reach the old one.
	for _, id := range ids {
		if id == leaderID {
			continue
		}
		leaderTrans.Connect(addrs[id], trans[id])
		trans[id].Connect(addrs[leaderID], leaderTrans)
	}
	time.Sleep(1500 * time.Millisecond)

	oldValue := fsms[leaderID].last()
	srEmit(t, map[string]interface{}{
		"event":             "sr_result_" + caseName,
		"case":              caseName,
		"old_leader":        leaderID,
		"old_leader_state":  leader.State().String(),
		"verify_completed":  verifyCompleted,
		"verify_after_partition_ok": verifyOK,
		"verify_error":      verifyErr,
		"ms_to_verify":      msToVerify,
		"new_leader":        newLeaderID,
		"new_apply_ok":      newApplyOK,
		"ms_to_new_leader":  msToNewLeader,
		"new_leader_value":  newValue,
		"verify_after_failover_ok": verifyAfterOK,
		"verify_after_failover_error": verifyAfterErr,
		"old_value_before_heal": oldValueBeforeHeal,
		"old_leader_value":  oldValue,
		"stale_verified_read": verifyAfterOK && newValue != "" && oldValueBeforeHeal != newValue,
	})
	t.Logf("case=%v old=%v verifyBefore=%v ms=%d newLeader=%v msNew=%d verifyAfter=%v errAfter=%q oldBeforeHeal=%q newValue=%q",
		caseName, leaderID, verifyOK, msToVerify, newLeaderID, msToNewLeader, verifyAfterOK, verifyAfterErr, oldValueBeforeHeal, newValue)
}

func TestAssuranceVerifyStaleRead(t *testing.T) {
	t.Run("trigger_nonvoters_connected", func(t *testing.T) {
		srRun(t, "trigger_nonvoters_connected", false)
	})
	t.Run("control_all_cut", func(t *testing.T) {
		srRun(t, "control_all_cut", true)
	})
}
