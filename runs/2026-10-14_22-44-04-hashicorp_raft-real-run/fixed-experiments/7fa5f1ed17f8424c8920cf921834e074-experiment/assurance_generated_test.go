// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

type replayProbeFSM struct{}

func (f *replayProbeFSM) Apply(l *Log) interface{}       { return nil }
func (f *replayProbeFSM) Snapshot() (FSMSnapshot, error) { return &replayProbeSnapshot{}, nil }
func (f *replayProbeFSM) Restore(rc io.ReadCloser) error {
	_, err := io.Copy(io.Discard, rc)
	_ = rc.Close()
	return err
}

type replayProbeSnapshot struct{}

func (s *replayProbeSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (s *replayProbeSnapshot) Release()                        {}

func replayProbeEmit(fields map[string]interface{}) {
	b, err := json.Marshal(fields)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceRestoreCommittedLogsReplayBackpressure asks whether NewRaft returns
// when Config.RestoreCommittedLogs has to replay more committed entries than the FSM
// mutation channel can hold in MaxAppendEntries batches before runFSM is started.
func TestAssuranceRestoreCommittedLogsReplayBackpressure(t *testing.T) {
	const snapshotIndex = uint64(1000)
	const window = 5 * time.Second

	cfgA := Configuration{Servers: []Server{{Suffrage: Voter, ID: "A", Address: "A"}}}

	cases := []struct {
		mode         string
		restore      bool
		maxAppend    int
		entriesAbove int
	}{
		{"replay_off", false, 64, 9000},
		{"replay_on", true, 64, 9000},
		{"replay_off_small_batches", false, 1, 200},
		{"replay_on_small_batches", true, 1, 200},
	}

	for _, tc := range cases {
		mode := tc.mode
		restoreCommitted := tc.restore
		entriesAboveSnapshot := uint64(tc.entriesAbove)
		lastIndex := snapshotIndex + entriesAboveSnapshot

		_, trans := NewInmemTransport("A")
		stable := NewInmemStore()
		logs := NewInmemCommitTrackingStore()
		snaps := NewInmemSnapshotStore()

		sink, err := snaps.Create(1, snapshotIndex, 1, cfgA, 1, trans)
		if err != nil {
			t.Fatalf("[%s] snapshot create: %v", mode, err)
		}
		if _, err := sink.Write([]byte("snapshot-state")); err != nil {
			t.Fatalf("[%s] snapshot write: %v", mode, err)
		}
		if err := sink.Close(); err != nil {
			t.Fatalf("[%s] snapshot close: %v", mode, err)
		}
		batch := make([]*Log, 0, 256)
		for idx := snapshotIndex + 1; idx <= lastIndex; idx++ {
			batch = append(batch, &Log{Index: idx, Term: 1, Type: LogCommand, Data: []byte("cmd")})
			if idx%256 == 0 {
				if err := logs.StoreLogs(batch); err != nil {
					t.Fatalf("[%s] store logs: %v", mode, err)
				}
				batch = batch[:0]
			}
		}
		if len(batch) > 0 {
			if err := logs.StoreLogs(batch); err != nil {
				t.Fatalf("[%s] store logs: %v", mode, err)
			}
		}
		if err := logs.StageCommitIndex(lastIndex); err != nil {
			t.Fatalf("[%s] stage commit index: %v", mode, err)
		}

		conf := DefaultConfig()
		conf.LocalID = "A"
		conf.MaxAppendEntries = tc.maxAppend
		conf.RestoreCommittedLogs = restoreCommitted
		conf.Logger = hclog.NewNullLogger()

		batches := (tc.entriesAbove + tc.maxAppend - 1) / tc.maxAppend
		fixture := map[string]interface{}{
			"event":                  "fixture",
			"mode":                   mode,
			"local_id":               "A",
			"snapshot_index":         snapshotIndex,
			"log_last_index":         lastIndex,
			"stored_commit_index":    lastIndex,
			"max_append_entries":     conf.MaxAppendEntries,
			"entries_above_snapshot": entriesAboveSnapshot,
			"batches_required":       batches,
			"observation_window_ms":  window.Milliseconds(),
		}
		replayProbeEmit(fixture)

		expected := map[string]interface{}{
			"event":    "construct",
			"mode":     mode,
			"local_id": "A",
		}

		done := make(chan *Raft, 1)
		errCh := make(chan error, 1)
		go func() {
			r, err := NewRaft(conf, &replayProbeFSM{}, logs, stable, snaps, trans)
			if err != nil {
				errCh <- err
				return
			}
			done <- r
		}()

		select {
		case r := <-done:
			expected["newraft_returned"] = true
			expected["last_applied"] = r.getLastApplied()
			expected["queued_fsm_batches"] = len(r.fsmMutateCh)
			expected["fsm_mutate_capacity"] = cap(r.fsmMutateCh)
			replayProbeEmit(expected)
			if sf := r.Shutdown(); sf != nil {
				_ = sf.Error()
			}
		case err := <-errCh:
			expected["newraft_returned"] = true
			expected["error"] = err.Error()
			replayProbeEmit(expected)
		case <-time.After(window):
			expected["newraft_returned"] = false
			replayProbeEmit(expected)
		}
	}
}
