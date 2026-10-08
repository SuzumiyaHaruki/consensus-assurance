// Diagnostic-only test added by the audit. It does NOT modify the captured
// implementation; delete this file to restore the tree to its original shape.
//
// Purpose: show that after AddVoter the Raft nodes DO converge on the new
// configuration, and that testing.go:EnsureSamePeers fails intermittently only
// because it captures peerSet from c.rafts[0] once and never refreshes it.
package raft

import (
	"bytes"
	"fmt"
	"reflect"
	"sync"
	"testing"
	"time"
)

func TestAudit_EnsureSamePeers_StalePeerSetCapture(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 2
	c := MakeCluster(2, t, conf)
	defer c.Close()

	conf = inmemConfig(t)
	conf.ProtocolVersion = 3
	c1 := MakeClusterNoBootstrap(1, t, conf)

	c.Merge(c1)
	c.FullyConnect()

	future := c.Leader().AddVoter(c1.rafts[0].localID, c1.rafts[0].localAddr, 0, 1*time.Second)
	if err := future.Error(); err != nil {
		t.Fatalf("err: %v", err)
	}

	// Mimic exactly what EnsureSamePeers does on its first read.
	peerSet := c.getConfiguration(c.rafts[0])
	t.Logf("captured peerSet from rafts[0] immediately after AddVoter: n=%d %+v",
		len(peerSet.Servers), peerSet)

	// Now poll all nodes and show they converge.
	deadline := time.Now().Add(5 * time.Second)
	for {
		cfgs := make([]Configuration, len(c.rafts))
		for j := range c.rafts {
			cfgs[j] = c.getConfiguration(c.rafts[j])
		}
		converged := true
		for j := 1; j < len(cfgs); j++ {
			if !reflect.DeepEqual(cfgs[0], cfgs[j]) {
				converged = false
			}
		}
		t.Logf("live: rafts[0]=%d rafts[1]=%d rafts[2]=%d converged=%v",
			len(cfgs[0].Servers), len(cfgs[1].Servers), len(cfgs[2].Servers), converged)
		if converged {
			if len(peerSet.Servers) != len(cfgs[0].Servers) {
				t.Logf("CONFIRMED: stale peerSet had %d servers while the cluster live-reports %d; "+
					"EnsureSamePeers compares the stale capture forever and times out",
					len(peerSet.Servers), len(cfgs[0].Servers))
			} else {
				t.Logf("no staleness observed in this run (peerSet was already current)")
			}
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("cluster did not converge to a single configuration within 5s: %+v", cfgs)
		}
		time.Sleep(20 * time.Millisecond)
	}
}

// TestAudit_EnsureSamePeers_Fixed runs the same scenario but with the proposed fix:
// the reference configuration is re-read on every pass of the retry loop. Intended to
// be run with -count=20+ to show it never produces the spurious mismatch.
func TestAudit_EnsureSamePeers_Fixed(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 2
	c := MakeCluster(2, t, conf)
	defer c.Close()

	conf = inmemConfig(t)
	conf.ProtocolVersion = 3
	c1 := MakeClusterNoBootstrap(1, t, conf)

	c.Merge(c1)
	c.FullyConnect()

	future := c.Leader().AddVoter(c1.rafts[0].localID, c1.rafts[0].localAddr, 0, 1*time.Second)
	if err := future.Error(); err != nil {
		t.Fatalf("err: %v", err)
	}

	deadline := time.Now().Add(5 * time.Second)
	for {
		// Proposed fix: refresh the reference node's config each pass.
		peerSet := c.getConfiguration(c.rafts[0])
		same := true
		for i, raft := range c.rafts {
			if i == 0 {
				continue
			}
			if !reflect.DeepEqual(peerSet, c.getConfiguration(raft)) {
				same = false
			}
		}
		if same {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("fixed helper still did not converge within 5s")
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func fsmHasCommand(fsm *MockFSM, cmd []byte) bool {
	fsm.Lock()
	defer fsm.Unlock()
	for _, l := range fsm.logs {
		if bytes.Equal(l, cmd) {
			return true
		}
	}
	return false
}

// TestAudit_CommittedEntriesSurviveChurn is a bounded randomized safety soak:
// it applies commands, repeatedly isolates the current leader to force
// re-elections, heals the cluster, and then asserts that every command that was
// reported committed (Apply returned nil) is present on every replica. A
// committed entry that disappears from any FSM would violate Raft's core safety
// property. Diagnostic-only.
func TestAudit_CommittedEntriesSurviveChurn(t *testing.T) {
	c := MakeCluster(5, t, nil)
	defer c.Close()

	var mu sync.Mutex
	var committed [][]byte
	seen := make(map[string]bool)
	next := 0

	pickLeader := func() *Raft {
		ls := c.GetInState(Leader)
		if len(ls) == 0 {
			return nil
		}
		return ls[0]
	}

	applyOne := func() {
		l := pickLeader()
		if l == nil {
			return
		}
		cmd := []byte(fmt.Sprintf("audit-cmd-%03d", next))
		f := l.Apply(cmd, 2*time.Second)
		if err := f.Error(); err != nil {
			return // not committed on this attempt
		}
		next++
		mu.Lock()
		if !seen[string(cmd)] {
			seen[string(cmd)] = true
			committed = append(committed, cmd)
		}
		mu.Unlock()
	}

	deadline := time.Now().Add(12 * time.Second)
	rounds := 0
	for time.Now().Before(deadline) {
		rounds++
		for i := 0; i < 4; i++ {
			applyOne()
		}
		if l := pickLeader(); l != nil {
			c.Partition([]ServerAddress{l.localAddr})
			time.Sleep(350 * time.Millisecond)
			for i := 0; i < 4; i++ {
				applyOne()
			}
			c.FullyConnect()
			time.Sleep(350 * time.Millisecond)
		}
	}
	c.FullyConnect()

	mu.Lock()
	snapshotCmds := make([][]byte, len(committed))
	copy(snapshotCmds, committed)
	mu.Unlock()
	total := len(snapshotCmds)
	if total == 0 {
		t.Fatalf("soak committed no entries (test ineffective)")
	}

	verifyDeadline := time.Now().Add(10 * time.Second)
	for {
		missing := 0
		for _, cmd := range snapshotCmds {
			for _, fsmRaw := range c.fsms {
				fsm := getMockFSM(fsmRaw)
				if !fsmHasCommand(fsm, cmd) {
					missing++
				}
			}
		}
		if missing == 0 {
			break
		}
		if time.Now().After(verifyDeadline) {
			for i, r := range c.rafts {
				fsm := getMockFSM(c.fsms[i])
				fsm.Lock()
				n := len(fsm.logs)
				fsm.Unlock()
				t.Logf("raft[%d] state=%v fsmLen=%d", i, r.getState(), n)
			}
			t.Fatalf("lost committed entries after churn: %d missing (command,replica) pairs across %d committed entries",
				missing, total)
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Logf("soak ok: %d committed entries over %d churn rounds; all replicas contain every committed entry",
		total, rounds)
}
