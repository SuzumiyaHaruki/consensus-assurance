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
	attempts      atomic.Int64
	failures      atomic.Int64
}

func (f *assuranceFailStore) StoreLogs(logs []*Log) error {
	f.attempts.Add(1)
	if f.failStoreLogs.Load() {
		f.failures.Add(1)
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
	node := string(r.localID)
	assuranceEmit(t, map[string]interface{}{
		"event": "assurance_leader_established",
		"node":  node,
		"term":  r.getCurrentTerm(),
	})
	assuranceEmit(t, map[string]interface{}{
		"event":     "assurance_config_change_attempt",
		"node":      node,
		"attempted": true,
	})

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
	entryDurable := getErr == nil

	// Decisive monitor event: was the published configuration durable?
	assuranceEmit(t, map[string]interface{}{
		"event":                     "assurance_config_published",
		"node":                      node,
		"published_ahead_of_durable": true,
		"entry_durable":             entryDurable,
		"published_voters":          len(after.Configuration().Servers),
		"durable_last_index":        durableAfter,
	})

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

// TestAssuranceFollowerStoreFailure asks whether the published-vs-durable
// divergence also arises when the failing durable write is on the follower
// side of a real two-node replication path.
func TestAssuranceFollowerStoreFailure(t *testing.T) {
	addrA, transA := NewInmemTransport("")
	addrB, transB := NewInmemTransport("")
	transA.Connect(addrB, transB)
	transB.Connect(addrA, transA)

	confA, confB := inmemConfig(t), inmemConfig(t)
	confA.LocalID, confB.LocalID = ServerID(addrA), ServerID(addrB)
	storeA := &assuranceFailStore{InmemStore: NewInmemStore()}
	storeB := &assuranceFailStore{InmemStore: NewInmemStore()}
	snapA, snapB := NewInmemSnapshotStore(), NewInmemSnapshotStore()
	boot := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: ServerID(addrA), Address: addrA},
		{Suffrage: Voter, ID: ServerID(addrB), Address: addrB},
	}}
	if err := BootstrapCluster(confA, storeA, storeA, snapA, transA, boot); err != nil {
		t.Fatalf("bootstrap A: %v", err)
	}
	if err := BootstrapCluster(confB, storeB, storeB, snapB, transB, boot); err != nil {
		t.Fatalf("bootstrap B: %v", err)
	}
	rA, err := NewRaft(confA, &MockFSM{}, storeA, storeA, snapA, transA)
	if err != nil {
		t.Fatalf("raft A: %v", err)
	}
	defer rA.Shutdown()
	rB, err := NewRaft(confB, &MockFSM{}, storeB, storeB, snapB, transB)
	if err != nil {
		t.Fatalf("raft B: %v", err)
	}
	defer rB.Shutdown()

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) && rA.State() != Leader && rB.State() != Leader {
		time.Sleep(10 * time.Millisecond)
	}
	leader, follower := rA, rB
	followerStore, followerTrans := storeB, transA
	if rB.State() == Leader {
		leader, follower = rB, rA
		followerStore, followerTrans = storeA, transB
	}
	_ = followerTrans
	if leader.State() != Leader {
		t.Fatalf("no leader: A=%v B=%v", rA.State(), rB.State())
	}
	node := string(follower.localID)
	fCfgBefore := follower.GetConfiguration()
	_ = fCfgBefore.Error()
	fDurableBefore, _ := followerStore.LastIndex()
	attemptsBefore, failuresBefore := followerStore.attempts.Load(), followerStore.failures.Load()

	// Fail the follower's durable write while the leader replicates a change.
	followerStore.failStoreLogs.Store(true)
	leader.AddVoter(ServerID("phantom"), ServerAddress("phantom-addr"), 0, 100*time.Millisecond)
	time.Sleep(600 * time.Millisecond)
	followerStore.failStoreLogs.Store(false)

	fCfgAfter := follower.GetConfiguration()
	_ = fCfgAfter.Error()
	fDurableAfter, _ := followerStore.LastIndex()
	assuranceEmit(t, map[string]interface{}{
		"event":                       "follower_store_failure",
		"node":                        node,
		"store_log_attempts":          followerStore.attempts.Load() - attemptsBefore,
		"store_log_failures":          followerStore.failures.Load() - failuresBefore,
		"follower_servers_before":     assuranceServers(fCfgBefore.Configuration()),
		"follower_servers_after":      assuranceServers(fCfgAfter.Configuration()),
		"follower_durable_before":     fDurableBefore,
		"follower_durable_after":      fDurableAfter,
		"follower_last_index":         follower.LastIndex(),
		"follower_published_phantom":  len(fCfgAfter.Configuration().Servers) > len(fCfgBefore.Configuration().Servers),
		"follower_state":              follower.State().String(),
	})
}

// TestAssuranceTruncationThenStoreFailure probes the remaining timing: a
// conflicting AppendEntries suffix is deleted, and the replacement write then
// fails at the real LogStore boundary.
func TestAssuranceTruncationThenStoreFailure(t *testing.T) {
	_, trans := NewInmemTransport("")
	store := &assuranceFailStore{InmemStore: NewInmemStore()}
	r := assuranceSingleNode(t, store, trans, &MockFSM{})
	defer r.Shutdown()

	if !assuranceWaitLeader(r, 3*time.Second) {
		t.Fatalf("never became leader, state=%v", r.State())
	}
	for _, v := range []string{"one", "two"} {
		if err := r.Apply([]byte(v), 2*time.Second).Error(); err != nil {
			t.Fatalf("apply %s: %v", v, err)
		}
	}
	cachedBefore, termBefore := r.getLastLog()
	durableBefore, _ := store.LastIndex()

	// A different leader in a higher term rewrites the suffix from index 2.
	newTerm := termBefore + 5
	req := &AppendEntriesRequest{
		RPCHeader:         r.getRPCHeader(),
		Term:              newTerm,
		PrevLogEntry:      1,
		PrevLogTerm:       1,
		Entries:           []*Log{{Index: 2, Term: newTerm, Type: LogNoop}, {Index: 3, Term: newTerm, Type: LogNoop}, {Index: 4, Term: newTerm, Type: LogNoop}},
	}
	store.failStoreLogs.Store(true)
	respCh := make(chan RPCResponse, 1)
	rpc := RPC{Command: req, RespChan: respCh}
	r.appendEntries(rpc, req)
	store.failStoreLogs.Store(false)
	resp := <-respCh
	appendResp, _ := resp.Response.(*AppendEntriesResponse)

	cachedAfter, _ := r.getLastLog()
	durableAfter, _ := store.LastIndex()
	var l Log
	getErr := store.GetLog(cachedAfter, &l)
	assuranceEmit(t, map[string]interface{}{
		"event":                    "truncation_then_store_failure",
		"cached_last_index_before": cachedBefore,
		"durable_last_index_before": durableBefore,
		"cached_last_index_after":  cachedAfter,
		"durable_last_index_after": durableAfter,
		"reported_last_index":      r.LastIndex(),
		"getlog_at_cached_err":     fmt.Sprint(getErr),
		"append_success":           appendResp != nil && appendResp.Success,
		"cached_ahead_of_durable":  cachedAfter > durableAfter,
		"state":                    r.State().String(),
	})
}

// TestAssuranceRealProducerTruncation drives the truncation timing through real
// producers: an isolated leader accumulates uncommitted entries, a new leader
// is elected by the other two voters and appends at those indices, and the
// isolated node's store fails while the suffix is overwritten.
func TestAssuranceRealProducerTruncation(t *testing.T) {
	type node struct {
		addr  ServerAddress
		trans *InmemTransport
		store *assuranceFailStore
		raft  *Raft
	}
	nodes := make([]*node, 3)
	addrs := make([]ServerAddress, 3)
	for i := range nodes {
		addr, trans := NewInmemTransport("")
		addrs[i] = addr
		nodes[i] = &node{addr: addr, trans: trans, store: &assuranceFailStore{InmemStore: NewInmemStore()}}
	}
	boot := Configuration{}
	for _, a := range addrs {
		boot.Servers = append(boot.Servers, Server{Suffrage: Voter, ID: ServerID(a), Address: a})
	}
	for _, n := range nodes {
		for _, other := range nodes {
			if other != n {
				n.trans.Connect(other.addr, other.trans)
			}
		}
		conf := inmemConfig(t)
		conf.LocalID = ServerID(n.addr)
		snap := NewInmemSnapshotStore()
		if err := BootstrapCluster(conf, n.store, n.store, snap, n.trans, boot); err != nil {
			t.Fatalf("bootstrap: %v", err)
		}
		r, err := NewRaft(conf, &MockFSM{}, n.store, n.store, snap, n.trans)
		if err != nil {
			t.Fatalf("new raft: %v", err)
		}
		n.raft = r
		defer r.Shutdown()
	}

	deadline := time.Now().Add(4 * time.Second)
	var leader *node
	for leader == nil && time.Now().Before(deadline) {
		for _, n := range nodes {
			if n.raft.State() == Leader {
				leader = n
				break
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	if leader == nil {
		t.Fatalf("no leader elected")
	}

	// Isolate the leader so its own appends stay uncommitted in its log.
	others := []*node{}
	for _, n := range nodes {
		if n != leader {
			others = append(others, n)
			leader.trans.Disconnect(n.addr)
			n.trans.Disconnect(leader.addr)
		}
	}
	for i := 0; i < 3; i++ {
		leader.raft.Apply([]byte(fmt.Sprintf("isolated-%d", i)), 0)
	}
	isolatedCached, _ := leader.raft.getLastLog()
	time.Sleep(400 * time.Millisecond)

	// The remaining two voters elect a new leader and commit a new entry.
	deadline = time.Now().Add(4 * time.Second)
	var newLeader *node
	for newLeader == nil && time.Now().Before(deadline) {
		for _, n := range others {
			if n.raft.State() == Leader {
				newLeader = n
				break
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	if newLeader == nil {
		t.Fatalf("no new leader elected among the remaining voters")
	}
	if err := newLeader.raft.Apply([]byte("new-term"), 2*time.Second).Error(); err != nil {
		t.Fatalf("new leader apply: %v", err)
	}

	// Fail the isolated node's store, then let the new leader overwrite its suffix.
	leader.store.failStoreLogs.Store(true)
	for _, n := range others {
		leader.trans.Connect(n.addr, n.trans)
		n.trans.Connect(leader.addr, leader.trans)
	}
	time.Sleep(800 * time.Millisecond)
	leader.store.failStoreLogs.Store(false)

	cached, _ := leader.raft.getLastLog()
	durable, _ := leader.store.LastIndex()
	var l Log
	getErr := leader.store.GetLog(cached, &l)
	assuranceEmit(t, map[string]interface{}{
		"event":                     "real_producer_truncation",
		"node":                      string(leader.raft.localID),
		"isolated_cached_last_index": isolatedCached,
		"cached_last_index_after":   cached,
		"durable_last_index_after":  durable,
		"reported_last_index":       leader.raft.LastIndex(),
		"getlog_at_cached_err":      fmt.Sprint(getErr),
		"cached_ahead_of_durable":   cached > durable,
		"state":                     leader.raft.State().String(),
		"termination":               true,
	})
}
