//go:build dragonboat_audit

// Audit-only large payload check. The upstream large-proposal test is
// commented out in request_test.go because it needs 8GB of RAM; the same code
// path (encoded entries, payload size checks, logdb storage, apply) can be
// exercised with feasible sizes.

package dragonboat

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

func formatSize(sz int) string {
	return fmt.Sprintf("%dMB-%d", sz/(1024*1024), sz)
}

func TestAuditLargeProposal(t *testing.T) {
	fs := vfs.GetTestFS()
	cts := []config.CompressionType{config.NoCompression, config.Snappy}
	sizes := []int{1024 * 1024, 8 * 1024 * 1024, 32 * 1024 * 1024}
	for _, ct := range cts {
		for _, size := range sizes {
			ct := ct
			size := size
			name := "no-compression"
			if ct == config.Snappy {
				name = "snappy"
			}
			t.Run(name+"/"+formatSize(size), func(t *testing.T) {
				to := &testOption{
					defaultTestNode: true,
					updateConfig: func(c *config.Config) *config.Config {
						c.EntryCompressionType = ct
						return c
					},
					tf: func(nh *NodeHost) {
						cs := nh.GetNoOPSession(1)
						timeout := time.Duration(nh.NodeHostConfig().RTTMillisecond*300) * time.Millisecond
						data := make([]byte, size)
						for i := range data {
							data[i] = byte(i)
						}
						ctx, cancel := context.WithTimeout(context.Background(), timeout)
						defer cancel()
						start := time.Now()
						r, err := nh.SyncPropose(ctx, cs, data)
						if err != nil {
							t.Fatalf("proposal of %d bytes failed: %v", size, err)
						}
						if r.Value != uint64(size) {
							t.Fatalf("state machine saw %d bytes, proposed %d", r.Value, size)
						}
						t.Logf("%d bytes committed and applied in %v", size, time.Since(start))
					},
				}
				runNodeHostTest(t, to, fs)
			})
		}
	}
}

// Large entries must also survive the transport path (message batch
// marshaling, tcp framing, receiver queue) between two NodeHosts.
func TestAuditLargeProposalTwoNodes(t *testing.T) {
	fs := vfs.GetTestFS()
	base := singleNodeHostTestDir
	if err := fs.RemoveAll(base); err != nil {
		t.Fatalf("%v", err)
	}
	defer func() {
		if err := fs.RemoveAll(base); err != nil {
			t.Fatalf("%v", err)
		}
	}()
	mk := func(name string, addr string) *config.NodeHostConfig {
		dir := fs.PathJoin(base, name)
		return &config.NodeHostConfig{
			WALDir:         dir,
			NodeHostDir:    dir,
			RTTMillisecond: getRTTMillisecond(fs, dir),
			RaftAddress:    addr,
			Expert:         getTestExpertConfig(fs),
		}
	}
	nh1, err := NewNodeHost(*mk("nh1", nodeHostTestAddr1))
	if err != nil {
		t.Fatalf("nh1: %v", err)
	}
	defer nh1.Stop()
	nh2, err := NewNodeHost(*mk("nh2", nodeHostTestAddr2))
	if err != nil {
		t.Fatalf("nh2: %v", err)
	}
	defer nh2.Stop()
	createSM := func(uint64, uint64) sm.IStateMachine { return &PST{} }
	peers := map[uint64]string{1: nodeHostTestAddr1, 2: nodeHostTestAddr2}
	cfg := config.Config{ClusterID: 1, NodeID: 1, ElectionRTT: 10, HeartbeatRTT: 1}
	if err := nh1.StartCluster(peers, false, createSM, cfg); err != nil {
		t.Fatalf("start node 1: %v", err)
	}
	cfg.NodeID = 2
	if err := nh2.StartCluster(peers, false, createSM, cfg); err != nil {
		t.Fatalf("start node 2: %v", err)
	}
	waitForLeaderToBeElected(t, nh1, 1)
	waitForLeaderToBeElected(t, nh2, 1)
	leaderID, ready, err := nh1.GetLeaderID(1)
	if err != nil || !ready {
		t.Fatalf("no leader: %v %t", err, ready)
	}
	leader := nh1
	if leaderID != 1 {
		leader = nh2
	}
	for _, size := range []int{8 * 1024 * 1024, 32 * 1024 * 1024} {
		size := size
		t.Run(formatSize(size), func(t *testing.T) {
			cs := leader.GetNoOPSession(1)
			timeout := time.Duration(leader.NodeHostConfig().RTTMillisecond*600) * time.Millisecond
			ctx, cancel := context.WithTimeout(context.Background(), timeout)
			defer cancel()
			data := make([]byte, size)
			for i := range data {
				data[i] = byte(i)
			}
			start := time.Now()
			r, err := leader.SyncPropose(ctx, cs, data)
			if err != nil {
				t.Fatalf("proposal of %d bytes failed: %v", size, err)
			}
			if r.Value != uint64(size) {
				t.Fatalf("state machine saw %d bytes, proposed %d", r.Value, size)
			}
			t.Logf("%d bytes committed across two nodes in %v", size, time.Since(start))
		})
	}
}
