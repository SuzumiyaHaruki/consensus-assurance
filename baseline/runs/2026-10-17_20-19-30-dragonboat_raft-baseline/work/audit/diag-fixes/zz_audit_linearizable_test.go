//go:build dragonboat_audit

// Audit-only linearizability smoke check: after a completed proposal, any read
// that starts later must observe that proposal's effect (or a later one).

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

type counterStateMachine struct {
	mu    sync.Mutex
	count uint64
}

func (s *counterStateMachine) Update([]byte) (sm.Result, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.count++
	return sm.Result{Value: s.count}, nil
}

func (s *counterStateMachine) Lookup(interface{}) (interface{}, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.count, nil
}

func (s *counterStateMachine) SaveSnapshot(w io.Writer,
	_ sm.ISnapshotFileCollection, _ <-chan struct{}) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	buf := make([]byte, 8)
	binary.LittleEndian.PutUint64(buf, s.count)
	_, err := w.Write(buf)
	return err
}

func (s *counterStateMachine) RecoverFromSnapshot(r io.Reader,
	_ []sm.SnapshotFile, _ <-chan struct{}) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	buf := make([]byte, 8)
	if _, err := io.ReadFull(r, buf); err != nil {
		return err
	}
	s.count = binary.LittleEndian.Uint64(buf)
	return nil
}

func (s *counterStateMachine) Close() error { return nil }

type linearizabilityObservation struct {
	writeDone time.Time
	writeVal  uint64
	readStart time.Time
	readVal   uint64
}

func TestAuditLinearizableReadUnderConcurrency(t *testing.T) {
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
	timeout := auditTimeout(nh, 100)
	const (
		workers = 4
		iters   = 40
	)
	var mu sync.Mutex
	observations := make([]linearizabilityObservation, 0)
	var wg sync.WaitGroup
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			session := nh.GetNoOPSession(1)
			for i := 0; i < iters; i++ {
				ctx, cancel := context.WithTimeout(context.Background(), timeout)
				r, err := nh.SyncPropose(ctx, session, []byte("x"))
				cancel()
				if err != nil {
					t.Errorf("proposal failed: %v", err)
					return
				}
				writeDone := time.Now()
				ctx, cancel = context.WithTimeout(context.Background(), timeout)
				readStart := time.Now()
				v, err := nh.SyncRead(ctx, 1, nil)
				cancel()
				if err != nil {
					t.Errorf("read failed: %v", err)
					return
				}
				mu.Lock()
				observations = append(observations, linearizabilityObservation{
					writeDone: writeDone,
					writeVal:  r.Value,
					readStart: readStart,
					readVal:   v.(uint64),
				})
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	if t.Failed() {
		return
	}
	margin := time.Millisecond
	for _, o := range observations {
		if o.writeDone.Add(margin).Before(o.readStart) && o.readVal < o.writeVal {
			t.Fatalf("stale linearizable read: write %d completed at %v, read started at %v returned %d",
				o.writeVal, o.writeDone, o.readStart, o.readVal)
		}
	}
	t.Logf("checked %d write/read pairs", len(observations))
}

// Same property across a two-node cluster: proposals and reads are issued on
// both NodeHosts (forwarded when needed) and a completed write must be visible
// to any read that starts later.
func TestAuditLinearizableReadAcrossNodes(t *testing.T) {
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
	timeout := auditTimeout(nh1, 200)
	const (
		workers = 4
		iters   = 30
	)
	var mu sync.Mutex
	observations := make([]linearizabilityObservation, 0)
	var wg sync.WaitGroup
	hosts := []*NodeHost{nh1, nh2}
	for w := 0; w < workers; w++ {
		w := w
		wg.Add(1)
		go func() {
			defer wg.Done()
			writeHost := hosts[w%2]
			readHost := hosts[(w+1)%2]
			session := writeHost.GetNoOPSession(1)
			for i := 0; i < iters; i++ {
				ctx, cancel := context.WithTimeout(context.Background(), timeout)
				r, err := writeHost.SyncPropose(ctx, session, []byte("x"))
				cancel()
				if err != nil {
					t.Errorf("proposal failed: %v", err)
					return
				}
				writeDone := time.Now()
				ctx, cancel = context.WithTimeout(context.Background(), timeout)
				readStart := time.Now()
				v, err := readHost.SyncRead(ctx, 1, nil)
				cancel()
				if err != nil {
					t.Errorf("read failed: %v", err)
					return
				}
				mu.Lock()
				observations = append(observations, linearizabilityObservation{
					writeDone: writeDone,
					writeVal:  r.Value,
					readStart: readStart,
					readVal:   v.(uint64),
				})
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	if t.Failed() {
		return
	}
	margin := time.Millisecond
	for _, o := range observations {
		if o.writeDone.Add(margin).Before(o.readStart) && o.readVal < o.writeVal {
			t.Fatalf("stale cross-node read: write %d completed at %v, read started at %v returned %d",
				o.writeVal, o.writeDone, o.readStart, o.readVal)
		}
	}
	t.Logf("checked %d cross-node write/read pairs", len(observations))
}
