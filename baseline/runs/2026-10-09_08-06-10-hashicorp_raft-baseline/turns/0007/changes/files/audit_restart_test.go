package raft

// Diagnostic-only crash/restart durability test (NOT part of the captured
// implementation).
//
// Simulates node crashes (clean Shutdown, which drops all in-flight state but
// preserves the persistent stores) and restarts the node with the same
// log/stable/snapshot stores and transport. It then asserts that the restarted
// node catches up and that every node's FSM applies the identical sequence
// (Raft's core durability/state-machine-safety guarantee under crash faults).

import (
	"fmt"
	"testing"
	"time"
)

func auditApplyN(t *testing.T, leader *Raft, tag string, n int) {
	for i := 0; i < n; i++ {
		f := leader.Apply([]byte(fmt.Sprintf("%s-%d", tag, i)), 5*time.Second)
		if err := f.Error(); err != nil {
			t.Fatalf("apply %s-%d: %v", tag, i, err)
		}
	}
}

// auditRestart re-creates a node in place using its persistent stores.
func auditRestart(t *testing.T, c *cluster, r *Raft) {
	idx := c.IndexOf(r)
	if idx < 0 {
		t.Fatalf("node not in cluster")
	}
	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}
	cfg := r.config()
	nr, err := NewRaft(&cfg, &MockFSM{}, r.logs, r.stable, r.snapshots, r.trans)
	if err != nil {
		t.Fatalf("restart NewRaft: %v", err)
	}
	c.rafts[idx] = nr
	c.fsms[idx] = nr.fsm
}

func TestAudit_RestartRecovery(t *testing.T) {
	c := MakeCluster(3, t, inmemConfig(t))
	defer c.Close()

	leader := c.Leader()
	auditApplyN(t, leader, "pre", 25)
	if err := auditWaitConverge(c, 30*time.Second); err != nil {
		t.Fatalf("pre-restart convergence: %v", err)
	}
	// Force a snapshot so restarts exercise the snapshot-restore path.
	if err := leader.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	t.Logf("snapshot taken at pre-restart")

	// Crash + restart a follower.
	followers := c.Followers()
	if len(followers) == 0 {
		t.Fatal("no followers")
	}
	victim := followers[0]
	victimID := victim.localID
	t.Logf("crashing follower %v", victimID)
	auditRestart(t, c, victim)

	// Writes while the follower is down.
	leader = c.Leader()
	auditApplyN(t, leader, "mid", 15)

	if err := auditWaitConverge(c, 30*time.Second); err != nil {
		t.Fatalf("post-follower-restart convergence: %v", err)
	}
	t.Logf("follower %v restarted and converged", victimID)

	// Crash + restart the current leader.
	oldLeader := c.Leader()
	oldLeaderID := oldLeader.localID
	t.Logf("crashing leader %v", oldLeaderID)
	auditRestart(t, c, oldLeader)

	// A new leader should emerge and accept writes.
	newLeader := auditWaitLeader(t, c, 30*time.Second)
	t.Logf("new leader %v (was %v)", newLeader.localID, oldLeaderID)
	auditApplyN(t, newLeader, "post", 15)

	if err := auditWaitConverge(c, 30*time.Second); err != nil {
		t.Fatalf("post-leader-restart convergence: %v", err)
	}
	t.Logf("SUMMARY converged; finalLogLen=%d", len(getMockFSM(c.fsms[0]).logs))
}

// auditWaitLeader polls for exactly one leader up to deadline, returning it, or
// failing with the observed per-node states.
func auditWaitLeader(t *testing.T, c *cluster, deadline time.Duration) *Raft {
	end := time.Now().Add(deadline)
	var last []RaftState
	for time.Now().Before(end) {
		leaders := c.GetInState(Leader)
		if len(leaders) == 1 {
			return leaders[0]
		}
		last = last[:0]
		for _, r := range c.rafts {
			last = append(last, r.State())
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("no single leader within %v; states=%v", deadline, last)
	return nil
}
