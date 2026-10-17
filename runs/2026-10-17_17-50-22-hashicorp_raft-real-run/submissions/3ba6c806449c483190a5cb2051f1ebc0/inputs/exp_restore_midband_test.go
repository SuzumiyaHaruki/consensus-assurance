package raft

// Construction notes:
//   * Each case runs a real single-node cluster that commits a first batch,
//     takes a snapshot, then commits a second batch, and shuts down, so the
//     restart replays only the tail after the snapshot.
//   * Three tails are measured at the default MaxAppendEntries of 64: about
//     fifty FSM batches, which is inside the range that earlier receipts only
//     covered with a seeded store state; exactly one hundred and twenty eight
//     batches, the channel capacity itself, measured on a large real tail so a
//     slow replay cannot be mistaken for a capacity effect; and one entry past
//     that, which the seeded boundary says must not return.

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

type mbFSM struct {
	mu      sync.Mutex
	applied int
}

func (f *mbFSM) Apply(*Log) interface{} {
	f.mu.Lock()
	f.applied++
	f.mu.Unlock()
	return nil
}

func (f *mbFSM) Snapshot() (FSMSnapshot, error) { return &mbSnapshot{}, nil }

func (f *mbFSM) Restore(io.ReadCloser) error {
	f.mu.Lock()
	f.applied = 0
	f.mu.Unlock()
	return nil
}

type mbSnapshot struct{}

func (s *mbSnapshot) Persist(SnapshotSink) error { return nil }
func (s *mbSnapshot) Release()                   {}

func mbEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

func mbConfig(id string) *Config {
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

func mbBlocked() int {
	buf := make([]byte, 1<<22)
	n := runtime.Stack(buf, true)
	return strings.Count(string(buf[:n]), "(*Raft).processLogs(")
}

func TestAssuranceRestoreMidbandReplay(t *testing.T) {
	cases := []struct {
		name        string
		secondBatch int
		event       string
	}{
		{name: "midband_replay", secondBatch: 3200, event: "mb_case_midband_replay"},
		{name: "capacity_replay", secondBatch: 8194, event: "mb_case_capacity_replay"},
		{name: "over_capacity_replay", secondBatch: 8195, event: "mb_case_over_capacity_replay"},
	}
	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			mbRunCase(t, tc.name, tc.event, tc.secondBatch)
		})
	}
}

func mbRunCase(t *testing.T, name string, caseEvent string, secondBatch int) {
	t.Helper()
	const firstBatch = 200
	const window = 20 * time.Second

	store := NewInmemCommitTrackingStore()
	snaps := NewInmemSnapshotStore()
	conf := mbConfig("node1")
	_, trans := NewInmemTransport("node1")
	configuration := Configuration{Servers: []Server{{Suffrage: Voter, ID: "node1", Address: trans.LocalAddr()}}}
	if err := BootstrapCluster(conf, store, store, snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	r, err := NewRaft(conf, &mbFSM{}, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("producing raft: %v", err)
	}
	deadline := time.Now().Add(10 * time.Second)
	for r.Leader() == "" && time.Now().Before(deadline) {
		time.Sleep(2 * time.Millisecond)
	}
	if r.Leader() == "" {
		t.Fatalf("no leader")
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
	replay := uint64(0)
	if staged > snapshotIndex {
		replay = staged - snapshotIndex
	}
	batches := (replay + 63) / 64

	mbEmit(t, map[string]interface{}{
		"event":                  caseEvent,
		"case":                   name,
		"mode":                   "real_cluster_restart_with_snapshot_bound_tail",
		"restore_committed_logs": true,
		"first_batch":            firstBatch,
		"second_batch":           secondBatch,
		"snapshot_index":         snapshotIndex,
		"staged_commit_index":    staged,
		"last_log_index":         lastLog,
		"replay_entries":         replay,
		"replay_batches":         batches,
		"max_append_entries":     64,
		"window_ms":              int(window / time.Millisecond),
	})

	base := mbBlocked()
	start := time.Now()
	done := make(chan error, 1)
	var restarted *Raft
	go func() {
		var rerr error
		restarted, rerr = NewRaft(mbConfig("node1"), &mbFSM{}, store, store, snaps, trans)
		done <- rerr
	}()
	returned := false
	errText := ""
	select {
	case err := <-done:
		returned = true
		if err != nil {
			errText = err.Error()
		} else {
			defer func() { _ = restarted.Shutdown().Error() }()
		}
	case <-time.After(window):
		errText = "no return within observation window"
	}
	mbEmit(t, map[string]interface{}{
		"event":               strings.Replace(caseEvent, "mb_case_", "mb_result_", 1),
		"case":                name,
		"returned":            returned,
		"elapsed_ms":          int(time.Since(start) / time.Millisecond),
		"error":               errText,
		"new_blocked_process": mbBlocked() - base,
	})
	t.Logf("case=%s replay=%d batches=%d returned=%v err=%q", name, replay, batches, returned, errText)
}
