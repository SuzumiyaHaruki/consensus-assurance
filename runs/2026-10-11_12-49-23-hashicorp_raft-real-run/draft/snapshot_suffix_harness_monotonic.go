package raft

// Assurance exploration harness against the captured hashicorp/raft snapshot.
// Not part of the target source; uses exported plus same-package test
// facilities. This variant adds a MonotonicLogStore scenario, where
// installSnapshot's removeOldLogs already deletes the above-snapshot bytes, to
// discriminate retained log bytes from the cached last-log state as the cause.

import (
	"fmt"
	"testing"
	"time"
)

func assuranceConfMono() *Config {
	conf := DefaultConfig()
	conf.HeartbeatTimeout = 300 * time.Millisecond
	conf.ElectionTimeout = 300 * time.Millisecond
	conf.LeaderLeaseTimeout = 300 * time.Millisecond
	conf.CommitTimeout = 10 * time.Millisecond
	// Delete all logs at or below a completed snapshot so the leader cannot
	// serve them from its log store.
	conf.TrailingLogs = 0
	conf.SnapshotThreshold = 1 << 60
	conf.SnapshotInterval = time.Hour
	return conf
}

type assuranceResultMono struct {
	scenario        string
	staleSuffix     bool // isolated node's last index was above the snapshot index
	storeMonotonic  bool
	snapshotIndex   uint64
	oldLastBefore   uint64
	oldLastAfter    uint64
	oldAppliedAfter uint64
	oldCommitAfter  uint64
	leaderLastAfter uint64
	leaderCommit    uint64
	stalled         bool
	caughtUp        bool
}

func waitFirstLeaderMono(t *testing.T, c *cluster, d time.Duration) *Raft {
	t.Helper()
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		leaders := c.GetInState(Leader)
		if len(leaders) == 1 {
			return leaders[0]
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("no stable leader")
	return nil
}

func waitLeaderExcludingMono(t *testing.T, c *cluster, exclude *Raft, d time.Duration) *Raft {
	t.Helper()
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		for _, r := range c.rafts {
			if r != exclude && r.State() == Leader {
				return r
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("no leader excluding isolated node")
	return nil
}

// runScenarioMono is runScenario with a selectable log store type. With
// monotonic=true, installSnapshot's removeOldLogs deletes all logs up to the
// snapshot's last index (including any above-snapshot suffix bytes), so a
// persistent stall can only come from the cached last-log index/term.
func runScenarioMono(t *testing.T, scenario string, monotonic bool, prefix, tail, extra, post int) assuranceResultMono {
	t.Helper()
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:           3,
		Bootstrap:       true,
		Conf:            assuranceConfMono(),
		MonotonicLogs:   monotonic,
		LongstopTimeout: 60 * time.Second,
	})
	defer c.Close()

	old := waitFirstLeaderMono(t, c, 10*time.Second)
	if err := old.Barrier(2 * time.Second).Error(); err != nil {
		t.Fatalf("barrier: %v", err)
	}
	for i := 0; i < prefix; i++ {
		f := old.Apply([]byte(fmt.Sprintf("prefix-%d", i)), 2*time.Second)
		if err := f.Error(); err != nil {
			t.Fatalf("prefix apply: %v", err)
		}
	}
	c.WaitForReplication(prefix)

	c.Partition([]ServerAddress{old.localAddr})

	for i := 0; i < tail; i++ {
		old.Apply([]byte(fmt.Sprintf("tail-%d", i)), 0)
	}
	oldLastBefore := old.LastIndex()

	nl := waitLeaderExcludingMono(t, c, old, 10*time.Second)
	if err := nl.Barrier(2 * time.Second).Error(); err != nil {
		t.Fatalf("new leader barrier: %v", err)
	}
	for i := 0; i < extra; i++ {
		f := nl.Apply([]byte(fmt.Sprintf("extra-%d", i)), 2*time.Second)
		if err := f.Error(); err != nil {
			t.Fatalf("extra apply: %v", err)
		}
	}
	if err := nl.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	snaps, err := nl.snapshots.List()
	if err != nil || len(snaps) == 0 {
		t.Fatalf("no snapshot: %v %v", snaps, err)
	}
	snapIdx := snaps[0].Index

	for i := 0; i < post; i++ {
		f := nl.Apply([]byte(fmt.Sprintf("post-%d", i)), 2*time.Second)
		if err := f.Error(); err != nil {
			t.Fatalf("post apply: %v", err)
		}
	}
	leaderCommit := nl.CommitIndex()

	if tail > 0 && oldLastBefore <= uint64(prefix) {
		t.Fatalf("isolated node tail was not appended: last=%d prefix=%d", oldLastBefore, prefix)
	}

	t.Logf("[CA] %s monotonic=%t prefix=%d tail=%d extra=%d post=%d snapshotIndex=%d oldLastBefore=%d leaderCommit=%d",
		scenario, monotonic, prefix, tail, extra, post, snapIdx, oldLastBefore, leaderCommit)

	c.FullyConnect()
	time.Sleep(1500 * time.Millisecond)
	applied1 := old.AppliedIndex()
	time.Sleep(3 * time.Second)
	applied2 := old.AppliedIndex()

	res := assuranceResultMono{
		scenario:        scenario,
		staleSuffix:     oldLastBefore > snapIdx,
		storeMonotonic:  monotonic,
		snapshotIndex:   snapIdx,
		oldLastBefore:   oldLastBefore,
		oldLastAfter:    old.LastIndex(),
		oldAppliedAfter: applied2,
		oldCommitAfter:  old.CommitIndex(),
		leaderLastAfter: nl.LastIndex(),
		leaderCommit:    leaderCommit,
	}
	res.caughtUp = applied2 >= leaderCommit
	res.stalled = !res.caughtUp && applied1 == applied2
	// Emit before the deferred c.Close() runs, so a slow helper shutdown cannot
	// hide an already completed measurement.
	emitMono(res)
	return res
}

func emitMono(r assuranceResultMono) {
	fmt.Printf("CA_EVENT {\"event\":\"scenario_setup\",\"scenario\":%q,\"stale_suffix\":%t,\"store_monotonic\":%t,\"snapshot_index\":%d,\"old_last_before\":%d}\n",
		r.scenario, r.staleSuffix, r.storeMonotonic, r.snapshotIndex, r.oldLastBefore)
	fmt.Printf("CA_EVENT {\"event\":\"snapshot_catchup_result\",\"scenario\":%q,\"stale_suffix\":%t,\"store_monotonic\":%t,\"snapshot_index\":%d,\"old_last_before\":%d,\"old_last_after\":%d,\"old_applied_after\":%d,\"old_commit_after\":%d,\"leader_last_after\":%d,\"leader_commit_index\":%d,\"stalled\":%t,\"isolated_caught_up\":%t}\n",
		r.scenario, r.staleSuffix, r.storeMonotonic, r.snapshotIndex, r.oldLastBefore, r.oldLastAfter,
		r.oldAppliedAfter, r.oldCommitAfter, r.leaderLastAfter, r.leaderCommit, r.stalled, r.caughtUp)
}

func TestAssuranceSnapshotStaleSuffixMonotonic(t *testing.T) {
	// Control: non-monotonic store, isolated log ends below the snapshot index.
	runScenarioMono(t, "control_catchup", false, 20, 2, 20, 10)

	// Non-monotonic store, isolated log extends above the snapshot index.
	runScenarioMono(t, "case_nonmonotonic_stall", false, 20, 200, 20, 10)

	// Monotonic store, same stale suffix; removeOldLogs deletes the bytes but
	// the cached last-log state is not reset.
	runScenarioMono(t, "case_monotonic_stall", true, 20, 200, 20, 10)
}
