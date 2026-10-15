// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"sync"
	"testing"
	"time"
)

func assuranceEmit(t *testing.T, event map[string]interface{}) {
	b, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	t.Log("CA_EVENT " + string(b))
}

func assuranceSingleNode(t *testing.T, tag string, batched bool) (*Raft, func()) {
	addr, trans := NewInmemTransport("")
	id := ServerID("server-" + string(addr))
	conf := DefaultConfig()
	conf.HeartbeatTimeout = 50 * time.Millisecond
	conf.ElectionTimeout = 50 * time.Millisecond
	conf.LeaderLeaseTimeout = 50 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.BatchApplyCh = batched
	conf.LocalID = id
	conf.Logger = newTestLoggerWithPrefix(t, tag)
	store := NewInmemStore()
	snap := NewInmemSnapshotStore()
	if err := BootstrapCluster(conf, store, store, snap, trans, Configuration{Servers: []Server{{Suffrage: Voter, ID: id, Address: addr}}}); err != nil {
		t.Fatalf("BootstrapCluster failed: %v", err)
	}
	r, err := NewRaft(conf, &MockFSM{}, store, store, snap, trans)
	if err != nil {
		t.Fatalf("NewRaft failed: %v", err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) && r.State() != Leader {
		time.Sleep(5 * time.Millisecond)
	}
	if r.State() != Leader {
		t.Fatalf("single node did not become leader")
	}
	return r, func() { _ = trans.Close() }
}

// assuranceCall issues the API call under test and returns a future.
func assuranceCall(r *Raft, kind string) Future {
	switch kind {
	case "verify":
		return r.VerifyLeader()
	case "barrier":
		return r.Barrier(0)
	default:
		return r.Apply([]byte("x"), 0)
	}
}

// assuranceRunShutdownTrial issues many API calls, optionally shutting the node
// down concurrently, and counts how many futures never complete.
func assuranceRunShutdownTrial(t *testing.T, trial int, kind string, shutdown bool, batched bool) {
	const calls = 128
	const window = 4 * time.Second
	const postCalls = 8
	r, cleanup := assuranceSingleNode(t, kind, batched)
	defer cleanup()

	assuranceEmit(t, map[string]interface{}{
		"event":      "assurance_shutdown_setup",
		"trial":      trial,
		"kind":       kind,
		"shutdown":   shutdown,
		"calls":      calls,
		"window_ms":  window.Milliseconds(),
		"post_calls": postCalls,
		"local_id":   string(r.localID),
	})

	var (
		wg       sync.WaitGroup
		mu       sync.Mutex
		returned int
		stuck    int
		errs     = map[string]int{}
	)
	record := func(err error) {
		mu.Lock()
		defer mu.Unlock()
		if err == nil {
			errs["nil"]++
		} else {
			errs[err.Error()]++
		}
	}

	for i := 0; i < calls; i++ {
		f := assuranceCall(r, kind)
		wg.Add(1)
		go func() {
			defer wg.Done()
			done := make(chan error, 1)
			go func() { done <- f.Error() }()
			select {
			case err := <-done:
				mu.Lock()
				returned++
				mu.Unlock()
				record(err)
			case <-time.After(window):
				mu.Lock()
				stuck++
				mu.Unlock()
			}
		}()
	}

	// Let the callers fill the channel, then shut down underneath them.
	var shutdownErr string
	shutdownDone := make(chan struct{})
	if shutdown {
		go func() {
			time.Sleep(2 * time.Millisecond)
			if err := r.Shutdown().Error(); err != nil {
				shutdownErr = err.Error()
			}
			close(shutdownDone)
		}()
	} else {
		close(shutdownDone)
	}

	<-shutdownDone

	// Calls that arrive after shutdown has returned are a separate question:
	// the documented answer for them is an immediate error.
	postReturned := 0
	postOutcomes := map[string]int{}
	if shutdown {
		for i := 0; i < postCalls; i++ {
			f := assuranceCall(r, kind)
			done := make(chan error, 1)
			go func() { done <- f.Error() }()
			select {
			case err := <-done:
				postReturned++
				if err == nil {
					postOutcomes["nil"]++
				} else {
					postOutcomes[err.Error()]++
				}
			case <-time.After(500 * time.Millisecond):
				postOutcomes["stuck"]++
			}
		}
	}

	wg.Wait()

	mu.Lock()
	ret, st := returned, stuck
	detail := map[string]int{}
	for k, v := range errs {
		detail[k] = v
	}
	mu.Unlock()

	state := "running"
	if shutdown {
		state = "shutdown"
	}
	assuranceEmit(t, map[string]interface{}{
		"event":          "assurance_shutdown_result",
		"trial":          trial,
		"kind":           kind,
		"shutdown":       shutdown,
		"calls":          calls,
		"returned":       ret,
		"stuck":          st,
		"any_stuck":      st > 0,
		"shutdown_error": shutdownErr,
		"node_state":     state,
		"outcomes":       detail,
		"window_ms":      window.Milliseconds(),
		"post_returned":  postReturned,
		"post_calls":     postCalls,
		"post_responded": postReturned == postCalls,
		"post_outcomes":  postOutcomes,
		"batch_apply_ch": batched,
	})
}

// TestAssuranceShutdownFutureCompletion asks whether futures handed to Raft
// concurrently with Shutdown can be left uncompleted, comparing VerifyLeader,
// Barrier and Apply against a control where no shutdown happens.
func TestAssuranceShutdownFutureCompletion(t *testing.T) {
	kinds := []string{"verify", "barrier", "apply"}
	for trial := 0; trial < 3; trial++ {
		for _, kind := range kinds {
			assuranceRunShutdownTrial(t, trial, kind, true, false)
		}
	}
	for _, kind := range kinds {
		assuranceRunShutdownTrial(t, 99, kind, false, false)
	}
	// BatchApplyCh buffers applyCh, so the apply path should inherit the
	// strand that VerifyLeader shows with its always-buffered verifyCh.
	for trial := 0; trial < 3; trial++ {
		assuranceRunShutdownTrial(t, trial, "barrier", true, true)
		assuranceRunShutdownTrial(t, trial, "apply", true, true)
	}
}
