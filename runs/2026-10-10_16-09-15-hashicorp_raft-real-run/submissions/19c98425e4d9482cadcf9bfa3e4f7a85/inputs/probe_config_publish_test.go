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

// TestAssuranceConfigPublishedWithoutPersist asks whether a membership change
// whose durable log write fails is still published into the node's live
// configuration, and what that does to its own progress.
func TestAssuranceConfigPublishedWithoutPersist(t *testing.T) {
	conf := inmemConfig(t)
	addr, trans := NewInmemTransport("")
	conf.LocalID = ServerID(addr)

	store := &assuranceFailStore{InmemStore: NewInmemStore()}
	snap := NewInmemSnapshotStore()
	fsm := &MockFSM{}

	boot := Configuration{Servers: []Server{{Suffrage: Voter, ID: conf.LocalID, Address: addr}}}
	if err := BootstrapCluster(conf, store, store, snap, trans, boot); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	r, err := NewRaft(conf, fsm, store, store, snap, trans)
	if err != nil {
		t.Fatalf("new raft: %v", err)
	}
	defer r.Shutdown()

	deadline := time.Now().Add(3 * time.Second)
	for r.State() != Leader && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if r.State() != Leader {
		t.Fatalf("never became leader, state=%v", r.State())
	}
	if err := r.Apply([]byte("baseline"), 2*time.Second).Error(); err != nil {
		t.Fatalf("baseline apply: %v", err)
	}

	before := r.GetConfiguration()
	if err := before.Error(); err != nil {
		t.Fatalf("get configuration before: %v", err)
	}
	durableBefore, err := store.LastIndex()
	if err != nil {
		t.Fatalf("durable last index before: %v", err)
	}

	// Fail exactly the durable write that carries the membership change.
	store.failStoreLogs.Store(true)
	addErr := r.AddVoter(ServerID("phantom"), ServerAddress("phantom-addr"), 0, 2*time.Second).Error()
	store.failStoreLogs.Store(false)

	after := r.GetConfiguration()
	if err := after.Error(); err != nil {
		t.Fatalf("get configuration after: %v", err)
	}
	durableAfter, err := store.LastIndex()
	if err != nil {
		t.Fatalf("durable last index after: %v", err)
	}

	// The membership entry was assigned the next log slot; is that slot durable?
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

	// Now watch whether this single-node cluster can still make progress.
	everLeader := false
	leaderSamples := 0
	samples := 0
	watchUntil := time.Now().Add(1500 * time.Millisecond)
	for time.Now().Before(watchUntil) {
		samples++
		if r.State() == Leader {
			everLeader = true
			leaderSamples++
		}
		time.Sleep(10 * time.Millisecond)
	}

	// Independent identity for the quorum requirement the node is now using.
	liveCfg := r.GetConfiguration()
	_ = liveCfg.Error()
	voters := 0
	for _, s := range liveCfg.Configuration().Servers {
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
