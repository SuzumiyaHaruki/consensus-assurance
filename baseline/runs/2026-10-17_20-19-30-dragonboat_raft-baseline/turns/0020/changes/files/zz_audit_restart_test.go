//go:build dragonboat_audit

// Audit-only crash/restart endurance check: repeatedly stop and restart a
// NodeHost (including snapshot creation) and verify that the state machine's
// applied state survives every restart and that new proposals keep
// committing.

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

type auditStateMachine struct {
	mu    sync.Mutex
	count uint64
	last  []byte
}

func (s *auditStateMachine) Update(data []byte) (sm.Result, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.count++
	s.last = append([]byte{}, data...)
	return sm.Result{Value: s.count}, nil
}

func (s *auditStateMachine) Lookup(query interface{}) (interface{}, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.count, nil
}

func (s *auditStateMachine) SaveSnapshot(w io.Writer,
	_ sm.ISnapshotFileCollection, _ <-chan struct{}) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	buf := make([]byte, 16+len(s.last))
	binary.LittleEndian.PutUint64(buf, s.count)
	binary.LittleEndian.PutUint64(buf[8:], uint64(len(s.last)))
	copy(buf[16:], s.last)
	_, err := w.Write(buf)
	return err
}

func (s *auditStateMachine) RecoverFromSnapshot(r io.Reader,
	_ []sm.SnapshotFile, _ <-chan struct{}) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	hdr := make([]byte, 16)
	if _, err := io.ReadFull(r, hdr); err != nil {
		return err
	}
	s.count = binary.LittleEndian.Uint64(hdr)
	sz := binary.LittleEndian.Uint64(hdr[8:])
	s.last = make([]byte, sz)
	_, err := io.ReadFull(r, s.last)
	return err
}

func (s *auditStateMachine) Close() error { return nil }

func TestAuditRestartEndurance(t *testing.T) {
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
	mk := func() *config.NodeHostConfig {
		return &config.NodeHostConfig{
			WALDir:         dir,
			NodeHostDir:    dir,
			RTTMillisecond: getRTTMillisecond(fs, dir),
			RaftAddress:    singleNodeHostTestAddr,
			Expert:         getTestExpertConfig(fs),
		}
	}
	createSM := func(uint64, uint64) sm.IStateMachine { return &auditStateMachine{} }
	cfg := config.Config{ClusterID: 1, NodeID: 1, ElectionRTT: 10, HeartbeatRTT: 1}
	nh, err := NewNodeHost(*mk())
	if err != nil {
		t.Fatalf("NewNodeHost: %v", err)
	}
	if err := nh.StartCluster(map[uint64]string{1: singleNodeHostTestAddr},
		false, createSM, cfg); err != nil {
		t.Fatalf("StartCluster: %v", err)
	}
	waitForLeaderToBeElected(t, nh, 1)
	rtt := nh.NodeHostConfig().RTTMillisecond
	timeout := time.Duration(rtt*60) * time.Millisecond
	expected := uint64(0)
	propose := func() {
		session := nh.GetNoOPSession(1)
		ctx, cancel := context.WithTimeout(context.Background(), timeout)
		defer cancel()
		r, err := nh.SyncPropose(ctx, session, []byte("payload"))
		if err != nil {
			t.Fatalf("proposal failed: %v", err)
		}
		expected++
		if r.Value != expected {
			t.Fatalf("state machine count %d, want %d", r.Value, expected)
		}
	}
	check := func() {
		for i := 0; i < 100; i++ {
			ctx, cancel := context.WithTimeout(context.Background(), timeout)
			v, err := nh.SyncRead(ctx, 1, nil)
			cancel()
			if err == nil {
				if got := v.(uint64); got != expected {
					t.Fatalf("after restart state machine count %d, want %d", got, expected)
				}
				return
			}
			time.Sleep(time.Duration(rtt) * time.Millisecond)
		}
		t.Fatalf("read did not succeed after restart")
	}
	for round := 0; round < 5; round++ {
		propose()
		propose()
		if round%2 == 0 {
			ctx, cancel := context.WithTimeout(context.Background(), timeout)
			idx, err := nh.SyncRequestSnapshot(ctx, 1, SnapshotOption{})
			cancel()
			if err != nil {
				t.Fatalf("snapshot failed: %v", err)
			}
			t.Logf("round %d: snapshot at index %d, count %d", round, idx, expected)
		}
		nh.Stop()
		nh, err = NewNodeHost(*mk())
		if err != nil {
			t.Fatalf("restart NewNodeHost: %v", err)
		}
		if err := nh.StartCluster(nil, false, createSM, cfg); err != nil {
			t.Fatalf("restart StartCluster: %v", err)
		}
		waitForLeaderToBeElected(t, nh, 1)
		check()
		t.Logf("round %d: restarted with count %d", round, expected)
	}
	propose()
	check()
	nh.Stop()
}
