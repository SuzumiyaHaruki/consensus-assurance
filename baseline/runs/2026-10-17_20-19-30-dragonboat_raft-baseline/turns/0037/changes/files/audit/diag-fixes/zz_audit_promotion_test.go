//go:build dragonboat_audit

// Audit-only end-to-end check of observer promotion: after RequestAddNode on an
// existing observer, the promoted node must become a voting member and be able
// to form a quorum together with one regular node.

package dragonboat

import (
	"context"
	"testing"
	"time"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

func TestAuditObserverPromotion(t *testing.T) {
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
	stopped := make(map[*NodeHost]bool)
	stop := func(nh *NodeHost) {
		if !stopped[nh] {
			stopped[nh] = true
			nh.Stop()
		}
	}
	defer func() {
		for _, nh := range hosts {
			stop(nh)
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
	rs, err := hosts[0].RequestAddObserver(1, 3, addrs[2], 0, pto)
	if err != nil {
		t.Fatalf("RequestAddObserver: %v", err)
	}
	if v := <-rs.ResultC(); !v.Completed() {
		t.Fatalf("add observer did not complete")
	}
	ocfg := config.Config{ClusterID: 1, NodeID: 3, ElectionRTT: 10, HeartbeatRTT: 1, IsObserver: true}
	if err := hosts[2].StartCluster(nil, true, createSM, ocfg); err != nil {
		t.Fatalf("start observer: %v", err)
	}
	waitForLeaderToBeElected(t, hosts[2], 1)
	timeout := auditTimeout(hosts[0], 100)
	session := hosts[0].GetNoOPSession(1)
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	if _, err := hosts[0].SyncPropose(ctx, session, []byte("before")); err != nil {
		cancel()
		t.Fatalf("proposal before promotion failed: %v", err)
	}
	cancel()

	// promote the observer; the target is documented as ignored for promotion,
	// but it is still validated up front, so pass the observer's address
	rs, err = hosts[0].RequestAddNode(1, 3, addrs[2], 0, pto)
	if err != nil {
		t.Fatalf("RequestAddNode (promotion): %v", err)
	}
	if v := <-rs.ResultC(); !v.Completed() {
		t.Fatalf("promotion did not complete (rejected=%t)", v.Rejected())
	}
	ctx, cancel = context.WithTimeout(context.Background(), timeout)
	m, err := hosts[0].SyncGetClusterMembership(ctx, 1)
	cancel()
	if err != nil {
		t.Fatalf("membership: %v", err)
	}
	if _, ok := m.Nodes[3]; !ok {
		t.Fatalf("node 3 is not a regular member after promotion: %v", m.Nodes)
	}
	if _, ok := m.Observers[3]; ok {
		t.Fatalf("node 3 is still an observer after promotion")
	}
	t.Logf("promoted: nodes=%v observers=%v", m.Nodes, m.Observers)

	// stop the leader's NodeHost: the remaining two nodes (one of them the
	// promoted node 3) must form the quorum and elect a leader.
	leaderID, ready, err := hosts[0].GetLeaderID(1)
	if err != nil || !ready {
		t.Fatalf("no leader: %v %t", err, ready)
	}
	stop(hosts[leaderID-1])
	survivors := make([]*NodeHost, 0, 2)
	for i, nh := range hosts {
		if uint64(i+1) != leaderID {
			survivors = append(survivors, nh)
		}
	}
	newLeader := uint64(0)
	for i := 0; i < 1000; i++ {
		for _, nh := range survivors {
			id, ready, err := nh.GetLeaderID(1)
			if err == nil && ready && id != leaderID {
				newLeader = id
			}
		}
		if newLeader != 0 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if newLeader == 0 {
		t.Fatalf("no new leader elected by the survivor + promoted observer")
	}
	t.Logf("new leader is node %d (old leader %d stopped)", newLeader, leaderID)
	var lnh *NodeHost
	for i, nh := range hosts {
		if uint64(i+1) == newLeader {
			lnh = nh
		}
	}
	session = lnh.GetNoOPSession(1)
	ctx, cancel = context.WithTimeout(context.Background(), timeout)
	if _, err := lnh.SyncPropose(ctx, session, []byte("after")); err != nil {
		cancel()
		t.Fatalf("proposal after promotion failed: %v", err)
	}
	cancel()
}
