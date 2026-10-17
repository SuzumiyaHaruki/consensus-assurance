package raft

import (
	"fmt"
	"io"
	"runtime"
	"strings"
	"testing"
	"time"
)

type probeFSM struct {
	applied int
}

func (f *probeFSM) Apply(*Log) interface{} {
	f.applied++
	return nil
}

func (f *probeFSM) Snapshot() (FSMSnapshot, error) { return &probeSnap{}, nil }
func (f *probeFSM) Restore(rc io.ReadCloser) error  { return nil }

type probeSnap struct{}

func (s *probeSnap) Persist(SnapshotSink) error { return nil }
func (s *probeSnap) Release()                  {}

func seedCommittedLogs(t *testing.T, n uint64) (*InmemCommitTrackingStore, *Config) {
	t.Helper()
	store := NewInmemCommitTrackingStore()
	logs := make([]*Log, 0, n)
	for i := uint64(1); i <= n; i++ {
		logs = append(logs, &Log{Index: i, Term: 1, Type: LogCommand, Data: []byte("x")})
	}
	if err := store.StoreLogs(logs); err != nil {
		t.Fatalf("store logs: %v", err)
	}
	if err := store.StageCommitIndex(n); err != nil {
		t.Fatalf("stage commit: %v", err)
	}
	conf := DefaultConfig()
	conf.LocalID = "node1"
	conf.RestoreCommittedLogs = true
	conf.LogLevel = "ERROR"
	return store, conf
}

func runNewRaft(t *testing.T, n uint64) (returned bool, err error, applied int) {
	t.Helper()
	store, conf := seedCommittedLogs(t, n)
	fsm := &probeFSM{}
	snaps := NewInmemSnapshotStore()
	_, trans := NewInmemTransport("node1")
	done := make(chan error, 1)
	var r *Raft
	go func() {
		var e error
		r, e = NewRaft(conf, fsm, store, store, snaps, trans)
		done <- e
	}()
	select {
	case e := <-done:
		if e == nil {
			t.Cleanup(func() { _ = r.Shutdown().Error() })
		}
		return true, e, fsm.applied
	case <-time.After(20 * time.Second):
		return false, nil, fsm.applied
	}
}

func TestProbeRestoreCommittedLogsStartup(t *testing.T) {
	for _, n := range []uint64{8192, 8193, 8320} {
		t.Run(fmt.Sprintf("entries_%d", n), func(t *testing.T) {
			returned, err, applied := runNewRaft(t, n)
			t.Logf("entries=%d batches=%d NewRaft_returned=%v err=%v fsm_applied=%d",
				n, (n+63)/64, returned, err, applied)
			if !returned {
				t.Errorf("NewRaft did not return for %d committed entries", n)
				dumpRaftStacks(t)
			}
		})
	}
}

func dumpRaftStacks(t *testing.T) {
	t.Helper()
	buf := make([]byte, 1<<20)
	n := runtime.Stack(buf, true)
	var keep []string
	for _, block := range strings.Split(string(buf[:n]), "\n\n") {
		if strings.Contains(block, "processLogs") || strings.Contains(block, "applyBatch") ||
			strings.Contains(block, "NewRaft") {
			keep = append(keep, block)
		}
	}
	t.Logf("matched goroutines:\n%s", strings.Join(keep, "\n\n"))
}

// TestProbeRealPrefix builds a genuine single-node cluster, commits enough
// commands through the real leader path, shuts it down, then restarts from the
// same stores with RestoreCommittedLogs enabled.
func TestProbeRealPrefix(t *testing.T) {
	store := NewInmemCommitTrackingStore()
	snaps := NewInmemSnapshotStore()
	_, trans := NewInmemTransport("node1")
	conf := DefaultConfig()
	conf.LocalID = "node1"
	conf.HeartbeatTimeout = 50 * time.Millisecond
	conf.ElectionTimeout = 50 * time.Millisecond
	conf.LeaderLeaseTimeout = 50 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.LogLevel = "ERROR"
	// The commit-tracking store only records commit progress while this option
	// is enabled, so the producing run must have it enabled as well.
	conf.RestoreCommittedLogs = true
	config := Configuration{Servers: []Server{{Suffrage: Voter, ID: "node1", Address: trans.LocalAddr()}}}
	if err := BootstrapCluster(conf, store, store, snaps, trans, config); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	fsm := &probeFSM{}
	r, err := NewRaft(conf, fsm, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("new raft: %v", err)
	}
	deadline := time.Now().Add(10 * time.Second)
	for r.Leader() == "" && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if r.Leader() == "" {
		t.Fatalf("no leader")
	}
	start := time.Now()
	const n = 8300
	var last ApplyFuture
	for i := 0; i < n; i++ {
		last = r.Apply([]byte("x"), 5*time.Second)
	}
	if err := last.Error(); err != nil {
		t.Fatalf("apply: %v", err)
	}
	applyDur := time.Since(start)
	ci, _ := store.GetCommitIndex()
	li, _ := store.LastIndex()
	t.Logf("applied %d commands in %v; staged_commit=%d last_log=%d fsm_applied=%d",
		n, applyDur, ci, li, fsm.applied)
	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}

	_, trans2 := NewInmemTransport("node1")
	conf2 := *conf
	done := make(chan error, 1)
	go func() {
		_, e := NewRaft(&conf2, fsm, store, store, snaps, trans2)
		done <- e
	}()
	select {
	case e := <-done:
		t.Logf("restart returned err=%v", e)
	case <-time.After(10 * time.Second):
		t.Logf("restart did NOT return (staged_commit=%d batches=%d)", ci, (ci+63)/64)
		dumpRaftStacks(t)
	}
}
