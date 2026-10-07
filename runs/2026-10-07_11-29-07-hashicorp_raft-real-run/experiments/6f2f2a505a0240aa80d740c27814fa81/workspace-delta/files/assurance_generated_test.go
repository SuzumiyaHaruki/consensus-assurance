// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated assurance harness. Nodes are shut down, then client requests are
// issued against the inactive instances and their completion is observed. The
// harness reports raw counts only; the plan states the predicate.

package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

func assuranceEmitEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

type assuranceInactiveFSM struct{}

func (assuranceInactiveFSM) Apply(*Log) interface{}         { return nil }
func (assuranceInactiveFSM) Snapshot() (FSMSnapshot, error) { return assuranceInactiveSnapshot{}, nil }
func (assuranceInactiveFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceInactiveSnapshot struct{}

func (assuranceInactiveSnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceInactiveSnapshot) Release()                     {}

// assuranceInactiveNode starts one node and completes Shutdown on it.
// Shutdown().Error() returns only after the raft goroutine group (run, runFSM
// and runSnapshots) has exited, so no handler remains for later requests.
func assuranceInactiveNode(t *testing.T, id ServerID, batchApply bool) *Raft {
	conf := DefaultConfig()
	conf.LocalID = id
	conf.LogLevel = "ERROR"
	conf.BatchApplyCh = batchApply
	_, trans := NewInmemTransport(ServerAddress(id))
	r, err := NewRaft(conf, assuranceInactiveFSM{}, NewInmemStore(), NewInmemStore(), NewInmemSnapshotStore(), trans)
	if err != nil {
		t.Fatalf("assurance: NewRaft %s: %v", id, err)
	}
	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("assurance: shutdown %s: %v", id, err)
	}
	return r
}

// assuranceUnresolvedVerify counts futures whose own completion channel is
// still empty. Error() is not called because it would block; the channel is
// written only by raft handlers, which have already exited.
func assuranceUnresolvedVerify(pending []*verifyFuture) int {
	unresolved := 0
	for _, f := range pending {
		select {
		case <-f.errCh:
		default:
			unresolved++
		}
	}
	return unresolved
}

func assuranceUnresolvedApply(pending []*logFuture) int {
	unresolved := 0
	for _, f := range pending {
		select {
		case <-f.errCh:
		default:
			unresolved++
		}
	}
	return unresolved
}

// assuranceErrorWithin bounds a single future wait so the diagnostic control
// cannot hang the harness if the API unexpectedly blocks instead of failing.
func assuranceErrorWithin(f Future, d time.Duration) (error, bool) {
	ch := make(chan error, 1)
	go func() { ch <- f.Error() }()
	select {
	case err := <-ch:
		return err, true
	case <-time.After(d):
		return nil, false
	}
}

func TestAssuranceInactiveRequestCompletion(t *testing.T) {
	const (
		op      = "after-shutdown"
		setup   = "default-verify-with-batched-apply"
		calls   = 128
		control = 8
		wait    = 250 * time.Millisecond
	)

	// n1: default configuration, so verifyCh is buffered with 64 slots and
	// applyCh is unbuffered.
	verifyNode := assuranceInactiveNode(t, "n1", false)
	// n2: the documented BatchApplyCh option buffers applyCh.
	applyNode := assuranceInactiveNode(t, "n2", true)
	// n3: default configuration control, whose unbuffered applyCh is the same
	// select structure with a channel that can never have a ready receiver.
	controlNode := assuranceInactiveNode(t, "n3", false)

	var verifyPending []*verifyFuture
	verifyCompleted, verifyOther := 0, 0
	for i := 0; i < calls; i++ {
		switch f := verifyNode.VerifyLeader().(type) {
		case errorFuture:
			if f.err == ErrRaftShutdown {
				verifyCompleted++
			} else {
				verifyOther++
			}
		case *verifyFuture:
			verifyPending = append(verifyPending, f)
		}
	}

	var applyPending []*logFuture
	applyCompleted, applyOther := 0, 0
	for i := 0; i < calls; i++ {
		switch f := applyNode.Apply([]byte("x"), 0).(type) {
		case errorFuture:
			if f.err == ErrRaftShutdown {
				applyCompleted++
			} else {
				applyOther++
			}
		case *logFuture:
			applyPending = append(applyPending, f)
		}
	}

	controlCompleted, controlUnresolved := 0, 0
	for i := 0; i < control; i++ {
		if err, done := assuranceErrorWithin(controlNode.Barrier(0), wait); done && err == ErrRaftShutdown {
			controlCompleted++
		} else {
			controlUnresolved++
		}
	}

	time.Sleep(wait)
	unresolvedVerify := assuranceUnresolvedVerify(verifyPending)
	unresolvedApply := assuranceUnresolvedApply(applyPending)

	assuranceEmitEvent(map[string]interface{}{
		"event":             "nodes_inactive",
		"setup":             setup,
		"op":                op,
		"verify_node_state": verifyNode.State().String(),
		"apply_node_state":  applyNode.State().String(),
		"control_node_state": controlNode.State().String(),
		"verify_calls":      calls,
		"apply_calls":       calls,
		"control_calls":     control,
	})
	assuranceEmitEvent(map[string]interface{}{
		"event":                         "inactive_requests_observed",
		"setup":                         setup,
		"op":                            op,
		"calls_total":                   calls + calls,
		"completed_shutdown_total":      verifyCompleted + applyCompleted,
		"completed_other_total":         verifyOther + applyOther,
		"unresolved_verify":             unresolvedVerify,
		"unresolved_apply":              unresolvedApply,
		"unresolved_total":              unresolvedVerify + unresolvedApply,
		"control_barrier_calls":         control,
		"control_barrier_completed":     controlCompleted,
		"control_barrier_unresolved":    controlUnresolved,
		"wait_millis":                   wait.Milliseconds(),
	})
}
