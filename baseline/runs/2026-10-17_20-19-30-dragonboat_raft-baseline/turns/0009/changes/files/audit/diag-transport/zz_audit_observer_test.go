//go:build dragonboat_audit

// Audit-only check of the documented observer capabilities: an observer can
// initiate both proposals and linearizable reads (raft package doc, section
// 4.2.1 / "non-voting member" notes; nodehost docs for AddObserver).

package dragonboat

import (
	"testing"
	"time"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

func TestAuditObserverReadAndPropose(t *testing.T) {
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

	pto := lpto(nh1)
	rs, err := nh1.RequestAddObserver(1, 3, nodeHostTestAddr3, 0, pto)
	if err != nil {
		t.Fatalf("RequestAddObserver: %v", err)
	}
	if v := <-rs.ResultC(); !v.Completed() {
		t.Fatalf("add observer was not completed (rejected=%t)", v.Rejected())
	}
	ocfg := config.Config{
		ClusterID:    1,
		NodeID:       3,
		ElectionRTT:  10,
		HeartbeatRTT: 1,
		IsObserver:   true,
	}
	if err := nh3.StartCluster(nil, true, createSM, ocfg); err != nil {
		t.Fatalf("start observer: %v", err)
	}
	waitForLeaderToBeElected(t, nh3, 1)

	rtt := nh3.NodeHostConfig().RTTMillisecond
	timeout := time.Duration(rtt*45) * time.Millisecond
	// observer can propose
	session := nh3.GetNoOPSession(1)
	start := time.Now()
	rs, err = nh3.Propose(session, []byte("from-observer"), timeout)
	if err != nil {
		t.Fatalf("observer propose: %v", err)
	}
	if v := <-rs.ResultC(); !v.Completed() {
		t.Fatalf("observer proposal did not complete (dropped=%t timeout=%t)",
			v.Dropped(), v.Timeout())
	}
	t.Logf("observer proposal completed in %v", time.Since(start))
	// observer can do linearizable reads
	for i := 0; i < 3; i++ {
		start = time.Now()
		rs, err = nh3.ReadIndex(1, timeout)
		if err != nil {
			t.Fatalf("observer read index: %v", err)
		}
		v := <-rs.ResultC()
		if !v.Completed() {
			t.Fatalf("observer ReadIndex did not complete (dropped=%t timeout=%t)",
				v.Dropped(), v.Timeout())
		}
		t.Logf("round %d: observer read index completed in %v", i, time.Since(start))
	}
}
