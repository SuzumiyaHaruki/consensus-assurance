//go:build dragonboat_audit

// Audit-only end-to-end check of witness voting: a cluster with two regular
// nodes and one witness must be able to elect a new leader after the old
// leader is lost, because the witness provides the second vote in the
// three-member quorum.

package dragonboat

import (
	"testing"
	"time"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

func TestAuditWitnessVotesInElection(t *testing.T) {
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
	nh2, err := NewNodeHost(*mk("nh2", nodeHostTestAddr2))
	if err != nil {
		t.Fatalf("nh2: %v", err)
	}
	nh3, err := NewNodeHost(*mk("nh3", nodeHostTestAddr3))
	if err != nil {
		t.Fatalf("nh3: %v", err)
	}
	stopped := make(map[*NodeHost]bool)
	stop := func(nh *NodeHost) {
		if !stopped[nh] {
			stopped[nh] = true
			nh.Stop()
		}
	}
	defer stop(nh1)
	defer stop(nh2)
	defer stop(nh3)

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

	pto := lpto(nh1)
	rs, err := nh1.RequestAddWitness(1, 3, nodeHostTestAddr3, 0, pto)
	if err != nil {
		t.Fatalf("RequestAddWitness: %v", err)
	}
	if v := <-rs.ResultC(); !v.Completed() {
		t.Fatalf("add witness was not completed (rejected=%t)", v.Rejected())
	}
	wcfg := config.Config{
		ClusterID:    1,
		NodeID:       3,
		ElectionRTT:  10,
		HeartbeatRTT: 1,
		IsWitness:    true,
	}
	if err := nh3.StartCluster(nil, true, createSM, wcfg); err != nil {
		t.Fatalf("start witness: %v", err)
	}
	waitForLeaderToBeElected(t, nh3, 1)

	leaderID, ready, err := nh1.GetLeaderID(1)
	if err != nil || !ready {
		t.Fatalf("no leader: %v %t", err, ready)
	}
	oldLeader, survivor := nh1, nh2
	oldLeaderID, survivorID := uint64(1), uint64(2)
	if leaderID != 1 {
		oldLeader, survivor = nh2, nh1
		oldLeaderID, survivorID = 2, 1
	}
	t.Logf("leader is node %d; stopping its NodeHost", oldLeaderID)
	stop(oldLeader)

	// the surviving regular node plus the witness form a quorum of two.
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
		t.Fatalf("no leader elected after losing the old leader: sees %d ready=%t err=%v",
			id, ready, err)
	}
	t.Logf("node %d is the new leader (witness vote required)", newLeader)
	session := survivor.GetNoOPSession(1)
	rs, err = survivor.Propose(session, []byte("after-leader-loss"), pto)
	if err != nil {
		t.Fatalf("propose after leader loss: %v", err)
	}
	if v := <-rs.ResultC(); !v.Completed() {
		t.Fatalf("proposal after leader loss did not complete")
	}
}
