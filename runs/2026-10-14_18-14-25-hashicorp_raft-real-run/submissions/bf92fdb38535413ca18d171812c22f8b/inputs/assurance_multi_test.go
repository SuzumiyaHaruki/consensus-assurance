package raft

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"testing"
	"time"
)

// TestAssuranceStaleConfigurationCommitQuorum
//
// Sourced question (gap 98ee8dfd5fac4b84915f91ed4b094bcf-gap-1): after a node restarts
// with Config.RestoreCommittedLogs enabled, can the older configuration it recovers
// decide a commit that the committed configuration would not allow?
//
// Design: three voters A, B, C. A snapshots while {A,B,C} is committed, C is then removed
// (committed {A,B}) and further entries are committed. A restarts with the flag on, so
// its tracked configuration is the snapshot's {A,B,C}, and B is partitioned while C stays
// connected. A's majority then counts C, which the committed configuration no longer
// contains.

type assuranceMultiEvent map[string]interface{}

func assuranceMultiEmit(ev assuranceMultiEvent) {
	b, err := json.Marshal(ev)
	if err != nil {
		fmt.Println(`CA_EVENT {"event":"assurance.multi_marshal_error"}`)
		return
	}
	fmt.Println("CA_EVENT " + string(b))
}

type assuranceMultiNode struct {
	name   string
	id     ServerID
	addr   ServerAddress
	trans  *InmemTransport
	logs   *InmemCommitTrackingStore
	stable *InmemStore
	snaps  *InmemSnapshotStore
	fsm    *MockFSM
	conf   *Config
	raft   *Raft
}

func assuranceMultiNewNode(t *testing.T, name string) *assuranceMultiNode {
	t.Helper()
	addr, trans := NewInmemTransport("")
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.LocalID = ServerID("server-" + string(addr))
	return &assuranceMultiNode{
		name:   name,
		id:     ServerID("server-" + string(addr)),
		addr:   addr,
		trans:  trans,
		logs:   NewInmemCommitTrackingStore(),
		stable: NewInmemStore(),
		snaps:  NewInmemSnapshotStore(),
		fsm:    &MockFSM{},
		conf:   conf,
	}
}

func assuranceMultiConfig(nodes []*assuranceMultiNode) Configuration {
	var c Configuration
	for _, n := range nodes {
		c.Servers = append(c.Servers, Server{Suffrage: Voter, ID: n.id, Address: n.addr})
	}
	return c
}

func assuranceMultiWire(nodes []*assuranceMultiNode) {
	for i, a := range nodes {
		for j, b := range nodes {
			if i == j {
				continue
			}
			a.trans.Connect(b.addr, b.trans)
		}
	}
}

func assuranceMultiLeader(nodes []*assuranceMultiNode, timeout time.Duration) *assuranceMultiNode {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		for _, n := range nodes {
			if n.raft != nil && n.raft.State() == Leader {
				return n
			}
		}
		time.Sleep(5 * time.Millisecond)
	}
	return nil
}

func assuranceMultiWaitLeader(n *assuranceMultiNode, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if n.raft.State() == Leader {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	return n.raft.State() == Leader
}

func assuranceMultiWaitNode(r *Raft, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if r.State() == Leader {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	return r.State() == Leader
}

func assuranceMultiConfigurations(r *Raft) configurations {
	fut := &configurationsFuture{}
	fut.ShutdownCh = r.shutdownCh
	fut.init()
	select {
	case r.configurationsCh <- fut:
	case <-r.shutdownCh:
		return configurations{}
	}
	if err := fut.Error(); err != nil {
		return configurations{}
	}
	return fut.configurations
}

func assuranceMultiSortedIDs(c Configuration) string {
	out := make([]string, 0, len(c.Servers))
	for _, s := range c.Servers {
		out = append(out, string(s.ID))
	}
	sort.Strings(out)
	return strings.Join(out, ",")
}

func assuranceMultiVoters(c Configuration) int {
	v := 0
	for _, s := range c.Servers {
		if s.Suffrage == Voter {
			v++
		}
	}
	return v
}

func assuranceMultiWaitFSMCommand(n *assuranceMultiNode, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if len(n.fsm.Logs()) > 0 {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	return len(n.fsm.Logs()) > 0
}

func assuranceMultiLastIndex(n *assuranceMultiNode) uint64 {
	idx, err := n.logs.LastIndex()
	if err != nil {
		return 0
	}
	return idx
}

// assuranceMultiLogConfig finds the newest configuration entry at or below limit.
func assuranceMultiLogConfig(logs *InmemCommitTrackingStore, limit uint64) (uint64, int, string) {
	var idx uint64
	var voters int
	var ids string
	for i := uint64(1); i <= limit; i++ {
		var entry Log
		if err := logs.GetLog(i, &entry); err != nil {
			return idx, voters, ids
		}
		if entry.Type == LogConfiguration {
			c := DecodeConfiguration(entry.Data)
			idx, voters, ids = i, assuranceMultiVoters(c), assuranceMultiSortedIDs(c)
		}
	}
	return idx, voters, ids
}

func TestAssuranceStaleConfigurationCommitQuorum(t *testing.T) {
	a := assuranceMultiNewNode(t, "A")
	b := assuranceMultiNewNode(t, "B")
	c := assuranceMultiNewNode(t, "C")
	nodes := []*assuranceMultiNode{a, b, c}
	configuration := assuranceMultiConfig(nodes)

	assuranceMultiWire(nodes)
	for _, n := range nodes {
		if err := BootstrapCluster(n.conf, n.logs, n.stable, n.snaps, n.trans, configuration); err != nil {
			t.Fatalf("bootstrap %s failed: %v", n.name, err)
		}
		r, err := NewRaft(n.conf, n.fsm, n.logs, n.stable, n.snaps, n.trans)
		if err != nil {
			t.Fatalf("NewRaft %s failed: %v", n.name, err)
		}
		n.raft = r
		// Shut every node down on any exit path: raft goroutines log through the test
		// logger, and a log after the test returns panics the test binary.
		defer func(r *Raft) { _ = r.Shutdown().Error() }(r)
	}

	leader := assuranceMultiLeader(nodes, 5*time.Second)
	if leader == nil {
		t.Fatalf("no leader was elected")
	}
	assuranceMultiEmit(assuranceMultiEvent{
		"event":          "assurance.multi.start",
		"leader":         leader.name,
		"a_id":           string(a.id),
		"b_id":           string(b.id),
		"c_id":           string(c.id),
		"configured_ids": assuranceMultiSortedIDs(configuration),
	})

	// Make A the leader through a real leadership transfer so that the rest of the case is
	// deterministic: the node that is removed must not be the leader, and the node that is
	// restarted must have applied entries before it can snapshot.
	if leader != a {
		if err := leader.raft.LeadershipTransferToServer(a.id, a.addr).Error(); err != nil {
			t.Fatalf("leadership transfer to A failed: %v", err)
		}
	}
	if !assuranceMultiWaitNode(a.raft, 5*time.Second) {
		t.Fatalf("A did not become leader after transfer")
	}
	leader = a

	// Commit one command through A and wait until A's FSM has applied it: a plain FSM
	// receives only command entries, and runFSM refuses a snapshot request while its own
	// last applied index is still zero (ErrNothingNewToSnapshot).
	if err := leader.raft.Apply([]byte("before-snapshot"), 2*time.Second).Error(); err != nil {
		t.Fatalf("pre-snapshot apply failed: %v", err)
	}
	if !assuranceMultiWaitFSMCommand(a, 3*time.Second) {
		t.Fatalf("A's FSM applied no command before the snapshot request")
	}

	// Snapshot A while {A,B,C} is still the committed configuration.
	if err := a.raft.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot on A failed: %v", err)
	}
	snapIndex, snapTerm := a.raft.getLastSnapshot()
	assuranceMultiEmit(assuranceMultiEvent{
		"event":          "assurance.multi.snapshot",
		"node":           "A",
		"snapshot_index": snapIndex,
		"snapshot_term":  snapTerm,
	})

	// Remove C, which commits against {A,B}, then commit more entries.
	if err := leader.raft.RemoveServer(c.id, 0, 2*time.Second).Error(); err != nil {
		t.Fatalf("RemoveServer(C) failed: %v", err)
	}
	for i := 0; i < 3; i++ {
		if err := leader.raft.Apply([]byte(fmt.Sprintf("after-remove-%d", i)), 2*time.Second).Error(); err != nil {
			t.Fatalf("post-removal apply %d failed: %v", i, err)
		}
	}
	aStaged, _ := a.logs.GetCommitIndex()
	aLast := assuranceMultiLastIndex(a)
	removeIndex, removeVoters, removeIDs := assuranceMultiLogConfig(a.logs, aLast)
	assuranceMultiEmit(assuranceMultiEvent{
		"event":                 "assurance.multi.removed",
		"removed_id":            string(c.id),
		"log_config_index":      removeIndex,
		"log_config_voters":     removeVoters,
		"log_config_ids":        removeIDs,
		"a_log_last_index":      aLast,
		"a_staged_commit_index": aStaged,
		"leader_after_removal":  leader.name,
	})

	// Restart A with the flag on, over the same stores, and partition B from A and C.
	if err := a.raft.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown A failed: %v", err)
	}
	b.trans.Disconnect(a.addr)
	b.trans.Disconnect(c.addr)
	c.trans.Disconnect(b.addr)

	_, newTrans := NewInmemTransport(a.addr)
	newTrans.Connect(c.addr, c.trans)
	c.trans.Connect(a.addr, newTrans)
	newTrans.Disconnect(b.addr)

	confA := *a.conf
	confA.RestoreCommittedLogs = true
	restartedFSM := &MockFSM{}
	restarted, err := NewRaft(&confA, restartedFSM, a.logs, a.stable, a.snaps, newTrans)
	if err != nil {
		t.Fatalf("restart of A failed: %v", err)
	}
	defer func() { _ = restarted.Shutdown().Error() }()
	a.raft = restarted
	a.trans = newTrans

	confs := assuranceMultiConfigurations(restarted)
	assuranceMultiEmit(assuranceMultiEvent{
		"event":                  "assurance.multi.restart",
		"node":                   "A",
		"latest_config_index":    confs.latestIndex,
		"latest_config_voters":   assuranceMultiVoters(confs.latest),
		"latest_config_ids":      assuranceMultiSortedIDs(confs.latest),
		"committed_config_index": confs.committedIndex,
		"log_config_index":       removeIndex,
		"log_config_voters":      removeVoters,
		"log_config_ids":         removeIDs,
		"b_connected":            false,
		"c_connected":            true,
		"b_last_index":           assuranceMultiLastIndex(b),
		"c_last_index":           assuranceMultiLastIndex(c),
	})

	wonLeadership := assuranceMultiWaitNode(restarted, 5*time.Second)
	outcome := assuranceMultiEvent{
		"event":                   "assurance.multi.outcome",
		"a_became_leader":         wonLeadership,
		"a_tracked_voters":        assuranceMultiVoters(confs.latest),
		"a_tracked_ids":           assuranceMultiSortedIDs(confs.latest),
		"committed_config_voters": removeVoters,
		"committed_config_ids":    removeIDs,
		"b_connected":             false,
	}

	if wonLeadership {
		payload := []byte("stale-quorum-entry")
		future := restarted.Apply(payload, 2*time.Second)
		applyErr := future.Error()
		entryIndex := future.Index()
		time.Sleep(200 * time.Millisecond)

		var stored Log
		var entryTerm uint64
		if err := a.logs.GetLog(entryIndex, &stored); err == nil {
			entryTerm = stored.Term
		}
		var bEntry Log
		bHasEntry := b.logs.GetLog(entryIndex, &bEntry) == nil
		var cEntry Log
		cHasEntry := c.logs.GetLog(entryIndex, &cEntry) == nil

		applied := false
		for _, l := range restartedFSM.Logs() {
			if string(l) == string(payload) {
				applied = true
				break
			}
		}

		outcome["entry_index"] = entryIndex
		outcome["entry_term"] = entryTerm
		outcome["apply_error"] = applyErr
		outcome["a_commit_index"] = restarted.CommitIndex()
		outcome["a_applied_index"] = restarted.AppliedIndex()
		outcome["b_log_has_entry"] = bHasEntry
		outcome["c_log_has_entry"] = cHasEntry
		outcome["c_entry_term"] = cEntry.Term
		outcome["a_fsm_applied_payload"] = applied
		outcome["committed_config_majority_lacks_entry"] = applyErr == nil && entryTerm != 0 && !bHasEntry
	}
	assuranceMultiEmit(outcome)

	// Stop the restarted node before the test returns so nothing logs afterwards.
	_ = restarted.Shutdown().Error()
}
