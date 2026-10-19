//go:build dragonboat_audit

// Audit-only reproduction tests. These files are not part of the captured
// implementation; they only exercise it. Delete before any upstream diff.
// Run with: -tags dragonboat_no_rocksdb,dragonboat_audit (needs TCP).

package dragonboat

import (
	"context"
	"testing"
	"time"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

// A membership change issued to an idle (quiesced) cluster must exit quiesce,
// commit, and leave the remaining nodes serving. handleConfigChange records
// pb.ConfigChangeEvent, so this is expected to work; the test pins it.
func TestAuditMembershipChangeAfterQuiesce(t *testing.T) {
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
	addrs := []string{nodeHostTestAddr1, nodeHostTestAddr2, nodeHostTestAddr3}
	hosts := make([]*NodeHost, 3)
	for i, addr := range addrs {
		dir := fs.PathJoin(base, addr)
		nhc := &config.NodeHostConfig{
			WALDir:         dir,
			NodeHostDir:    dir,
			RTTMillisecond: getRTTMillisecond(fs, dir),
			RaftAddress:    addr,
			Expert:         getTestExpertConfig(fs),
		}
		nh, err := NewNodeHost(*nhc)
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
	createSM := func(uint64, uint64) sm.IStateMachine {
		return &counterStateMachine{}
	}
	peers := map[uint64]string{1: addrs[0], 2: addrs[1], 3: addrs[2]}
	for i := 0; i < 3; i++ {
		cfg := config.Config{
			ClusterID:    1,
			NodeID:       uint64(i + 1),
			ElectionRTT:  10,
			HeartbeatRTT: 1,
			Quiesce:      true,
		}
		if err := hosts[i].StartCluster(peers, false, createSM, cfg); err != nil {
			t.Fatalf("start node %d: %v", i+1, err)
		}
	}
	timeout := auditTimeout(hosts[0], 300)
	for i := 0; i < 3; i++ {
		waitForLeaderToBeElected(t, hosts[i], 1)
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	if _, err := hosts[0].SyncPropose(ctx, hosts[0].GetNoOPSession(1), []byte("x")); err != nil {
		cancel()
		t.Fatalf("proposal before quiesce: %v", err)
	}
	cancel()
	time.Sleep(3 * time.Second) // let the cluster enter quiesce
	leaderID, ok, err := hosts[0].GetLeaderID(1)
	if err != nil || !ok {
		t.Fatalf("leader unknown: %v %v", ok, err)
	}
	leader := hosts[leaderID-1]
	target := uint64(1)
	for target == leaderID {
		target++
	}
	// Remove a follower; retry while it is still a member, since the first
	// request can race with the election that wakes the cluster.
	deadline := time.Now().Add(3 * timeout)
	removed := false
	for time.Now().Before(deadline) && !removed {
		ci := leader.GetNodeHostInfo(NodeHostInfoOption{})
		for _, c := range ci.ClusterInfoList {
			if c.ClusterID != 1 {
				continue
			}
			_, stillThere := c.Nodes[target]
			if !stillThere {
				removed = true
			}
		}
		if removed {
			break
		}
		ctx, cancel = context.WithTimeout(context.Background(), time.Second)
		_ = leader.SyncRequestDeleteNode(ctx, 1, target, 0)
		cancel()
	}
	if !removed {
		t.Fatalf("node %d was not removed after quiesce", target)
	}
	ctx, cancel = context.WithTimeout(context.Background(), timeout)
	if _, err := leader.SyncPropose(ctx, leader.GetNoOPSession(1), []byte("y")); err != nil {
		cancel()
		t.Fatalf("proposal after membership change: %v", err)
	}
	cancel()
}
