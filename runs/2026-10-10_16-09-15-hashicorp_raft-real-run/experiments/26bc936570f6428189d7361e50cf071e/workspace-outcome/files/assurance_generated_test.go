// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"errors"
	"fmt"
	"sync/atomic"
	"testing"
	"time"
)

// assuranceFailStore is an in-memory LogStore/StableStore whose StoreLogs can be
// made to fail on demand. It models a transient durable-write failure at the
// real LogStore boundary; every other operation behaves like InmemStore.
type assuranceFailStore struct {
	*InmemStore
	failStoreLogs atomic.Bool
}

func (f *assuranceFailStore) StoreLogs(logs []*Log) error {
	if f.failStoreLogs.Load() {
		return errors.New("injected LogStore.StoreLogs failure")
	}
	return f.InmemStore.StoreLogs(logs)
}

func assuranceEmit(t *testing.T, ev map[string]interface{}) {
	t.Helper()
	buf, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(buf))
}

func assuranceServers(c Configuration) []string {
	out := make([]string, 0, len(c.Servers))
	for _, s := range c.Servers {
		out = append(out, fmt.Sprintf("%s/%s/%s", s.ID, s.Address, s.Suffrage))
	}
	return out
}

// assuranceSingleNode builds one bootstrapped voter with the supplied store.
func assuranceSingleNode(t *testing.T, store *assuranceFailStore, trans *InmemTransport, fsm FSM) *Raft {
	t.Helper()
	conf := inmemConfig(t)
	conf.LocalID = ServerID(trans.LocalAddr())
	snap := NewInmemSnapshotStore()
	boot := Configuration{Servers: []Server{{Suffrage: Voter, ID: conf.LocalID, Address: trans.LocalAddr()}}}
	if err := BootstrapCluster(conf, store, store, snap, trans, boot); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	r, err := NewRaft(conf, fsm, store, store, snap, trans)
	if err != nil {
		t.Fatalf("new raft: %v", err)
	}
	return r
}

func assuranceWaitLeader(r *Raft, d time.Duration) bool {
	deadline := time.Now().Add(d)
	for r.State() != Leader && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	return r.State() == Leader
}

// TestAssuranceConfigPublishedWithoutPersist asks whether a membership change
// whose durable log write fails is still published into the node's live
// configuration, and what that does to its own progress.
func TestAssuranceConfigPublishedWithoutPersist(t *testing.T) {
	_, trans := NewInmemTransport("")
	store := &assuranceFailStore{InmemStore: NewInmemStore()}
	r := assuranceSingleNode(t, store, trans, &MockFSM{})
	defer r.Shutdown()

	if !assuranceWaitLeader(r, 3*time.Second) {
		t.Fatalf("never became leader, state=%v", r.State())
	}
	if err := r.Apply([]byte("baseline"), 2*time.Second).Error(); err != nil {
		t.Fatalf("baseline apply: %v", err)
	}

	before := r.GetConfiguration()
	_ = before.Error()
	durableBefore, _ := store.LastIndex()

	// Fail exactly the durable write that carries the membership change.
	store.failStoreLogs.Store(true)
	addErr := r.AddVoter(ServerID("phantom"), ServerAddress("phantom-addr"), 0, 2*time.Second).Error()
	store.failStoreLogs.Store(false)

	after := r.GetConfiguration()
	_ = after.Error()
	durableAfter, _ := store.LastIndex()

	var stored Log
	assignedIdx := durableBefore + 1
	getErr := store.GetLog(assignedIdx, &stored)

	assuranceEmit(t, map[string]interface{}{
		"event":                       "config_publish_after_failed_durable_write",
		"add_voter_error":             fmt.Sprint(addErr),
		"config_index_before":         before.Index(),
		"config_servers_before":       assuranceServers(before.Configuration()),
		"durable_last_index_before":   durableBefore,
		"config_index_after":          after.Index(),
		"config_servers_after":        assuranceServers(after.Configuration()),
		"durable_last_index_after":    durableAfter,
		"assigned_config_index":       assignedIdx,
		"getlog_at_assigned_idx_err":  fmt.Sprint(getErr),
		"raft_last_index":             r.LastIndex(),
		"published_ahead_of_durable":  len(after.Configuration().Servers) > len(before.Configuration().Servers),
		"published_config_index_api":  after.Index(),
	})

	// Watch whether this single-voter cluster can still make progress.
	everLeader := false
	leaderSamples, samples := 0, 0
	watchUntil := time.Now().Add(1500 * time.Millisecond)
	for time.Now().Before(watchUntil) {
		samples++
		if r.State() == Leader {
			everLeader = true
			leaderSamples++
		}
		time.Sleep(10 * time.Millisecond)
	}

	live := r.GetConfiguration()
	_ = live.Error()
	voters := 0
	for _, s := range live.Configuration().Servers {
		if s.Suffrage == Voter {
			voters++
		}
	}
	assuranceEmit(t, map[string]interface{}{
		"event":                        "progress_after_failed_durable_write",
		"state":                        r.State().String(),
		"ever_leader_in_window":        everLeader,
		"leader_samples":               leaderSamples,
		"samples":                      samples,
		"voters_in_live_configuration": voters,
		"quorum_size_live":             voters/2 + 1,
		"reachable_voters":             1,
		"commit_index":                 r.CommitIndex(),
		"last_index":                   r.LastIndex(),
	})
}

// TestAssuranceRestartRepairsAuthorityContext closes the recovery question: after
// the failed membership change, does a restart from the same durable store
// restore a consistent authority context?
func TestAssuranceRestartRepairsAuthorityContext(t *testing.T) {
	addr := NewInmemAddr()
	_, trans := NewInmemTransport(addr)
	store := &assuranceFailStore{InmemStore: NewInmemStore()}
	snap := NewInmemSnapshotStore()
	conf := inmemConfig(t)
	conf.LocalID = ServerID(addr)
	boot := Configuration{Servers: []Server{{Suffrage: Voter, ID: conf.LocalID, Address: addr}}}
	if err := BootstrapCluster(conf, store, store, snap, trans, boot); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	r, err := NewRaft(conf, &MockFSM{}, store, store, snap, trans)
	if err != nil {
		t.Fatalf("new raft: %v", err)
	}
	if !assuranceWaitLeader(r, 3*time.Second) {
		t.Fatalf("never became leader, state=%v", r.State())
	}

	store.failStoreLogs.Store(true)
	addErr := r.AddVoter(ServerID("phantom"), ServerAddress("phantom-addr"), 0, 2*time.Second).Error()
	store.failStoreLogs.Store(false)

	preRestart := r.GetConfiguration()
	_ = preRestart.Error()
	preState := r.State().String()
	durable, _ := store.LastIndex()
	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}

	// Restart from the same durable store: the phantom entry was never stored.
	_, trans2 := NewInmemTransport(addr)
	r2, err := NewRaft(conf, &MockFSM{}, store, store, snap, trans2)
	if err != nil {
		t.Fatalf("restart raft: %v", err)
	}
	defer r2.Shutdown()
	becameLeader := assuranceWaitLeader(r2, 3*time.Second)
	post := r2.GetConfiguration()
	_ = post.Error()
	assuranceEmit(t, map[string]interface{}{
		"event":                    "restart_after_failed_durable_write",
		"add_voter_error":          fmt.Sprint(addErr),
		"durable_last_index":       durable,
		"state_before_restart":     preState,
		"servers_before_restart":   assuranceServers(preRestart.Configuration()),
		"became_leader_after":      becameLeader,
		"servers_after_restart":    assuranceServers(post.Configuration()),
		"voters_after_restart":     len(post.Configuration().Servers),
		"commit_index_after":       r2.CommitIndex(),
	})
}

// TestAssuranceConfigPersistControl is the success-path control: when the same
// membership change persists, the entry is in the log store, so the published
// configuration has a durable counterpart.
func TestAssuranceConfigPersistControl(t *testing.T) {
	_, trans := NewInmemTransport("")
	store := &assuranceFailStore{InmemStore: NewInmemStore()}
	r := assuranceSingleNode(t, store, trans, &MockFSM{})
	defer r.Shutdown()

	if !assuranceWaitLeader(r, 3*time.Second) {
		t.Fatalf("never became leader, state=%v", r.State())
	}
	if err := r.Apply([]byte("baseline"), 2*time.Second).Error(); err != nil {
		t.Fatalf("baseline apply: %v", err)
	}
	durableBefore, _ := store.LastIndex()
	before := r.GetConfiguration()
	_ = before.Error()

	addErr := r.AddVoter(ServerID("phantom"), ServerAddress("phantom-addr"), 0, 2*time.Second).Error()
	assignedIdx := durableBefore + 1
	var stored Log
	getErr := store.GetLog(assignedIdx, &stored)
	after := r.GetConfiguration()
	_ = after.Error()
	durableAfter, _ := store.LastIndex()

	assuranceEmit(t, map[string]interface{}{
		"event":                      "config_persist_success_control",
		"add_voter_error":            fmt.Sprint(addErr),
		"assigned_config_index":      assignedIdx,
		"getlog_at_assigned_idx_err": fmt.Sprint(getErr),
		"durable_last_index_after":   durableAfter,
		"config_servers_before":      assuranceServers(before.Configuration()),
		"config_servers_after":       assuranceServers(after.Configuration()),
	})
}
