// Copyright (c) 2026. Assurance harness artifact (draft, not part of the target source).
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"runtime"
	"strings"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

// caRestartWait bounds how long the harness waits for a restarted node's
// NewRaft call to return before recording it as non-returning.
const caRestartWait = 5 * time.Second

type caReplayCase struct {
	name               string
	applied            int
	snapshotBeforeStop bool
	maxAppendEntries   int // 0 keeps the captured default
}

type caReplayResult struct {
	Case               string   `json:"case"`
	Applied            int      `json:"applied"`
	MaxAppendEntries   int      `json:"max_append_entries"`
	FSMBufferCapacity  int      `json:"fsm_mutate_ch_capacity"`
	PersistedCommitIdx uint64   `json:"persisted_commit_index"`
	LastLogIndex       uint64   `json:"last_log_index"`
	SnapshotPresent    bool     `json:"snapshot_present"`
	SnapshotIndex      uint64   `json:"snapshot_index"`
	LastAppliedAtStart uint64   `json:"last_applied_before_restart"`
	ReplayWindow       uint64   `json:"replay_window"`
	FSMBoundInWindow   uint64   `json:"fsm_bound_entries_in_window"`
	EstimatedBatches   uint64   `json:"estimated_replay_batches"`
	RestartReturned    bool     `json:"restart_returned"`
	RestartElapsedMs   int64    `json:"restart_elapsed_ms"`
	RestartError       string   `json:"restart_error"`
	RestartFrames      []string `json:"restart_stack_frames"`
}

func caEmit(t *testing.T, res caReplayResult) {
	t.Helper()
	blob, err := json.Marshal(res)
	if err != nil {
		t.Fatalf("marshal result: %v", err)
	}
	fmt.Println("CA_EVENT " + string(blob))
}

// TestAssurance_RestoreCommittedLogs_StartupReplay observes whether NewRaft
// returns when RestoreCommittedLogs replays a startup window of
// (last snapshot index, persisted commit index] committed entries.
//
// Each case runs the real single-voter Raft node (in-memory transport, real
// commit-tracking log store) to produce the persisted commit index and log
// contents, shuts it down, and then calls NewRaft again over the same stores.
// The cases differ only in how many entries are committed before the restart
// and whether a snapshot is taken before shutdown, i.e. in the size of the
// startup replay window.
func TestAssurance_RestoreCommittedLogs_StartupReplay(t *testing.T) {
	cases := []caReplayCase{
		{name: "small_window_default_batch", applied: 4000},
		{name: "mid_window_default_batch", applied: 1000},
		{name: "mid_window_small_batch", applied: 1000, maxAppendEntries: 4},
		{name: "large_window_default_batch", applied: 12000},
		{name: "large_window_after_snapshot", applied: 12000, snapshotBeforeStop: true},
	}
	for _, tc := range cases {
		res := caRunReplayCase(t, tc)
		caEmit(t, res)
	}
}

func caRunReplayCase(t *testing.T, tc caReplayCase) caReplayResult {
	t.Helper()

	res := caReplayResult{Case: tc.name, Applied: tc.applied}

	// Automatic snapshotting is disabled so that the startup replay window is
	// determined only by the explicit applies and the optional manual
	// snapshot. This is a legal configuration and models a node whose newest
	// snapshot lags its commit index (which also happens with default settings
	// when more than SnapshotThreshold entries are committed between the
	// periodic snapshot checks).
	conf := inmemConfig(t)
	conf.Logger = hclog.NewNullLogger()
	conf.RestoreCommittedLogs = true
	conf.SnapshotThreshold = math.MaxUint64
	conf.SnapshotInterval = time.Hour
	if tc.maxAppendEntries > 0 {
		conf.MaxAppendEntries = tc.maxAppendEntries
	}

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})

	leader := c.Leader()

	var last Future
	for i := 0; i < tc.applied; i++ {
		last = leader.Apply([]byte(fmt.Sprintf("test%d", i)), 0)
	}
	if err := last.Error(); err != nil {
		t.Fatalf("apply %d: %v", tc.applied, err)
	}

	logs := leader.logs
	stable := leader.stable
	snaps := leader.snapshots
	fsm := leader.fsm
	addr := leader.trans.LocalAddr()

	store, ok := logs.(CommitTrackingLogStore)
	if !ok {
		t.Fatalf("log store %T does not implement CommitTrackingLogStore", logs)
	}
	commitIdx, err := store.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex: %v", err)
	}
	lastLogIdx, err := logs.LastIndex()
	if err != nil {
		t.Fatalf("LastIndex: %v", err)
	}
	res.PersistedCommitIdx = commitIdx
	res.LastLogIndex = lastLogIdx
	res.MaxAppendEntries = leader.config().MaxAppendEntries
	res.FSMBufferCapacity = cap(leader.fsmMutateCh)

	var lastAppliedAtStart uint64
	if tc.snapshotBeforeStop {
		if err := leader.Snapshot().Error(); err != nil {
			t.Fatalf("snapshot: %v", err)
		}
		snapsList, err := snaps.List()
		if err != nil || len(snapsList) == 0 {
			t.Fatalf("snapshot list: %v (%d)", err, len(snapsList))
		}
		res.SnapshotPresent = true
		res.SnapshotIndex = snapsList[0].Index
		lastAppliedAtStart = snapsList[0].Index
	}
	res.LastAppliedAtStart = lastAppliedAtStart
	if commitIdx > lastAppliedAtStart {
		res.ReplayWindow = commitIdx - lastAppliedAtStart
	}

	// Census the entry types inside the startup replay window using the same
	// rule as Raft.prepareLog, so the batch arithmetic below rests on observed
	// log contents rather than on an assumed layout.
	fsmBound, err := caCountFSMBound(logs, lastAppliedAtStart+1, commitIdx, leader.protocolVersion)
	if err != nil {
		t.Fatalf("census replay window: %v", err)
	}
	res.FSMBoundInWindow = fsmBound
	if res.MaxAppendEntries > 0 {
		res.EstimatedBatches = (fsmBound + uint64(res.MaxAppendEntries) - 1) / uint64(res.MaxAppendEntries)
	}

	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}

	// Restart the node over the same durable stores, exactly as the target's
	// own restart tests do, with a fresh transport on the same address.
	cfg := *conf
	cfg.Logger = hclog.NewNullLogger()

	doneCh := make(chan error, 1)
	go func() {
		defer func() {
			if r := recover(); r != nil {
				doneCh <- fmt.Errorf("panic: %v", r)
			}
		}()
		_, trans2 := NewInmemTransport(addr)
		_, err := NewRaft(&cfg, fsm, logs, stable, snaps, trans2)
		doneCh <- err
	}()

	start := time.Now()
	select {
	case rerr := <-doneCh:
		res.RestartReturned = true
		if rerr != nil {
			res.RestartError = rerr.Error()
		}
	case <-time.After(caRestartWait):
		res.RestartFrames = caBlockedReplayFrames()
	}
	res.RestartElapsedMs = time.Since(start).Milliseconds()

	for _, d := range c.dirs {
		_ = os.RemoveAll(d)
	}
	return res
}

// caCountFSMBound counts the entries in [1, upTo] that Raft.prepareLog turns
// into an entry delivered to the FSM (LogCommand, LogBarrier and, above
// protocol version 2, LogConfiguration). No-ops and the deprecated peer entry
// types are not delivered.
func caCountFSMBound(logs LogStore, from, upTo uint64, protocol ProtocolVersion) (uint64, error) {
	var bound uint64
	if from == 0 {
		from = 1
	}
	for idx := from; idx <= upTo; idx++ {
		var l Log
		if err := logs.GetLog(idx, &l); err != nil {
			return bound, fmt.Errorf("GetLog(%d): %w", idx, err)
		}
		switch l.Type {
		case LogCommand, LogBarrier:
			bound++
		case LogConfiguration:
			if protocol > 2 {
				bound++
			}
		}
	}
	return bound, nil
}

// caBlockedReplayFrames samples the goroutine dump and returns the stack of the
// goroutine that has not returned out of the startup replay path, so the
// blocking mechanism is inspectable rather than inferred. A send blocked
// inside a select is reported by the runtime with a [select] state header, so
// the block is identified by its frames rather than by its state name.
func caBlockedReplayFrames() []string {
	buf := make([]byte, 1<<20)
	n := runtime.Stack(buf, true)
	lines := strings.Split(string(buf[:n]), "\n")

	var frames []string
	for i := 0; i < len(lines); i++ {
		if !strings.HasPrefix(lines[i], "goroutine ") {
			continue
		}
		var block []string
		for j := i; j < len(lines) && strings.TrimSpace(lines[j]) != ""; j++ {
			block = append(block, strings.TrimSpace(lines[j]))
		}
		joined := strings.Join(block, "\n")
		if strings.Contains(joined, "processLogs") && strings.Contains(joined, "restoreFromCommittedLogs") {
			for _, f := range block {
				if strings.HasPrefix(f, "goroutine ") || strings.Contains(f, ".go:") {
					frames = append(frames, f)
					if len(frames) >= 10 {
						break
					}
				}
			}
			break
		}
	}
	return frames
}
