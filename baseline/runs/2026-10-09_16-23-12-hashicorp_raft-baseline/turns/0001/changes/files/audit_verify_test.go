package raft_test

import (
	"fmt"
	"io"
	"testing"
	"time"

	raft "github.com/hashicorp/raft"
)

func auditWait(t *testing.T, limit time.Duration, what string, f func() bool) {
	t.Helper()
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if f() {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s", what)
}

// Only public APIs and the supplied in-memory stores/transport/FSM are used.
// Different legal local timeouts make the old-leader/new-leader overlap
// deterministic; VerifyLeader must obtain a voting quorum regardless of timers.
func TestAuditVerifyLeaderNonvoter(t *testing.T) {
	for _, connectedNonvoter := range []bool{true, false} {
		t.Run(fmt.Sprintf("nonvoter_connected=%v", connectedNonvoter), func(t *testing.T) {
			const n = 4
			var nodes [n]*raft.Raft
			var trans [n]*raft.InmemTransport
			var fsms [n]*raft.MockFSM
			configuration := raft.Configuration{}
			for i := 0; i < n; i++ {
				addr := raft.ServerAddress(fmt.Sprintf("audit-node-%d", i))
				_, trans[i] = raft.NewInmemTransport(addr)
				suffrage := raft.Voter
				if i == 3 {
					suffrage = raft.Nonvoter
				}
				configuration.Servers = append(configuration.Servers, raft.Server{ID: raft.ServerID(addr), Address: addr, Suffrage: suffrage})
			}
			for i := range trans {
				for j := range trans {
					if i != j {
						trans[i].Connect(trans[j].LocalAddr(), trans[j])
					}
				}
			}
			defer func() {
				var futures []raft.Future
				for _, node := range nodes {
					if node != nil {
						futures = append(futures, node.Shutdown())
					}
				}
				for _, f := range futures {
					if err := f.Error(); err != nil {
						t.Error(err)
					}
				}
			}()
			for i := 0; i < n; i++ {
				cfg := raft.DefaultConfig()
				cfg.LocalID = configuration.Servers[i].ID
				cfg.LogOutput = io.Discard
				cfg.HeartbeatTimeout = time.Second
				cfg.ElectionTimeout = time.Second
				cfg.LeaderLeaseTimeout = time.Second
				cfg.CommitTimeout = 5 * time.Millisecond
				if i == 1 || i == 2 {
					cfg.HeartbeatTimeout = 5 * time.Second
					cfg.ElectionTimeout = 5 * time.Second
					cfg.LeaderLeaseTimeout = 50 * time.Millisecond
				}
				store := raft.NewInmemStore()
				snaps := raft.NewInmemSnapshotStore()
				fsms[i] = &raft.MockFSM{}
				if err := raft.BootstrapCluster(cfg, store, store, snaps, trans[i], configuration); err != nil {
					t.Fatal(err)
				}
				var err error
				nodes[i], err = raft.NewRaft(cfg, fsms[i], store, store, snaps, trans[i])
				if err != nil {
					t.Fatal(err)
				}
			}
			auditWait(t, 4*time.Second, "node 0 elected", func() bool { return nodes[0].State() == raft.Leader })
			if err := nodes[0].Apply([]byte("before partition"), time.Second).Error(); err != nil {
				t.Fatal(err)
			}
			auditWait(t, time.Second, "initial replication", func() bool { return len(fsms[1].Logs()) == 1 && len(fsms[2].Logs()) == 1 && len(fsms[3].Logs()) == 1 })
			// Leave voter 0 with nonvoter 3; voters 1 and 2 form the other side.
			for _, i := range []int{0, 3} {
				for _, j := range []int{1, 2} {
					trans[i].Disconnect(trans[j].LocalAddr())
					trans[j].Disconnect(trans[i].LocalAddr())
				}
			}
			if !connectedNonvoter {
				trans[0].Disconnect(trans[3].LocalAddr())
				trans[3].Disconnect(trans[0].LocalAddr())
			}
			for _, i := range []int{1, 2} {
				cfg := nodes[i].ReloadableConfig()
				cfg.HeartbeatTimeout = 100 * time.Millisecond
				cfg.ElectionTimeout = 100 * time.Millisecond
				if err := nodes[i].ReloadConfig(cfg); err != nil {
					t.Fatal(err)
				}
			}
			var newLeader *raft.Raft
			auditWait(t, 700*time.Millisecond, "majority elects a new leader", func() bool {
				for _, i := range []int{1, 2} {
					if nodes[i].State() == raft.Leader {
						newLeader = nodes[i]
						return true
					}
				}
				return false
			})
			if err := newLeader.Apply([]byte("committed after partition"), time.Second).Error(); err != nil {
				t.Fatal(err)
			}
			if nodes[0].State() != raft.Leader {
				t.Fatal("old leader already stepped down; overlap not reproduced")
			}
			err := nodes[0].VerifyLeader().Error()
			oldLogs := fsms[0].Logs()
			t.Logf("old term=%d new term=%d old FSM=%q new FSM=%q VerifyLeader error=%v", nodes[0].CurrentTerm(), newLeader.CurrentTerm(), oldLogs, fsms[newLeaderIndex(nodes, newLeader)].Logs(), err)
			if len(oldLogs) != 1 {
				t.Fatalf("expected stale old FSM, got %q", oldLogs)
			}
			if err == nil {
				t.Error("VerifyLeader succeeded on stale leader using only itself and a nonvoter; the voting majority has already committed on a new leader")
			}
		})
	}
}

func newLeaderIndex(nodes [4]*raft.Raft, target *raft.Raft) int {
	for i, node := range nodes {
		if node == target {
			return i
		}
	}
	panic("leader not found")
}
