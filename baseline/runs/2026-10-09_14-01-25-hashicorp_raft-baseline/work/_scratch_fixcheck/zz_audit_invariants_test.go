//go:build auditdiag

// AUDIT DIAGNOSTIC FILE (not part of the captured implementation).
// Built only with: go test -tags auditdiag ...
//
// Independent invariant harness: drives a 5-node in-memory cluster under
// random leader-isolation partitions and checks, after healing, that
// (a) all FSMs converge to an identical applied-command sequence and
// (b) every command whose Apply() reported success is present in every FSM.
// This does not rely on the repository's own assertions.
package raft

import (
	"bytes"
	"fmt"
	"math/rand"
	"sync"
	"testing"
	"time"
)

func auditLeader(c *cluster) *Raft {
	for _, r := range c.rafts {
		if r.State() == Leader {
			return r
		}
	}
	return nil
}

func auditWaitLeader(c *cluster, d time.Duration) *Raft {
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		if l := auditLeader(c); l != nil {
			return l
		}
		time.Sleep(5 * time.Millisecond)
	}
	return nil
}

func auditFSMLogs(c *cluster) [][][]byte {
	out := make([][][]byte, len(c.fsms))
	for i, f := range c.fsms {
		m := getMockFSM(f)
		m.Lock()
		cp := make([][]byte, len(m.logs))
		for j, l := range m.logs {
			cp[j] = append([]byte(nil), l...)
		}
		m.Unlock()
		out[i] = cp
	}
	return out
}

func TestAuditRandomPartitionInvariants(t *testing.T) {
	conf := inmemConfig(t)
	c := MakeCluster(5, t, conf)
	defer c.Close()

	if auditWaitLeader(c, 10*time.Second) == nil {
		t.Fatal("no leader elected")
	}

	var mu sync.Mutex
	var applied [][]byte
	stop := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; ; i++ {
			select {
			case <-stop:
				return
			default:
			}
			l := auditLeader(c)
			if l == nil {
				time.Sleep(5 * time.Millisecond)
				continue
			}
			cmd := []byte(fmt.Sprintf("cmd-%d", i))
			if err := l.Apply(cmd, 200*time.Millisecond).Error(); err == nil {
				mu.Lock()
				applied = append(applied, cmd)
				mu.Unlock()
			}
			time.Sleep(time.Millisecond)
		}
	}()

	rng := rand.New(rand.NewSource(1))
	for round := 0; round < 4; round++ {
		l := auditLeader(c)
		if l == nil {
			l = auditWaitLeader(c, 5*time.Second)
		}
		if l == nil {
			t.Fatalf("round %d: no leader to isolate", round)
		}
		c.Disconnect(l.localAddr)
		// Let a new leader emerge on the majority side.
		time.Sleep(time.Duration(150+rng.Intn(200)) * time.Millisecond)
		c.FullyConnect()
		time.Sleep(time.Duration(100+rng.Intn(200)) * time.Millisecond)
	}

	close(stop)
	wg.Wait()
	c.FullyConnect()

	// Wait for FSM convergence (10s).
	deadline := time.Now().Add(10 * time.Second)
	var logs [][][]byte
	for {
		logs = auditFSMLogs(c)
		converged := true
		for i := 1; i < len(logs); i++ {
			if len(logs[i]) != len(logs[0]) {
				converged = false
				break
			}
			for j := range logs[0] {
				if !bytes.Equal(logs[i][j], logs[0][j]) {
					converged = false
					break
				}
			}
			if !converged {
				break
			}
		}
		if converged || time.Now().After(deadline) {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}

	mu.Lock()
	appliedCopy := append([][]byte(nil), applied...)
	mu.Unlock()

	// Check 1: identical applied sequence across all nodes.
	for i := 1; i < len(logs); i++ {
		if len(logs[i]) != len(logs[0]) {
			t.Errorf("FSM length mismatch: node0=%d node%d=%d", len(logs[0]), i, len(logs[i]))
			continue
		}
		for j := range logs[0] {
			if !bytes.Equal(logs[i][j], logs[0][j]) {
				t.Errorf("FSM content mismatch at %d: node0=%q node%d=%q", j, logs[0][j], i, logs[i][j])
				break
			}
		}
	}

	// Check 2: every applied-and-acked command is present on node 0.
	idx := make(map[string]bool, len(logs[0]))
	for _, l := range logs[0] {
		idx[string(l)] = true
	}
	missing := 0
	for _, cmd := range appliedCopy {
		if !idx[string(cmd)] {
			missing++
		}
	}
	t.Logf("rounds=4 acked=%d node0_applied=%d missing=%d", len(appliedCopy), len(logs[0]), missing)
	if missing != 0 {
		t.Errorf("%d acked commands are missing from the FSM", missing)
	}
}
