//go:build dragonboat_audit

// Audit-only state machine convergence check: every replica in a three-node
// cluster must apply exactly the same sequence of proposals, including across
// a snapshot and log compaction.

package dragonboat

import (
	"context"
	"encoding/binary"
	"io"
	"sync"
	"testing"
	"time"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

type checksumStateMachine struct {
	mu    sync.Mutex
	count uint64
	sum   uint64
}

func (s *checksumStateMachine) Update(data []byte) (sm.Result, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.count++
	s.sum += binary.LittleEndian.Uint64(data)
	return sm.Result{Value: s.count, Data: encodeState(s.count, s.sum)}, nil
}

func encodeState(count, sum uint64) []byte {
	buf := make([]byte, 16)
	binary.LittleEndian.PutUint64(buf, count)
	binary.LittleEndian.PutUint64(buf[8:], sum)
	return buf
}

func decodeState(buf []byte) (uint64, uint64) {
	return binary.LittleEndian.Uint64(buf), binary.LittleEndian.Uint64(buf[8:])
}

func (s *checksumStateMachine) Lookup(interface{}) (interface{}, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return encodeState(s.count, s.sum), nil
}

func (s *checksumStateMachine) SaveSnapshot(w io.Writer,
	_ sm.ISnapshotFileCollection, _ <-chan struct{}) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	_, err := w.Write(encodeState(s.count, s.sum))
	return err
}

func (s *checksumStateMachine) RecoverFromSnapshot(r io.Reader,
	_ []sm.SnapshotFile, _ <-chan struct{}) error {
	buf := make([]byte, 16)
	if _, err := io.ReadFull(r, buf); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.count, s.sum = decodeState(buf)
	return nil
}

func (s *checksumStateMachine) Close() error { return nil }

func TestAuditStateMachineConvergence(t *testing.T) {
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
		return &checksumStateMachine{}
	}
	peers := map[uint64]string{1: addrs[0], 2: addrs[1], 3: addrs[2]}
	for i := 0; i < 3; i++ {
		cfg := config.Config{
			ClusterID:    1,
			NodeID:       uint64(i + 1),
			ElectionRTT:  10,
			HeartbeatRTT: 1,
		}
		if err := hosts[i].StartCluster(peers, false, createSM, cfg); err != nil {
			t.Fatalf("start node %d: %v", i+1, err)
		}
	}
	for i := 0; i < 3; i++ {
		waitForLeaderToBeElected(t, hosts[i], 1)
	}
	timeout := auditTimeout(hosts[0], 100)
	session := hosts[0].GetNoOPSession(1)
	var wantSum uint64
	propose := func(n int) {
		for i := 0; i < n; i++ {
			v := uint64(i) + 1
			wantSum += v
			buf := make([]byte, 8)
			binary.LittleEndian.PutUint64(buf, v)
			ctx, cancel := context.WithTimeout(context.Background(), timeout)
			_, err := hosts[0].SyncPropose(ctx, session, buf)
			cancel()
			if err != nil {
				t.Fatalf("proposal %d failed: %v", i, err)
			}
		}
	}
	check := func(count, sum uint64, label string) {
		for i, nh := range hosts {
			var c, s uint64
			ok := false
			for attempt := 0; attempt < 100; attempt++ {
				ctx, cancel := context.WithTimeout(context.Background(), timeout)
				v, err := nh.SyncRead(ctx, 1, nil)
				cancel()
				if err == nil {
					c, s = decodeState(v.([]byte))
					ok = true
					break
				}
				time.Sleep(time.Duration(nh.NodeHostConfig().RTTMillisecond) * time.Millisecond)
			}
			if !ok {
				t.Fatalf("%s: node %d read did not succeed", label, i+1)
			}
			if c != count || s != sum {
				t.Fatalf("%s: node %d has count=%d sum=%d, want count=%d sum=%d",
					label, i+1, c, s, count, sum)
			}
		}
	}
	propose(40)
	check(40, wantSum, "initial")
	// force a snapshot on node 1 and let compaction remove the log
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	if _, err := hosts[0].SyncRequestSnapshot(ctx, 1, SnapshotOption{}); err != nil {
		cancel()
		t.Fatalf("snapshot failed: %v", err)
	}
	cancel()
	propose(20)
	check(60, wantSum, "after snapshot")
	t.Logf("all three nodes converged: count=60 sum=%d", wantSum)
}
