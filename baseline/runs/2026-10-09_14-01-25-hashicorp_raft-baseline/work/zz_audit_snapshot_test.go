//go:build auditdiag

// AUDIT DIAGNOSTIC FILE (not part of the captured implementation).
// Built only with: go test -tags auditdiag ...
//
// Exercises snapshot install/compaction under partition: a straggler follower is
// disconnected while the leader commits many entries and takes snapshots, then
// reconnected and required to catch up. Verifies all FSMs converge to an
// identical applied sequence and no acked command is lost.
package raft

import (
	"bytes"
	"fmt"
	"sync"
	"testing"
	"time"
)

func TestAuditSnapshotCatchupInvariants(t *testing.T) {
	conf := inmemConfig(t)
	conf.SnapshotThreshold = 10
	conf.SnapshotInterval = 50 * time.Millisecond
	conf.TrailingLogs = 5
	c := MakeCluster(5, t, conf)
	defer c.Close()

	if auditWaitLeader(c, 10*time.Second) == nil {
		t.Fatal("no leader elected")
	}

	var straggler *Raft
	for _, r := range c.rafts {
		if r.State() == Follower {
			straggler = r
			break
		}
	}
	if straggler == nil {
		t.Fatal("no follower found")
	}
	c.Disconnect(straggler.localAddr)
	t.Logf("disconnected straggler %s", straggler.localID)

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
			cmd := []byte(fmt.Sprintf("scmd-%d", i))
			if err := l.Apply(cmd, 200*time.Millisecond).Error(); err == nil {
				mu.Lock()
				applied = append(applied, cmd)
				mu.Unlock()
			}
			if i%25 == 0 {
				_ = l.Snapshot().Error()
			}
			time.Sleep(time.Millisecond)
		}
	}()

	time.Sleep(1500 * time.Millisecond)
	close(stop)
	wg.Wait()

	// Heal and let the straggler catch up.
	c.FullyConnect()

	deadline := time.Now().Add(15 * time.Second)
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
	for _, l := range logs[0] {
		idx[string(l)] = true
	}
	missing := 0
	for _, cmd := range appliedCopy {
		if !idx[string(cmd)] {
			missing++
		}
	}
	stats := straggler.Stats()
	t.Logf("acked=%d node0_applied=%d missing=%d straggler_last_snapshot=%s straggler_last_idx=%s straggler_applied=%s",
		len(appliedCopy), len(logs[0]), missing, stats["last_snapshot_index"], stats["last_log_index"], stats["applied_index"])
	if missing != 0 {
		t.Errorf("%d acked commands missing", missing)
	}
}
