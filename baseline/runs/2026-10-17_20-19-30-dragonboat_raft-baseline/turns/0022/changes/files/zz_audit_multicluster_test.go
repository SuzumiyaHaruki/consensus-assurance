//go:build dragonboat_audit

// Audit-only multi-cluster isolation check: two independent single-node
// clusters on one NodeHost must keep separate replicated state across a
// snapshot and a NodeHost restart.

package dragonboat

import (
	"context"
	"testing"
	"time"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

func TestAuditMultipleClustersOnOneNodeHost(t *testing.T) {
	fs := vfs.GetTestFS()
	dir := singleNodeHostTestDir
	if err := fs.RemoveAll(dir); err != nil {
		t.Fatalf("%v", err)
	}
	defer func() {
		if err := fs.RemoveAll(dir); err != nil {
			t.Fatalf("%v", err)
		}
	}()
	mk := func() *config.NodeHostConfig {
		return &config.NodeHostConfig{
			WALDir:         dir,
			NodeHostDir:    dir,
			RTTMillisecond: getRTTMillisecond(fs, dir),
			RaftAddress:    singleNodeHostTestAddr,
			Expert:         getTestExpertConfig(fs),
		}
	}
	createSM := func(uint64, uint64) sm.IStateMachine {
		return &counterStateMachine{}
	}
	peers := map[uint64]string{1: singleNodeHostTestAddr}
	nh, err := NewNodeHost(*mk())
	if err != nil {
		t.Fatalf("NewNodeHost: %v", err)
	}
	start := func(nh *NodeHost, join bool, members map[uint64]string) {
		for _, cid := range []uint64{1, 2} {
			c := config.Config{ClusterID: cid, NodeID: 1, ElectionRTT: 10, HeartbeatRTT: 1}
			if err := nh.StartCluster(members, join, createSM, c); err != nil {
				t.Fatalf("start cluster %d: %v", cid, err)
			}
		}
		for _, cid := range []uint64{1, 2} {
			waitForLeaderToBeElected(t, nh, cid)
		}
	}
	start(nh, false, peers)
	timeout := time.Duration(nh.NodeHostConfig().RTTMillisecond*100) * time.Millisecond
	propose := func(cid uint64, n int) {
		session := nh.GetNoOPSession(cid)
		for i := 0; i < n; i++ {
			ctx, cancel := context.WithTimeout(context.Background(), timeout)
			_, err := nh.SyncPropose(ctx, session, []byte("x"))
			cancel()
			if err != nil {
				t.Fatalf("cluster %d proposal failed: %v", cid, err)
			}
		}
	}
	propose(1, 3)
	propose(2, 5)
	for _, cid := range []uint64{1, 2} {
		ctx, cancel := context.WithTimeout(context.Background(), timeout)
		if _, err := nh.SyncRequestSnapshot(ctx, cid, SnapshotOption{}); err != nil {
			cancel()
			t.Fatalf("cluster %d snapshot failed: %v", cid, err)
		}
		cancel()
	}
	nh.Stop()
	nh, err = NewNodeHost(*mk())
	if err != nil {
		t.Fatalf("restart NewNodeHost: %v", err)
	}
	defer nh.Stop()
	start(nh, false, nil)
	want := map[uint64]uint64{1: 3, 2: 5}
	for _, cid := range []uint64{1, 2} {
		got := uint64(0)
		ok := false
		for i := 0; i < 100; i++ {
			ctx, cancel := context.WithTimeout(context.Background(), timeout)
			v, err := nh.SyncRead(ctx, cid, nil)
			cancel()
			if err == nil {
				got = v.(uint64)
				ok = true
				break
			}
			time.Sleep(time.Duration(nh.NodeHostConfig().RTTMillisecond) * time.Millisecond)
		}
		if !ok {
			t.Fatalf("cluster %d read did not succeed after restart", cid)
		}
		if got != want[cid] {
			t.Fatalf("cluster %d has count %d after restart, want %d", cid, got, want[cid])
		}
		t.Logf("cluster %d count %d after restart", cid, got)
	}
}
