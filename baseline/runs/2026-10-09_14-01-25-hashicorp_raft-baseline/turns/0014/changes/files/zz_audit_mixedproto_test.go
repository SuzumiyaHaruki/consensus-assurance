//go:build auditdiag

// AUDIT DIAGNOSTIC FILE (not part of the captured implementation).
// Built only with: go test -tags auditdiag ...
//
// Mixed protocol-version stress: a protocol-2 cluster grows a protocol-3 node,
// then runs continuous writes across leader-isolation partitions. Verifies all
// FSMs converge to an identical applied sequence and no acked command is lost.
// This targets the version-gated config/`prepareLog` paths.
package raft

import (
	"bytes"
	"fmt"
	"sync"
	"testing"
	"time"
)

func TestAuditMixedProtocolInvariants(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 2
	c := MakeCluster(3, t, conf)
	defer c.Close()

	conf = inmemConfig(t)
	conf.ProtocolVersion = 3
	c1 := MakeClusterNoBootstrap(1, t, conf)
	defer c1.Close()

	c.Merge(c1)
	c.FullyConnect()

	l := auditWaitLeader(c, 10*time.Second)
	if l == nil {
		t.Fatal("no leader")
	}
	if err := l.AddVoter(c1.rafts[0].localID, c1.rafts[0].localAddr, 0, 2*time.Second).Error(); err != nil {
		t.Fatalf("AddVoter: %v", err)
	}

	// Wait for all nodes to adopt the 4-voter config before stressing.
	deadline := time.Now().Add(10 * time.Second)
	for {
		base := c.getConfiguration(c.rafts[0])
		same := true
		for i, r := range c.rafts {
			if i == 0 {
				continue
			}
			if len(c.getConfiguration(r).Servers) != len(base.Servers) {
				same = false
				break
			}
		}
		if same || time.Now().After(deadline) {
			break
		}
		time.Sleep(10 * time.Millisecond)
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
			ld := auditLeader(c)
			if ld == nil {
				time.Sleep(5 * time.Millisecond)
				continue
			}
			cmd := []byte(fmt.Sprintf("mcmd-%d", i))
			if err := ld.Apply(cmd, 200*time.Millisecond).Error(); err == nil {
				mu.Lock()
				applied = append(applied, cmd)
				mu.Unlock()
			}
			time.Sleep(time.Millisecond)
		}
	}()

	for round := 0; round < 3; round++ {
		ld := auditLeader(c)
		if ld == nil {
			ld = auditWaitLeader(c, 5*time.Second)
		}
		if ld == nil {
			break
		}
		c.Disconnect(ld.localAddr)
		time.Sleep(250 * time.Millisecond)
		c.FullyConnect()
		time.Sleep(250 * time.Millisecond)
	}

	close(stop)
	wg.Wait()
	c.FullyConnect()

	deadline = time.Now().Add(15 * time.Second)
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
		time.Sleep(50 * time.Millisecond)
	}

	mu.Lock()
	appliedCopy := append([][]byte(nil), applied...)
	mu.Unlock()

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
	idx := make(map[string]bool, len(logs[0]))
	for _, lg := range logs[0] {
		idx[string(lg)] = true
	}
	missing := 0
	for _, cmd := range appliedCopy {
		if !idx[string(cmd)] {
			missing++
		}
	}
	t.Logf("nodes=%d acked=%d node0_applied=%d missing=%d", len(logs), len(appliedCopy), len(logs[0]), missing)
	if missing != 0 {
		t.Errorf("%d acked commands missing", missing)
	}
}
