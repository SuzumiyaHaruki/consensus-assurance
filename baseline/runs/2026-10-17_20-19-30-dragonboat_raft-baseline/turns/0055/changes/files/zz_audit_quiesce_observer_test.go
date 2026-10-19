//go:build dragonboat_audit

// Audit-only check that an observer keeps working while the cluster is
// quiesced: its ReadIndex and proposal are forwarded to the leader, which must
// wake up and answer.

package dragonboat

import (
	"context"
	"testing"
	"time"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

func TestAuditObserverReadAndProposeAfterQuiesce(t *testing.T) {
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
	nh3, err := NewNodeHost(*mk("nh3", nodeHostTestAddr3))
	if err != nil {
		t.Fatalf("nh3: %v", err)
	}
	defer nh3.Stop()

	createSM := func(uint64, uint64) sm.IStateMachine { return &counterStateMachine{} }
	peers := map[uint64]string{1: nodeHostTestAddr1, 2: nodeHostTestAddr2}
	cfg := config.Config{
		ClusterID: 1, NodeID: 1, ElectionRTT: 10, HeartbeatRTT: 1, Quiesce: true,
	}
	if err := nh1.StartCluster(peers, false, createSM, cfg); err != nil {
		t.Fatalf("start node 1: %v", err)
	}
	cfg.NodeID = 2
	if err := nh2.StartCluster(peers, false, createSM, cfg); err != nil {
		t.Fatalf("start node 2: %v", err)
	}
	waitForLeaderToBeElected(t, nh1, 1)
	pto := lpto(nh1)
	rs, err := nh1.RequestAddObserver(1, 3, nodeHostTestAddr3, 0, pto)
	if err != nil {
		t.Fatalf("RequestAddObserver: %v", err)
	}
	if v := <-rs.ResultC(); !v.Completed() {
		t.Fatalf("add observer was not completed (rejected=%t)", v.Rejected())
	}
	ocfg := config.Config{
		ClusterID: 1, NodeID: 3, ElectionRTT: 10, HeartbeatRTT: 1,
		IsObserver: true, Quiesce: true,
	}
	if err := nh3.StartCluster(nil, true, createSM, ocfg); err != nil {
		t.Fatalf("start observer: %v", err)
	}
	waitForLeaderToBeElected(t, nh3, 1)
	timeout := auditTimeout(nh3, 300)
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	if _, err := nh1.SyncPropose(ctx, nh1.GetNoOPSession(1), []byte("x")); err != nil {
		cancel()
		t.Fatalf("proposal before quiesce: %v", err)
	}
	cancel()
	time.Sleep(3 * time.Second)
	ctx, cancel = context.WithTimeout(context.Background(), timeout)
	v, err := nh3.SyncRead(ctx, 1, nil)
	cancel()
	if err != nil {
		t.Fatalf("observer read after quiesce: %v", err)
	}
	if v.(uint64) != 1 {
		t.Fatalf("observer read %v, want 1", v)
	}
	ctx, cancel = context.WithTimeout(context.Background(), timeout)
	if _, err := nh3.SyncPropose(ctx, nh3.GetNoOPSession(1), []byte("y")); err != nil {
		cancel()
		t.Fatalf("observer proposal after quiesce: %v", err)
	}
	cancel()
	ctx, cancel = context.WithTimeout(context.Background(), timeout)
	v, err = nh2.SyncRead(ctx, 1, nil)
	cancel()
	if err != nil {
		t.Fatalf("read after observer proposal: %v", err)
	}
	if v.(uint64) != 2 {
		t.Fatalf("read %v, want 2", v)
	}
}
