// Copyright (c) 2026. Assurance harness artifact (draft, not part of the target source).
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

func caEmit(t *testing.T, payload interface{}) {
	t.Helper()
	blob, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(blob))
}

// caSlowFSM sleeps inside Apply for a fixed interval, standing for an
// application whose state machine cannot keep up with the commit rate.
type caSlowFSM struct {
	MockFSM
	delay time.Duration
}

func (f *caSlowFSM) Apply(l *Log) interface{} {
	time.Sleep(f.delay)
	return f.MockFSM.Apply(l)
}

// TestAssurance_FSMLatencyStallsMainLoop asks whether a slow FSM stalls the
// leader's main loop, using a call that the main loop must answer as the probe.
//
// The cluster is a single voter, so no election intervenes: the leader appends
// and commits on its own, processLogs delivers each committed batch to the FSM
// by a blocking send on a 128-slot channel, and VerifyLeader for a single voter
// is answered inside the main loop, so a future that stays unresolved is direct
// evidence that the loop is blocked. The slow case sleeps in Apply; the control
// applies without sleeping and is flooded the same way.
func TestAssurance_FSMLatencyStallsMainLoop(t *testing.T) {
	caRunFSMStallTrial(t, 0, 25*time.Millisecond)
	caRunFSMStallTrial(t, 1, 0)
}

func caRunFSMStallTrial(t *testing.T, trial int, delay time.Duration) {
	t.Helper()

	conf := inmemConfig(t)
	conf.Logger = hclog.NewNullLogger()

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:      1,
		Bootstrap:  true,
		Conf:       conf,
		MakeFSMFunc: func() FSM { return &caSlowFSM{delay: delay} },
	})
	defer c.Close()

	leader := c.Leader()

	// Baseline: the main loop is idle, so the probe should be answered at once.
	baseStart := time.Now()
	baseErr := leader.VerifyLeader().Error()
	baseMs := time.Since(baseStart).Milliseconds()
	caEmit(t, map[string]interface{}{
		"event":            "fsm_stall_baseline",
		"trial":            trial,
		"apply_delay_ms":   delay.Milliseconds(),
		"probe_is_leader":  true,
		"probe_elapsed_ms": baseMs,
		"probe_error":      caErrString(baseErr),
	})

	// Flood: drive applies far faster than the FSM can apply them.
	const flood = 400
	// Fire the applies without waiting for each to be applied, which is what
	// lets the FSM fall behind: the main loop receives them one at a time and
	// dispatches them, and the FSM cannot keep up.
	done := make(chan int, 1)
	go func() {
		n := 0
		for i := 0; i < flood; i++ {
			leader.Apply([]byte(fmt.Sprintf("flood-%d", i)), 0)
			n++
		}
		done <- n
	}()

	time.Sleep(150 * time.Millisecond)
	probeStart := time.Now()
	probeErr := leader.VerifyLeader().Error()
	probeMs := time.Since(probeStart).Milliseconds()
	lag := leader.getLastIndex() - leader.getLastApplied()

	applied := <-done
	time.Sleep(200 * time.Millisecond)

	caEmit(t, map[string]interface{}{
		"event":                 "fsm_stall_probe",
		"trial":                 trial,
		"apply_delay_ms":        delay.Milliseconds(),
		"flood_target":          flood,
		"flood_applied":         applied,
		"index_lag_at_probe":    lag,
		"probe_elapsed_ms":      probeMs,
		"probe_error":           caErrString(probeErr),
		"baseline_elapsed_ms":   baseMs,
		"probe_slower_than_base": probeMs > baseMs,
	})
}

func caErrString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
