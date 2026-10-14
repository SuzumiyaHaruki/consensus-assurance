// Copyright (c) 2026. Assurance harness artifact (draft, not part of the target source).
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
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
	name          string
	applied       int
	snapshotAfter int // 0 = no snapshot is taken before shutdown
}

// caReplayPrefix is the admission event: the state established before the
// restart, fully observed before any restart outcome exists.
type caReplayPrefix struct {
	Event              string `json:"event"`
	Case               string `json:"case"`
	Applied            int    `json:"applied"`
	SnapshotAfter      int    `json:"snapshot_after"`
	MaxAppendEntries   int    `json:"max_append_entries"`
	SnapshotThreshold  uint64 `json:"snapshot_threshold"`
	SnapshotIntervalMs int64  `json:"snapshot_interval_ms"`
	FSMBufferCapacity  int    `json:"fsm_mutate_ch_capacity"`
	PersistedCommitIdx uint64 `json:"persisted_commit_index"`
	LastLogIndex       uint64 `json:"last_log_index"`
	SnapshotPresent    bool   `json:"snapshot_present"`
	SnapshotIndex      uint64 `json:"snapshot_index"`
	LastAppliedAtStart uint64 `json:"last_applied_before_restart"`
	ReplayWindow       uint64 `json:"replay_window"`
	FSMBoundInWindow   uint64 `json:"fsm_bound_entries_in_window"`
	EstimatedBatches   uint64 `json:"estimated_replay_batches"`
}

// caReplayRestart is the result event: the outcome of the admitted restart,
// carrying the same operands that decide replay_batches_within_capacity so the
// classification is inspectable next to the outcome it is used to select.
type caReplayRestart struct {
	Event                  string   `json:"event"`
	Case                   string   `json:"case"`
	Applied                int      `json:"applied"`
	MaxAppendEntries       int      `json:"max_append_entries"`
	FSMBufferCapacity      int      `json:"fsm_mutate_ch_capacity"`
	ReplayWindow           uint64   `json:"replay_window"`
	FSMBoundInWindow       uint64   `json:"fsm_bound_entries_in_window"`
	EstimatedBatches       uint64   `json:"estimated_replay_batches"`
	ReplayBatchesWithinCap bool     `json:"replay_batches_within_capacity"`
	RestartReturned        bool     `json:"restart_returned"`
	RestartElapsedMs       int64    `json:"restart_elapsed_ms"`
	RestartError           string   `json:"restart_error"`
	RestartFrames          []string `json:"restart_stack_frames"`
}

func caEmit(t *testing.T, payload interface{}) {
	t.Helper()
	blob, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(blob))
}

// TestAssurance_RestoreCommittedLogs_DefaultSnapshotSettings asks whether a
// node whose snapshot settings are left at the captured defaults can restart
// into a startup replay window larger than the 128-batch capacity of
// fsmMutateCh, or whether the periodic snapshot keeps the window below it.
//
// SnapshotThreshold, SnapshotInterval and MaxAppendEntries are left untouched
// at their configured values here, and their values are reported in the
// admission event. The newest snapshot is placed by a real user snapshot at a
// chosen point so the accumulation after it is deterministic; the same window
// also arises without any snapshot when the node has not yet reached its first
// periodic check, which the case without a snapshot exercises.
func TestAssurance_RestoreCommittedLogs_DefaultSnapshotSettings(t *testing.T) {
	cases := []caReplayCase{
		{name: "defaults_no_snapshot_window_10000", applied: 10000},
		{name: "defaults_snapshot_then_10000_more", applied: 14000, snapshotAfter: 4000},
		{name: "defaults_snapshot_then_2000_more", applied: 6000, snapshotAfter: 4000},
	}
	for _, tc := range cases {
		caRunReplayCase(t, tc)
	}
}

func caRunReplayCase(t *testing.T, tc caReplayCase) {
	t.Helper()

	conf := inmemConfig(t)
	conf.Logger = hclog.NewNullLogger()
	conf.RestoreCommittedLogs = true
	// SnapshotThreshold, SnapshotInterval and MaxAppendEntries keep their
	// captured values: this probe is about the configured snapshot cadence.

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})

	leader := c.Leader()

	applyN := func(n int) {
		t.Helper()
		var last Future
		for i := 0; i < n; i++ {
			last = leader.Apply([]byte(fmt.Sprintf("test%d", i)), 0)
		}
		if err := last.Error(); err != nil {
			t.Fatalf("%s: apply %d: %v", tc.name, n, err)
		}
	}

	if tc.snapshotAfter > 0 {
		applyN(tc.snapshotAfter)
		if err := leader.Snapshot().Error(); err != nil {
			t.Fatalf("%s: snapshot: %v", tc.name, err)
		}
		applyN(tc.applied - tc.snapshotAfter)
	} else {
		applyN(tc.applied)
	}

	logs := leader.logs
	stable := leader.stable
	snaps := leader.snapshots
	fsm := leader.fsm
	addr := leader.trans.LocalAddr()
	cfgNow := leader.config()

	store, ok := logs.(CommitTrackingLogStore)
	if !ok {
		t.Fatalf("%s: log store %T does not implement CommitTrackingLogStore", tc.name, logs)
	}
	commitIdx, err := store.GetCommitIndex()
	if err != nil {
		t.Fatalf("%s: GetCommitIndex: %v", tc.name, err)
	}
	lastLogIdx, err := logs.LastIndex()
	if err != nil {
		t.Fatalf("%s: LastIndex: %v", tc.name, err)
	}

	prefix := caReplayPrefix{
		Event:              "startup_replay_prefix",
		Case:               tc.name,
		Applied:            tc.applied,
		SnapshotAfter:      tc.snapshotAfter,
		MaxAppendEntries:   cfgNow.MaxAppendEntries,
		SnapshotThreshold:  cfgNow.SnapshotThreshold,
		SnapshotIntervalMs: cfgNow.SnapshotInterval.Milliseconds(),
		FSMBufferCapacity:  cap(leader.fsmMutateCh),
		PersistedCommitIdx: commitIdx,
		LastLogIndex:       lastLogIdx,
	}

	var lastAppliedAtStart uint64
	if snapsList, err := snaps.List(); err != nil {
		t.Fatalf("%s: snapshot list: %v", tc.name, err)
	} else if len(snapsList) > 0 {
		// The newest snapshot in the store is what a restart restores.
		prefix.SnapshotPresent = true
		prefix.SnapshotIndex = snapsList[0].Index
		lastAppliedAtStart = snapsList[0].Index
	}
	prefix.LastAppliedAtStart = lastAppliedAtStart
	if commitIdx > lastAppliedAtStart {
		prefix.ReplayWindow = commitIdx - lastAppliedAtStart
	}

	// Census the entry types inside the startup replay window using the same
	// rule as Raft.prepareLog, so the batch arithmetic below rests on observed
	// log contents rather than on an assumed layout.
	fsmBound, err := caCountFSMBound(logs, lastAppliedAtStart+1, commitIdx, leader.protocolVersion)
	if err != nil {
		t.Fatalf("%s: census replay window: %v", tc.name, err)
	}
	prefix.FSMBoundInWindow = fsmBound
	if prefix.MaxAppendEntries > 0 {
		prefix.EstimatedBatches = (fsmBound + uint64(prefix.MaxAppendEntries) - 1) / uint64(prefix.MaxAppendEntries)
	}

	caEmit(t, prefix)

	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("%s: shutdown: %v", tc.name, err)
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

	result := caReplayRestart{
		Event:                  "startup_replay_restart",
		Case:                   tc.name,
		Applied:                tc.applied,
		MaxAppendEntries:       prefix.MaxAppendEntries,
		FSMBufferCapacity:      prefix.FSMBufferCapacity,
		ReplayWindow:           prefix.ReplayWindow,
		FSMBoundInWindow:       prefix.FSMBoundInWindow,
		EstimatedBatches:       prefix.EstimatedBatches,
		ReplayBatchesWithinCap: prefix.EstimatedBatches <= uint64(prefix.FSMBufferCapacity),
	}

	start := time.Now()
	select {
	case rerr := <-doneCh:
		result.RestartReturned = true
		if rerr != nil {
			result.RestartError = rerr.Error()
		}
	case <-time.After(caRestartWait):
		result.RestartFrames = caBlockedReplayFrames()
	}
	result.RestartElapsedMs = time.Since(start).Milliseconds()

	caEmit(t, result)

	for _, d := range c.dirs {
		_ = os.RemoveAll(d)
	}
}

// caCountFSMBound counts the entries in [from, upTo] that Raft.prepareLog turns
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
