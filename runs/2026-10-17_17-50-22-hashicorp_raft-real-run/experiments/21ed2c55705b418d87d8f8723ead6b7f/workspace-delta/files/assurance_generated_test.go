package raft

// Construction notes:
//   * Earlier startup receipts observed the hanging replay for 5000 ms. This
//     harness keeps the default batch size and the exact boundary state, and
//     watches the 129-batch case for thirty seconds instead.
//   * The control replays 8192 entries (128 batches) with a ten-second window and
//     is expected to return in milliseconds, which shows that a thirty-second
//     wait is far longer than a completed replay of this size needs.

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

type ppFSM struct {
	mu      sync.Mutex
	applied int
}

func (f *ppFSM) Apply(*Log) interface{} {
	f.mu.Lock()
	f.applied++
	f.mu.Unlock()
	return nil
}

func (f *ppFSM) Snapshot() (FSMSnapshot, error) { return &ppSnapshot{}, nil }

func (f *ppFSM) Restore(io.ReadCloser) error {
	f.mu.Lock()
	f.applied = 0
	f.mu.Unlock()
	return nil
}

type ppSnapshot struct{}

func (s *ppSnapshot) Persist(SnapshotSink) error { return nil }
func (s *ppSnapshot) Release()                  {}

func ppEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

func ppConfig(id string) *Config {
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

func ppBlocked() int {
	buf := make([]byte, 1<<22)
	n := runtime.Stack(buf, true)
	return strings.Count(string(buf[:n]), "(*Raft).processLogs(")
}

func ppRun(t *testing.T, name string, entries uint64, window time.Duration) {
	store := NewInmemCommitTrackingStore()
	logs := make([]*Log, 0, entries)
	for i := uint64(1); i <= entries; i++ {
		logs = append(logs, &Log{Index: i, Term: 1, Type: LogCommand, Data: []byte("x")})
	}
	if err := store.StoreLogs(logs); err != nil {
		t.Fatalf("seed logs: %v", err)
	}
	if err := store.StageCommitIndex(entries); err != nil {
		t.Fatalf("stage commit index: %v", err)
	}
	_, trans := NewInmemTransport("P")
	fsm := &ppFSM{}
	base := ppBlocked()
	ppEmit(t, map[string]interface{}{
		"event":              "pp_case_" + name,
		"case":               name,
		"entries":            entries,
		"replay_batches":     (entries + 63) / 64,
		"max_append_entries": 64,
		"window_ms":          int(window / time.Millisecond),
		"restore_committed_logs": true,
	})
	done := make(chan error, 1)
	var raft *Raft
	start := time.Now()
	go func() {
		var err error
		raft, err = NewRaft(ppConfig("P"), fsm, store, store, NewInmemSnapshotStore(), trans)
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
	case <-time.After(window):
		errText = "no return within observation window"
	}
	ppEmit(t, map[string]interface{}{
		"event":               "pp_result_" + name,
		"case":                name,
		"returned":            returned,
		"elapsed_ms":          int(time.Since(start) / time.Millisecond),
		"error":               errText,
		"new_blocked_process": ppBlocked() - base,
	})
	t.Logf("case=%s entries=%d window=%v returned=%v", name, entries, window, returned)
}

func TestAssuranceStartupPermanence(t *testing.T) {
	t.Run("control_128_batches", func(t *testing.T) {
		ppRun(t, "control_128_batches", 8192, 10*time.Second)
	})
	t.Run("trigger_129_batches_30s", func(t *testing.T) {
		ppRun(t, "trigger_129_batches_30s", 8193, 30*time.Second)
	})
}
