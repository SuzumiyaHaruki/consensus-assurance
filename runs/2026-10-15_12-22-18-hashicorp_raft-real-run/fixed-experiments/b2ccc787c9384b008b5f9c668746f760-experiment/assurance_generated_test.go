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

func assuranceSingleNode(t *testing.T, tag string) (*Raft, func()) {
	addr, trans := NewInmemTransport("")
	id := ServerID("server-" + string(addr))
	conf := DefaultConfig()
	conf.HeartbeatTimeout = 50 * time.Millisecond
	conf.ElectionTimeout = 50 * time.Millisecond
	conf.LeaderLeaseTimeout = 50 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
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
func assuranceRunShutdownTrial(t *testing.T, trial int, kind string, shutdown bool) {
	const calls = 64
	r, cleanup := assuranceSingleNode(t, kind)
	defer cleanup()

	assuranceEmit(t, map[string]interface{}{
		"event":    "assurance_shutdown_setup",
		"trial":    trial,
		"kind":     kind,
		"shutdown": shutdown,
		"calls":    calls,
		"local_id": string(r.localID),
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
			case <-time.After(1500 * time.Millisecond):
				mu.Lock()
				stuck++
				mu.Unlock()
			}
		}()
	}

	var shutdownErr string
	shutdownDone := make(chan struct{})
	if shutdown {
		go func() {
			if err := r.Shutdown().Error(); err != nil {
				shutdownErr = err.Error()
			}
			close(shutdownDone)
		}()
	} else {
		close(shutdownDone)
	}

	<-shutdownDone
	if shutdown {
		// Give every future a generous window after shutdown has returned.
		time.Sleep(400 * time.Millisecond)
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
	})
}

// TestAssuranceShutdownFutureCompletion asks whether futures handed to Raft
// concurrently with Shutdown can be left uncompleted, comparing VerifyLeader,
// Barrier and Apply against a control where no shutdown happens.
func TestAssuranceShutdownFutureCompletion(t *testing.T) {
	kinds := []string{"verify", "barrier", "apply"}
	for trial := 0; trial < 3; trial++ {
		for _, kind := range kinds {
			assuranceRunShutdownTrial(t, trial, kind, true)
		}
	}
	for _, kind := range kinds {
		assuranceRunShutdownTrial(t, 99, kind, false)
	}
}
