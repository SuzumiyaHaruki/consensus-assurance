// Audit diagnostic test (added for the consensus-assurance audit; NOT part of
// the captured implementation). It exercises crash-fault tolerance using the
// in-memory transport, because the sandbox forbids AF_INET and the shipped
// integration tests (integ_test.go) require TCP.
package raft

import (
	"fmt"
	"math/rand"
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

// TestAudit_RandomizedSafety drives a 3-node cluster through randomized
// partitions, heals, leadership transfers and snapshots while applying
// commands, then checks a core linearizability invariant: every command whose
// apply future returned success (i.e. was acknowledged as committed) must be
// present in *every* node's applied state once the cluster has healed.
func TestAudit_RandomizedSafety(t *testing.T) {
	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	c := MakeCluster(3, t, conf)
	defer c.Close()

	acked := make(map[string]bool)
	rng := rand.New(rand.NewSource(time.Now().UnixNano()))

	apply := func(cmd string) {
		leaders := c.GetInState(Leader)
		if len(leaders) != 1 {
			return
		}
		f := leaders[0].Apply([]byte(cmd), time.Second)
		if err := f.Error(); err == nil {
			acked[cmd] = true
		}
	}

	steps := 120
	for i := 0; i < steps; i++ {
		switch rng.Intn(10) {
		case 0, 1, 2, 3, 4, 5:
			apply(fmt.Sprintf("cmd-%d-%d", time.Now().UnixNano(), i))
		case 6:
			if ns := c.GetInState(Leader); len(ns) > 0 {
				_ = ns[0].LeadershipTransfer().Error()
			}
		case 7:
			// isolate a random node
			if ns := c.rafts; len(ns) > 0 {
				c.Disconnect(ns[rng.Intn(len(ns))].localAddr)
			}
		case 8:
			c.FullyConnect()
		case 9:
			if ns := c.GetInState(Leader); len(ns) > 0 {
				_ = ns[0].Snapshot().Error()
			}
		}
		time.Sleep(time.Duration(rng.Intn(8)+1) * time.Millisecond)
	}

	// Heal completely and let the cluster converge.
	c.FullyConnect()
	if !waitConverged(t, c, 0, "randomized-final") {
		t.Fatalf("cluster did not converge after randomized churn")
	}
	c.EnsureSame(t)

	// Every acknowledged command must exist in every node's applied log.
	for i := range c.rafts {
		fsm := getMockFSM(c.fsms[i])
		fsm.Lock()
		present := make(map[string]bool, len(fsm.logs))
		for _, l := range fsm.logs {
			present[string(l)] = true
		}
		fsm.Unlock()
		for cmd := range acked {
			if !present[cmd] {
				t.Fatalf("node %d lost acknowledged command %q", i, cmd)
			}
		}
	}

	// Raft Log Matching Property: if two logs contain an entry with the same
	// index, the entries are identical (same term, type and data).
	type entryID struct {
		term uint64
		typ  LogType
		data string
	}
	logsByNode := make([]map[uint64]entryID, len(c.rafts))
	for i := range c.rafts {
		m := make(map[uint64]entryID)
		first, _ := c.stores[i].FirstIndex()
		last, _ := c.stores[i].LastIndex()
		if first != 0 {
			for idx := first; idx <= last; idx++ {
				var l Log
				if err := c.stores[i].GetLog(idx, &l); err != nil {
					break
				}
				m[idx] = entryID{l.Term, l.Type, string(l.Data)}
			}
		}
		logsByNode[i] = m
	}
	for i := 0; i < len(logsByNode); i++ {
		for j := i + 1; j < len(logsByNode); j++ {
			for idx, ei := range logsByNode[i] {
				if ej, ok := logsByNode[j][idx]; ok && ei != ej {
					t.Fatalf("log matching violated between nodes %d and %d at index %d: %+v vs %+v",
						i, j, idx, ei, ej)
				}
			}
		}
	}
	t.Logf("acked=%d, randomized safety check passed", len(acked))
}
