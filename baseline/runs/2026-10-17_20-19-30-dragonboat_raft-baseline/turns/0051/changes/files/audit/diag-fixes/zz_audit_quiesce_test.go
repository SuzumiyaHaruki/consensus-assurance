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

// The quiesce implementation is only unit tested at the quiesceState level.
// This checks the end-to-end behaviour the feature promises: an idle cluster
// enters quiesce and still answers a linearizable read, and a proposal after
// quiesce is committed and visible to a read on the other node.
func TestAuditReadAndProposeAfterQuiesce(t *testing.T) {
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
	createSM := func(uint64, uint64) sm.IStateMachine {
		return &counterStateMachine{}
	}
	peers := map[uint64]string{1: nodeHostTestAddr1, 2: nodeHostTestAddr2}
	cfg := config.Config{
		ClusterID:    1,
		NodeID:       1,
		ElectionRTT:  10,
		HeartbeatRTT: 1,
		Quiesce:      true,
	}
	if err := nh1.StartCluster(peers, false, createSM, cfg); err != nil {
		t.Fatalf("start node 1: %v", err)
	}
	cfg.NodeID = 2
	if err := nh2.StartCluster(peers, false, createSM, cfg); err != nil {
		t.Fatalf("start node 2: %v", err)
	}
	waitForLeaderToBeElected(t, nh1, 1)
	waitForLeaderToBeElected(t, nh2, 1)
	timeout := auditTimeout(nh1, 300)
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	if _, err := nh1.SyncPropose(ctx, nh1.GetNoOPSession(1), []byte("x")); err != nil {
		cancel()
		t.Fatalf("proposal before quiesce: %v", err)
	}
	cancel()
	// threshold() is electionTick*10 = 100 ticks; one tick per RTT (10 ms).
	time.Sleep(3 * time.Second)
	for i, nh := range []*NodeHost{nh1, nh2} {
		ctx, cancel := context.WithTimeout(context.Background(), timeout)
		v, err := nh.SyncRead(ctx, 1, nil)
		cancel()
		if err != nil {
			t.Fatalf("read on nh%d after idle (quiesce): %v", i+1, err)
		}
		if v.(uint64) != 1 {
			t.Fatalf("read on nh%d returned %v, want 1", i+1, v)
		}
	}
	ctx, cancel = context.WithTimeout(context.Background(), timeout)
	r, err := nh1.SyncPropose(ctx, nh1.GetNoOPSession(1), []byte("y"))
	cancel()
	if err != nil {
		t.Fatalf("proposal after quiesce: %v", err)
	}
	ctx, cancel = context.WithTimeout(context.Background(), timeout)
	v, err := nh2.SyncRead(ctx, 1, nil)
	cancel()
	if err != nil {
		t.Fatalf("read after quiesce proposal: %v", err)
	}
	if v.(uint64) != r.Value {
		t.Fatalf("read %v, want %v", v, r.Value)
	}
}

// The quiesced follower's clock only advances electionTick; it never starts an
// election on its own. After the leader of an idle (quiesced) three-node
// cluster is lost, the cluster must therefore recover once a client request
// arrives - the request exits quiesce and normal election timeouts apply.
func TestAuditProposeAfterLeaderLossWhileQuiesced(t *testing.T) {
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
			if nh != nil {
				nh.Stop()
			}
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
	time.Sleep(3 * time.Second) // let every node enter quiesce
	leaderID, ok, err := hosts[0].GetLeaderID(1)
	if err != nil || !ok {
		t.Fatalf("leader unknown: %v %v", ok, err)
	}
	hosts[leaderID-1].Stop()
	hosts[leaderID-1] = nil
	survivor := hosts[0]
	if leaderID == 1 {
		survivor = hosts[1]
	}
	// A proposal forwarded to the dead leader is dropped, as in any leader
	// change, so retry like a real client until the cluster has recovered.
	deadline := time.Now().Add(3 * timeout)
	var lastErr error
	for time.Now().Before(deadline) {
		ctx, cancel = context.WithTimeout(context.Background(), time.Second)
		_, lastErr = survivor.SyncPropose(ctx, survivor.GetNoOPSession(1),
			[]byte("y"))
		cancel()
		if lastErr == nil {
			return
		}
	}
	t.Fatalf("cluster did not recover after losing quiesced leader %d: %v",
		leaderID, lastErr)
}
