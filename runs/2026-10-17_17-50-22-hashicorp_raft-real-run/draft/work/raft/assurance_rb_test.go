package raft

// Construction notes:
//   * The startup replay pushes one commitTuple per MaxAppendEntries entries into
//     r.fsmMutateCh, whose capacity is fixed at 128 in the captured code, and the
//     only consumer is started after NewRaft returns.
//   * Earlier work measured the boundary at MaxAppendEntries=64 (8192 entries)
//     and MaxAppendEntries=1024 (131072 entries). This harness moves the batch
//     size to its smallest legal value, 1, so the predicted boundary is 128
//     entries rather than 8192.
//   * Cases: exactly 128 replayed entries, which is 128 batches and should
//     return, and 129 entries, which is 129 batches and should not.

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

const rbBatchCapacity = 128

type rbFSM struct {
	mu      sync.Mutex
	applied int
}

func (f *rbFSM) Apply(*Log) interface{} {
	f.mu.Lock()
	f.applied++
	f.mu.Unlock()
	return nil
}

func (f *rbFSM) Snapshot() (FSMSnapshot, error) { return &rbSnapshot{}, nil }

func (f *rbFSM) Restore(io.ReadCloser) error {
	f.mu.Lock()
	f.applied = 0
	f.mu.Unlock()
	return nil
}

func (f *rbFSM) count() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.applied
}

type rbSnapshot struct{}

func (s *rbSnapshot) Persist(SnapshotSink) error { return nil }
func (s *rbSnapshot) Release()                  {}

func rbEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

func rbConfig(id string) *Config {
	conf := DefaultConfig()
	conf.LocalID = ServerID(id)
	conf.Logger = hclog.NewNullLogger()
	conf.LogLevel = "ERROR"
	conf.HeartbeatTimeout = 50 * time.Millisecond
	conf.ElectionTimeout = 50 * time.Millisecond
	conf.LeaderLeaseTimeout = 50 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.RestoreCommittedLogs = true
	conf.MaxAppendEntries = 1
	return conf
}

func rbBlockedProducers() int {
	buf := make([]byte, 1<<22)
	n := runtime.Stack(buf, true)
	return strings.Count(string(buf[:n]), "(*Raft).processLogs(")
}

type rbResult struct {
	returned    bool
	elapsed     time.Duration
	err         string
	applied     int
	blockedDiff int
}

func rbStart(conf *Config, fsm *rbFSM, store *InmemCommitTrackingStore,
	snaps SnapshotStore, addr ServerAddress, timeout time.Duration) rbResult {
	base := rbBlockedProducers()
	_, trans := NewInmemTransport(addr)
	done := make(chan error, 1)
	var raft *Raft
	start := time.Now()
	go func() {
		var err error
		raft, err = NewRaft(conf, fsm, store, store, snaps, trans)
		done <- err
	}()
	var res rbResult
	select {
	case err := <-done:
		res.returned = true
		res.elapsed = time.Since(start)
		if err != nil {
			res.err = err.Error()
		} else {
			defer func() { _ = raft.Shutdown().Error() }()
		}
	case <-time.After(timeout):
		res.elapsed = time.Since(start)
		res.err = "no return within observation window"
	}
	res.applied = fsm.count()
	res.blockedDiff = rbBlockedProducers() - base
	return res
}

func rbRun(t *testing.T, name string, entries uint64, timeout time.Duration) {
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
	lastLog, err := store.LastIndex()
	if err != nil {
		t.Fatalf("last index: %v", err)
	}
	rbEmit(t, map[string]interface{}{
		"event":                  "rb_case_" + name,
		"case":                   name,
		"mode":                   "seeded_commit_tracking_store",
		"restore_committed_logs": true,
		"max_append_entries":     1,
		"fsm_batch_capacity":     rbBatchCapacity,
		"entries":                entries,
		"staged_commit_index":    entries,
		"last_log_index":         lastLog,
		"replay_entries":         entries,
		"replay_batches":         entries,
		"timeout_ms":             int(timeout / time.Millisecond),
	})
	res := rbStart(rbConfig("node1"), &rbFSM{}, store, NewInmemSnapshotStore(), "node1", timeout)
	rbEmit(t, map[string]interface{}{
		"event":                          "rb_result_" + name,
		"case":                           name,
		"returned":                       res.returned,
		"elapsed_ms":                     int(res.elapsed / time.Millisecond),
		"error":                          res.err,
		"fsm_applied_sampled":            res.applied,
		"new_goroutines_in_process_logs": res.blockedDiff,
	})
	t.Logf("case=%s entries=%d returned=%v elapsed=%v err=%q", name, entries, res.returned, res.elapsed, res.err)
}

func TestAssuranceRestoreBatchOne(t *testing.T) {
	t.Run("control_128_batches_at_1", func(t *testing.T) {
		rbRun(t, "control_128_batches_at_1", 128, 10*time.Second)
	})
	t.Run("trigger_129_batches_at_1", func(t *testing.T) {
		rbRun(t, "trigger_129_batches_at_1", 129, 5*time.Second)
	})
}
