//go:build dragonboat_audit

// Audit-only end-to-end check of leader self-removal: a two-node cluster whose
// leader deletes itself must leave the other node as a working single-node
// cluster, and the removed node must drop the cluster.

package dragonboat

import (
	"context"
	"testing"
	"time"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

func TestAuditLeaderSelfRemoval(t *testing.T) {
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
	addrs := []string{nodeHostTestAddr1, nodeHostTestAddr2}
	hosts := make([]*NodeHost, 2)
	for i, addr := range addrs {
		nh, err := NewNodeHost(*mk(addr, addr))
		if err != nil {
			t.Fatalf("nodehost %d: %v", i, err)
		}
		hosts[i] = nh
	}
	defer func() {
		for _, nh := range hosts {
			nh.Stop()
		}
	}()
	createSM := func(uint64, uint64) sm.IStateMachine { return &PST{} }
	peers := map[uint64]string{1: addrs[0], 2: addrs[1]}
	for i := 0; i < 2; i++ {
		cfg := config.Config{ClusterID: 1, NodeID: uint64(i + 1), ElectionRTT: 10, HeartbeatRTT: 1}
		if err := hosts[i].StartCluster(peers, false, createSM, cfg); err != nil {
			t.Fatalf("start node %d: %v", i+1, err)
		}
	}
	for i := 0; i < 2; i++ {
		waitForLeaderToBeElected(t, hosts[i], 1)
	}
	leaderID, ready, err := hosts[0].GetLeaderID(1)
	if err != nil || !ready {
		t.Fatalf("no leader: %v %t", err, ready)
	}
	leader := hosts[leaderID-1]
	survivor := hosts[2-leaderID]
	pto := lpto(leader)
	rs, err := leader.RequestDeleteNode(1, leaderID, 0, pto)
	if err != nil {
		t.Fatalf("RequestDeleteNode: %v", err)
	}
	if v := <-rs.ResultC(); !v.Completed() {
		t.Fatalf("self removal did not complete (rejected=%t)", v.Rejected())
	}
	t.Logf("leader node %d removed itself", leaderID)
	timeout := auditTimeout(leader, 100)
	// the surviving node must become the leader of the remaining single-node
	// cluster and keep committing
	survivorID := uint64(2 - (leaderID - 1))
	newLeader := uint64(0)
	for i := 0; i < 1000; i++ {
		id, ready, err := survivor.GetLeaderID(1)
		if err == nil && ready && id == survivorID {
			newLeader = id
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if newLeader == 0 {
		id, ready, err := survivor.GetLeaderID(1)
		t.Fatalf("survivor did not become leader: sees %d ready=%t err=%v", id, ready, err)
	}
	t.Logf("survivor node %d is the new leader", newLeader)
	session := survivor.GetNoOPSession(1)
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	if _, err := survivor.SyncPropose(ctx, session, []byte("after-self-removal")); err != nil {
		cancel()
		t.Fatalf("proposal after self removal failed: %v", err)
	}
	cancel()
	// the removed node must drop the cluster from its NodeHost
	removed := false
	for i := 0; i < 500; i++ {
		_, _, err := leader.GetLeaderID(1)
		if err == ErrClusterNotFound {
			removed = true
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if !removed {
		_, _, err := leader.GetLeaderID(1)
		t.Fatalf("removed leader still manages the cluster (err=%v)", err)
	}
	t.Logf("removed node no longer manages the cluster")
}
