//go:build dragonboat_audit

// Audit-only end-to-end check of membership-change rejections: a witness can
// not be promoted to a voting member and a voting member can not be turned
// into a witness. Both must be rejected cleanly (the raft layer panics if such
// a change is ever applied).

package dragonboat

import (
	"context"
	"testing"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

func TestAuditMembershipRejections(t *testing.T) {
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
	addrs := []string{nodeHostTestAddr1, nodeHostTestAddr2, nodeHostTestAddr3}
	hosts := make([]*NodeHost, 3)
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
	waitForLeaderToBeElected(t, hosts[0], 1)
	pto := lpto(hosts[0])
	rs, err := hosts[0].RequestAddWitness(1, 3, addrs[2], 0, pto)
	if err != nil {
		t.Fatalf("RequestAddWitness: %v", err)
	}
	if v := <-rs.ResultC(); !v.Completed() {
		t.Fatalf("add witness did not complete")
	}
	wcfg := config.Config{ClusterID: 1, NodeID: 3, ElectionRTT: 10, HeartbeatRTT: 1, IsWitness: true}
	if err := hosts[2].StartCluster(nil, true, createSM, wcfg); err != nil {
		t.Fatalf("start witness: %v", err)
	}
	waitForLeaderToBeElected(t, hosts[2], 1)

	// witness -> voting member must be rejected, not applied (applying it would
	// panic in the raft layer)
	rs, err = hosts[0].RequestAddNode(1, 3, addrs[2], 0, pto)
	if err != nil {
		t.Fatalf("promoting a witness returned an error instead of a result: %v", err)
	}
	if v := <-rs.ResultC(); !v.Rejected() {
		t.Fatalf("promoting a witness was not rejected (completed=%t)", v.Completed())
	}
	// voting member -> witness must be rejected too
	rs, err = hosts[0].RequestAddWitness(1, 1, addrs[0], 0, pto)
	if err != nil {
		t.Fatalf("adding a voter as witness returned an error: %v", err)
	}
	if v := <-rs.ResultC(); !v.Rejected() {
		t.Fatalf("adding a voter as witness was not rejected (completed=%t)", v.Completed())
	}
	// membership must be unchanged and the cluster must still work
	timeout := auditTimeout(hosts[0], 100)
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	m, err := hosts[0].SyncGetClusterMembership(ctx, 1)
	cancel()
	if err != nil {
		t.Fatalf("membership: %v", err)
	}
	if _, ok := m.Witnesses[3]; !ok {
		t.Fatalf("node 3 is no longer a witness: %v", m.Witnesses)
	}
	if _, ok := m.Nodes[1]; !ok {
		t.Fatalf("node 1 is no longer a regular member: %v", m.Nodes)
	}
	session := hosts[0].GetNoOPSession(1)
	ctx, cancel = context.WithTimeout(context.Background(), timeout)
	if _, err := hosts[0].SyncPropose(ctx, session, []byte("still-works")); err != nil {
		cancel()
		t.Fatalf("proposal after rejected changes failed: %v", err)
	}
	cancel()
	t.Logf("rejections handled cleanly; nodes=%v witnesses=%v", m.Nodes, m.Witnesses)
}
