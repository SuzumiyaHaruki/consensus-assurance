//go:build dragonboat_audit

// Audit-only reproduction tests. These files are not part of the captured
// implementation; they only exercise it. Delete before any upstream diff.
// Run with: -tags dragonboat_no_rocksdb,dragonboat_audit (needs TCP).

package dragonboat

import (
	"testing"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

// RequestLeaderTransfer with target 0 (NoNode) is accepted by the node and
// then reaches raft, where handleLeaderTransfer panics with "leader transfer
// target not set". The public call has already returned nil by then, and the
// panic lands on the exec-engine step worker, killing the process.
func TestAuditLeaderTransferWithInvalidTargetDoesNotPanic(t *testing.T) {
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
	nhc := &config.NodeHostConfig{
		WALDir:         dir,
		NodeHostDir:    dir,
		RTTMillisecond: getRTTMillisecond(fs, dir),
		RaftAddress:    singleNodeHostTestAddr,
		Expert:         getTestExpertConfig(fs),
	}
	nh, err := NewNodeHost(*nhc)
	if err != nil {
		t.Fatalf("NewNodeHost: %v", err)
	}
	defer nh.Stop()
	createSM := func(uint64, uint64) sm.IStateMachine {
		return &counterStateMachine{}
	}
	cfg := config.Config{ClusterID: 1, NodeID: 1, ElectionRTT: 10, HeartbeatRTT: 1}
	if err := nh.StartCluster(map[uint64]string{1: singleNodeHostTestAddr},
		false, createSM, cfg); err != nil {
		t.Fatalf("StartCluster: %v", err)
	}
	waitForLeaderToBeElected(t, nh, 1)
	if err := nh.RequestLeaderTransfer(1, 0); err == nil {
		t.Fatalf("RequestLeaderTransfer with target 0 returned nil error")
	}
}
