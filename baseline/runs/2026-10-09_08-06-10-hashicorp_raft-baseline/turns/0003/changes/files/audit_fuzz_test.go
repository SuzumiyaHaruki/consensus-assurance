package raft

// Diagnostic-only randomized consistency stress test (NOT part of the captured
// implementation).
//
// It drives an in-memory cluster through random partitions/heals and command
// traffic, then asserts Raft's core state-machine-safety invariant: every node's
// FSM applies exactly the same sequence of log data (so no committed entry is
// lost, reordered, or duplicated on a node). Convergence is polled with a
// generous deadline so that CPU contention does not create false failures.

import (
	"bytes"
	"fmt"
	"math/rand"
	"testing"
	"time"
)

// auditFSMsEqual reports whether all nodes' MockFSM logs are byte-identical.
func auditFSMsEqual(c *cluster) (bool, string) {
	first := getMockFSM(c.fsms[0])
	first.Lock()
	defer first.Unlock()
	for i := 1; i < len(c.fsms); i++ {
		fsm := getMockFSM(c.fsms[i])
		fsm.Lock()
		if len(first.logs) != len(fsm.logs) {
			fsm.Unlock()
			return false, fmt.Sprintf("len mismatch node0=%d node%d=%d", len(first.logs), i, len(fsm.logs))
		}
		for idx := range first.logs {
			if !bytes.Equal(first.logs[idx], fsm.logs[idx]) {
				fsm.Unlock()
				return false, fmt.Sprintf("node%d diverges at applied idx %d: %q vs %q", i, idx, first.logs[idx], fsm.logs[idx])
			}
		}
		fsm.Unlock()
	}
	return true, ""
}

func auditWaitConverge(c *cluster, deadline time.Duration) error {
	end := time.Now().Add(deadline)
	var last string
	for time.Now().Before(end) {
		if ok, why := auditFSMsEqual(c); ok {
			return nil
		} else {
			last = why
		}
		time.Sleep(10 * time.Millisecond)
	}
	return fmt.Errorf("FSMs did not converge within %v: %s", deadline, last)
}

func auditConsistencyRound(t *testing.T, seed int64, rounds int, nodeCount int) {
	rng := rand.New(rand.NewSource(seed))
	c := MakeCluster(nodeCount, t, inmemConfig(t))
	defer c.Close()

	var applied, failed int
	for round := 0; round < rounds; round++ {
		// Fault FIRST, so writes are attempted while possibly partitioned
		// (minority leader, no-quorum majority, etc.).
		partitioned := 0
		switch rng.Intn(3) {
		case 0: // isolate one node (minority)
			c.Disconnect(c.rafts[rng.Intn(len(c.rafts))].localAddr)
			partitioned = 1
		case 1: // isolate a block of nodes
			if nodeCount >= 3 {
				far := []ServerAddress{c.rafts[0].localAddr, c.rafts[1].localAddr}
				c.Partition(far)
				partitioned = 2
			}
		}

		// Write traffic on whoever is leader right now. Short timeouts so a
		// partitioned (no-quorum) leader does not block the test.
		if l := c.Leader(); l != nil {
			for k := 0; k < 1+rng.Intn(3); k++ {
				f := l.Apply([]byte(fmt.Sprintf("s%d-r%d-k%d", seed, round, k)), 1*time.Second)
				if err := f.Error(); err == nil {
					applied++
				} else {
					failed++
				}
			}
		}
		if partitioned > 0 {
			time.Sleep(time.Duration(10+rng.Intn(150)) * time.Millisecond)
		}

		// Heal and require convergence to a single applied sequence.
		c.FullyConnect()
		if err := auditWaitConverge(c, 30*time.Second); err != nil {
			t.Fatalf("seed %d round %d: %v (applied=%d failed=%d)",
				seed, round, err, applied, failed)
		}
	}
	t.Logf("SUMMARY seed=%d nodes=%d rounds=%d applied=%d failed=%d finalLogLen=%d",
		seed, nodeCount, rounds, applied, failed, len(getMockFSM(c.fsms[0]).logs))
}

func TestAudit_RandomizedConsistency(t *testing.T) {
	auditConsistencyRound(t, 20261009, 120, 3)
	auditConsistencyRound(t, 7777, 80, 5)
}
