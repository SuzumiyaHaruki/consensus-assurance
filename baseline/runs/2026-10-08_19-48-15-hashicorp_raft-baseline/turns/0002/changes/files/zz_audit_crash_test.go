// Audit diagnostic test (added for the consensus-assurance audit; NOT part of
// the captured implementation). It exercises crash-fault tolerance using the
// in-memory transport, because the sandbox forbids AF_INET and the shipped
// integration tests (integ_test.go) require TCP.
package raft

import (
	"fmt"
	"testing"
	"time"
)

// TestAudit_CrashRestartFollower repeatedly crash-restarts a follower while
// writes continue, and requires that (a) commits made while the node was down
// survive, (b) the restarted node rejoins and catches up, and (c) all state
// machines converge to identical contents.
func TestAudit_CrashRestartFollower(t *testing.T) {
	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	c := MakeCluster(3, t, conf)
	defer c.Close()
	for i := range c.rafts {
		t.Logf("start: idx=%d addr=%v id=%v", i, c.rafts[i].localAddr, c.rafts[i].localID)
	}

	apply := func(key string) uint64 {
		leader := c.Leader()
		if leader == nil {
			t.Fatalf("no leader while applying %q", key)
		}
		f := leader.Apply([]byte(key), 0)
		if err := f.Error(); err != nil {
			t.Fatalf("apply %q failed: %v", key, err)
		}
		return f.Index()
	}

	for round := 0; round < 3; round++ {
		for i := 0; i < 20; i++ {
			apply(fmt.Sprintf("r%d-%d", round, i))
		}
		waitConverged(t, c, round, "post-apply")

		followers := c.Followers()
		if len(followers) == 0 {
			t.Fatalf("round %d: no followers to crash", round)
		}
		victim := followers[0]
		idx := c.IndexOf(victim)

		// Crash the follower.
		if err := victim.Shutdown().Error(); err != nil {
			t.Fatalf("round %d: shutdown: %v", round, err)
		}

		// Keep committing while it is down (quorum is the remaining two nodes).
		var committedWhileDown uint64
		for i := 0; i < 10; i++ {
			committedWhileDown = apply(fmt.Sprintf("down-%d-%d", round, i))
		}

		// Restart the follower with its same durable log/stable/snapshot stores.
		// Raft's Shutdown() does not close the transport, so the in-memory
		// transport (and its peer links) can be reused as-is.
		trans := victim.trans.(*InmemTransport)
		cfg := victim.config()
		r, err := NewRaft(&cfg, victim.fsm, victim.logs, victim.stable, victim.snapshots, trans)
		if err != nil {
			t.Fatalf("round %d: restart: %v", round, err)
		}
		c.rafts[idx] = r

		// The cluster must converge, including the restarted node.
		if !waitConverged(t, c, round, "post-restart") {
			t.Fatalf("round %d: restarted node did not rejoin (committed while down=%d)",
				round, committedWhileDown)
		}

		leader := c.Leader()
		if leader == nil {
			t.Fatalf("round %d: no leader after restart", round)
		}
		if got := r.getCommitIndex(); got < committedWhileDown {
			t.Fatalf("round %d: restarted node commit index %d lost committed entry %d",
				round, got, committedWhileDown)
		}
		if got := leader.getCommitIndex(); got < committedWhileDown {
			t.Fatalf("round %d: leader commit index %d regressed below %d",
				round, got, committedWhileDown)
		}
	}
}

// waitConverged waits until every node has applied the same number of entries,
// logging per-node state on timeout. It returns false on timeout.
func waitConverged(t *testing.T, c *cluster, round int, phase string) bool {
	deadline := time.Now().Add(5 * time.Second)
	for {
		applied := make([]uint64, len(c.rafts))
		equal := true
		for i := range c.rafts {
			applied[i] = c.rafts[i].getLastApplied()
			if applied[i] != applied[0] {
				equal = false
			}
		}
		if equal {
			return true
		}
		if time.Now().After(deadline) {
			for i := range c.rafts {
				li, _ := c.rafts[i].getLastLog()
				t.Logf("stuck: round=%d phase=%s idx=%d addr=%v state=%v applied=%d commit=%d lastLog=%d",
					round, phase, i, c.rafts[i].localAddr, c.rafts[i].getState(),
					applied[i], c.rafts[i].getCommitIndex(), li)
			}
			return false
		}
		time.Sleep(50 * time.Millisecond)
	}
}
