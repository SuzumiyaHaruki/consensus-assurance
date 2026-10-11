package raft

// Assurance exploration harness against the captured hashicorp/raft snapshot.
// It is not part of the target source and only uses exported plus same-package
// test facilities.

import (
	"fmt"
	"testing"
	"time"
)

func assuranceConf() *Config {
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

type assuranceResult struct {
	event           string
	staleSuffix     bool // isolated node's last index was above the snapshot index
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

func waitFirstLeader(t *testing.T, c *cluster, d time.Duration) *Raft {
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

func waitLeaderExcluding(t *testing.T, c *cluster, exclude *Raft, d time.Duration) *Raft {
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

// runScenario builds a 3 node in-memory cluster, isolates the leader, lets it
// append `tail` uncommitted entries, then lets the replacement leader commit
// `extra` entries and take a snapshot at index S. It then commits `post` more
// entries and reconnects the isolated node, measuring whether that node
// catches up.
func runScenario(t *testing.T, event string, prefix, tail, extra, post int) assuranceResult {
	t.Helper()
	c := MakeCluster(3, t, assuranceConf())
	defer c.Close()

	old := waitFirstLeader(t, c, 10*time.Second)
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

	// Isolate the current leader from the other two nodes, which retain quorum.
	c.Partition([]ServerAddress{old.localAddr})

	// Append an uncommitted tail while the isolated node still believes it is
	// the leader.
	for i := 0; i < tail; i++ {
		old.Apply([]byte(fmt.Sprintf("tail-%d", i)), 0)
	}
	oldLastBefore := old.LastIndex()

	nl := waitLeaderExcluding(t, c, old, 10*time.Second)
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

	// Commit entries above the snapshot index; a correctly caught-up follower
	// must receive them.
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

	t.Logf("[CA] %s prefix=%d tail=%d extra=%d post=%d snapshotIndex=%d oldLastBefore=%d leaderCommit=%d",
		event, prefix, tail, extra, post, snapIdx, oldLastBefore, leaderCommit)

	c.FullyConnect()
	time.Sleep(1500 * time.Millisecond)
	applied1 := old.AppliedIndex()
	time.Sleep(3 * time.Second)
	applied2 := old.AppliedIndex()

	res := assuranceResult{
		event:           event,
		staleSuffix:     oldLastBefore > snapIdx,
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
	return res
}

func emit(name string, r assuranceResult) {
	// Admission event for the executed prefix; identity fields (scenario,
	// snapshot_index, old_last_before) are shared with the result event so the
	// engine can correlate them.
	fmt.Printf("CA_EVENT {\"event\":\"scenario_setup\",\"scenario\":%q,\"stale_suffix\":%t,\"snapshot_index\":%d,\"old_last_before\":%d}\n",
		name, r.staleSuffix, r.snapshotIndex, r.oldLastBefore)
	// Result event for the same operation; applicability is selected by
	// stale_suffix and the assertion is the required (healthy) property, so a
	// stalled case appears as a violating witness.
	fmt.Printf("CA_EVENT {\"event\":\"snapshot_catchup_result\",\"scenario\":%q,\"stale_suffix\":%t,\"snapshot_index\":%d,\"old_last_before\":%d,\"old_last_after\":%d,\"old_applied_after\":%d,\"old_commit_after\":%d,\"leader_last_after\":%d,\"leader_commit_index\":%d,\"stalled\":%t,\"isolated_caught_up\":%t}\n",
		name, r.staleSuffix, r.snapshotIndex, r.oldLastBefore, r.oldLastAfter, r.oldAppliedAfter,
		r.oldCommitAfter, r.leaderLastAfter, r.leaderCommit, r.stalled, r.caughtUp)
}

func TestAssuranceSnapshotStaleSuffix(t *testing.T) {
	// Control: the isolated node's log ends below the replacement leader's
	// snapshot index.
	control := runScenario(t, "control_catchup", 20, 2, 20, 10)
	emit(control.event, control)

	// Case: the isolated node's log extends above the snapshot index.
	stuck := runScenario(t, "case_no_progress", 20, 200, 20, 10)
	emit(stuck.event, stuck)
}
