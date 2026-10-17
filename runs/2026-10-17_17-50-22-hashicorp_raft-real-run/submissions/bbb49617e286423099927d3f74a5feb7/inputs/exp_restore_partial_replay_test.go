package raft

// Construction notes:
//   * A real single-node cluster commits a first batch, takes a snapshot, then
//     commits a second batch, and is shut down. On restart the replay is the gap
//     between the snapshot index and the staged commit index, so the snapshot
//     shortens the replay instead of eliminating it.
//   * Short case: the second batch is small enough that the gap needs a handful
//     of FSM batches, which is the recovery region earlier work could only infer.
//   * Long case: the second batch pushes the gap past 128 batches at the default
//     MaxAppendEntries=64, which must block NewRaft.

import (
	"encoding/json"
	"fmt"
	"io"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

// Values taken from DefaultConfig(); recorded in every event so the boundary
// arithmetic stays inspectable.
const (
	rcMaxAppendEntries = 64
	rcBatchCapacity    = 128
)

type rcFSM struct {
	mu      sync.Mutex
	applied int
}

func (f *rcFSM) Apply(*Log) interface{} {
	f.mu.Lock()
	f.applied++
	f.mu.Unlock()
	return nil
}

func (f *rcFSM) Snapshot() (FSMSnapshot, error) { return &rcSnapshot{}, nil }

func (f *rcFSM) Restore(io.ReadCloser) error {
	f.mu.Lock()
	f.applied = 0
	f.mu.Unlock()
	return nil
}

func (f *rcFSM) count() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.applied
}

type rcSnapshot struct{}

func (s *rcSnapshot) Persist(SnapshotSink) error { return nil }
func (s *rcSnapshot) Release()                  {}

func rcEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

func rcConfig(id string) *Config {
	conf := DefaultConfig()
	conf.LocalID = ServerID(id)
	conf.Logger = hclog.NewNullLogger()
	conf.LogLevel = "ERROR"
	conf.HeartbeatTimeout = 50 * time.Millisecond
	conf.ElectionTimeout = 50 * time.Millisecond
	conf.LeaderLeaseTimeout = 50 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.RestoreCommittedLogs = true
	return conf
}

func rcBlockedProducers() int {
	buf := make([]byte, 1<<22)
	n := runtime.Stack(buf, true)
	return strings.Count(string(buf[:n]), "(*Raft).processLogs(")
}

type rcPrefix struct {
	store         *InmemCommitTrackingStore
	snaps         *InmemSnapshotStore
	stagedCommit  uint64
	lastLog       uint64
	snapshotIndex uint64
}

func rcBuildPrefix(t *testing.T, firstBatch, secondBatch int) rcPrefix {
	store := NewInmemCommitTrackingStore()
	snaps := NewInmemSnapshotStore()
	conf := rcConfig("node1")
	_, trans := NewInmemTransport("node1")
	configuration := Configuration{Servers: []Server{{Suffrage: Voter, ID: "node1", Address: trans.LocalAddr()}}}
	if err := BootstrapCluster(conf, store, store, snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	r, err := NewRaft(conf, &rcFSM{}, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("create producing raft: %v", err)
	}
	deadline := time.Now().Add(10 * time.Second)
	for r.Leader() == "" && time.Now().Before(deadline) {
		time.Sleep(2 * time.Millisecond)
	}
	if r.Leader() == "" {
		t.Fatalf("producing raft did not elect a leader")
	}
	apply := func(n int) {
		var last ApplyFuture
		for i := 0; i < n; i++ {
			last = r.Apply([]byte("x"), 5*time.Second)
		}
		if err := last.Error(); err != nil {
			t.Fatalf("apply: %v", err)
		}
	}
	apply(firstBatch)
	if err := r.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	apply(secondBatch)
	snapshotIndex := uint64(0)
	listed, err := snaps.List()
	if err != nil {
		t.Fatalf("list snapshots: %v", err)
	}
	if len(listed) > 0 {
		snapshotIndex = listed[0].Index
	}
	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}
	staged, err := store.GetCommitIndex()
	if err != nil {
		t.Fatalf("staged commit: %v", err)
	}
	lastLog, err := store.LastIndex()
	if err != nil {
		t.Fatalf("last log: %v", err)
	}
	return rcPrefix{store: store, snaps: snaps, stagedCommit: staged, lastLog: lastLog, snapshotIndex: snapshotIndex}
}

func rcRun(t *testing.T, name string, firstBatch, secondBatch int, timeout time.Duration) {
	prefix := rcBuildPrefix(t, firstBatch, secondBatch)
	replay := uint64(0)
	if prefix.stagedCommit > prefix.snapshotIndex {
		replay = prefix.stagedCommit - prefix.snapshotIndex
	}
	batches := (replay + rcMaxAppendEntries - 1) / rcMaxAppendEntries
	base := rcBlockedProducers()
	conf := rcConfig("node1")
	_, trans := NewInmemTransport("node1")
	done := make(chan error, 1)
	var raft *Raft
	start := time.Now()
	go func() {
		var err error
		raft, err = NewRaft(conf, &rcFSM{}, prefix.store, prefix.store, prefix.snaps, trans)
		done <- err
	}()
	returned := false
	errText := ""
	select {
	case err := <-done:
		returned = true
		if err != nil {
			errText = err.Error()
		} else {
			defer func() { _ = raft.Shutdown().Error() }()
		}
	case <-time.After(timeout):
		errText = "no return within observation window"
	}
	elapsed := time.Since(start)
	blocked := rcBlockedProducers() - base
	rcEmit(t, map[string]interface{}{
		"event":                  "rc_result_" + name,
		"case":                   name,
		"mode":                   "real_cluster_restart_with_mid_snapshot",
		"first_batch":            firstBatch,
		"second_batch":           secondBatch,
		"snapshot_index":         prefix.snapshotIndex,
		"staged_commit_index":    prefix.stagedCommit,
		"last_log_index":         prefix.lastLog,
		"replay_entries":         replay,
		"replay_batches":         batches,
		"max_append_entries":     rcMaxAppendEntries,
		"fsm_batch_capacity":     rcBatchCapacity,
		"returned":               returned,
		"elapsed_ms":             int(elapsed / time.Millisecond),
		"error":                  errText,
		"new_goroutines_in_process_logs": blocked,
	})
	t.Logf("case=%s snapshot=%d staged=%d replay=%d batches=%d returned=%v err=%q",
		name, prefix.snapshotIndex, prefix.stagedCommit, replay, batches, returned, errText)
}

func TestAssuranceRestorePartialReplay(t *testing.T) {
	t.Run("control_short_replay_after_snapshot", func(t *testing.T) {
		rcRun(t, "control_short_replay_after_snapshot", 200, 200, 10*time.Second)
	})
	t.Run("trigger_long_replay_after_snapshot", func(t *testing.T) {
		rcRun(t, "trigger_long_replay_after_snapshot", 200, 8300, 5*time.Second)
	})
}
