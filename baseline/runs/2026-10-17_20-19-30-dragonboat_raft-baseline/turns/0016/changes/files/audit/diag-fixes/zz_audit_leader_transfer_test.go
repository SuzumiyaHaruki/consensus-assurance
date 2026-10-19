//go:build dragonboat_audit

// Audit-only end-to-end leadership transfer check. The captured
// TestNodeHostLeadershipTransfer only requests a transfer from a node to
// itself (a no-op), so the documented RequestLeaderTransfer behaviour is not
// exercised by the upstream suite.

package dragonboat

import (
	"testing"
	"time"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

func TestAuditLeaderTransfer(t *testing.T) {
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
	leader, follower := nh1, nh2
	leaderNode, followerNode := uint64(1), uint64(2)
	if leaderID != 1 {
		leader, follower = nh2, nh1
		leaderNode, followerNode = 2, 1
	}
	t.Logf("initial leader is node %d", leaderNode)

	// make sure the follower has every entry the leader has: in a two-node
	// cluster a committed proposal is on both nodes by definition
	pto := lpto(leader)
	session := leader.GetNoOPSession(1)
	rs, err := leader.Propose(session, []byte("before-transfer"), pto)
	if err != nil {
		t.Fatalf("propose: %v", err)
	}
	if v := <-rs.ResultC(); !v.Completed() {
		t.Fatalf("proposal before transfer did not complete")
	}

	if err := leader.RequestLeaderTransfer(1, followerNode); err != nil {
		t.Fatalf("RequestLeaderTransfer: %v", err)
	}
	t.Logf("requested transfer from node %d to node %d", leaderNode, followerNode)
	transferred := false
	for i := 0; i < 500; i++ {
		id, ready, err := follower.GetLeaderID(1)
		if err == nil && ready && id == followerNode {
			transferred = true
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if !transferred {
		id, ready, err := follower.GetLeaderID(1)
		t.Fatalf("leadership was not transferred: follower sees leader %d ready=%t err=%v",
			id, ready, err)
	}
	t.Logf("node %d is now the leader", followerNode)
	// the old leader must also see the new leader
	if id, ready, err := leader.GetLeaderID(1); err != nil || !ready || id != followerNode {
		t.Fatalf("old leader sees %d ready=%t err=%v, want %d",
			id, ready, err, followerNode)
	}
	// proposals must commit under the new leader
	session = follower.GetNoOPSession(1)
	rs, err = follower.Propose(session, []byte("after-transfer"), pto)
	if err != nil {
		t.Fatalf("propose after transfer: %v", err)
	}
	if v := <-rs.ResultC(); !v.Completed() {
		t.Fatalf("proposal after transfer did not complete")
	}
}
