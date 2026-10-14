package raft

import (
	"encoding/json"
	"fmt"
	"runtime"
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

func assuranceMultiStackExcerpt(text string, marker string) (string, int) {
	count := strings.Count(text, marker)
	if count == 0 {
		return "", 0
	}
	idx := strings.Index(text, marker)
	start := idx - 200
	if start < 0 {
		start = 0
	}
	end := idx + 300
	if end > len(text) {
		end = len(text)
	}
	return strings.ReplaceAll(text[start:end], "\n", " | "), count
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

// TestAssuranceRecoveredSnapshotConfiguration
//
// Sourced question: when a node restarts with Config.RestoreCommittedLogs enabled and
// recovers no configuration, does that missing configuration reach durable state? A node
// whose tracked committed configuration is empty will write that empty configuration and
// its index into the snapshot metadata it creates, and a later restart restores the
// configuration from that snapshot, so the loss outlives the replay path that produced it.
func TestAssuranceRecoveredSnapshotConfiguration(t *testing.T) {
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
		defer func(r *Raft) { _ = r.Shutdown().Error() }(r)
	}

	leader := assuranceMultiLeader(nodes, 5*time.Second)
	if leader == nil {
		t.Fatalf("no leader was elected")
	}
	if leader == a {
		if err := a.raft.LeadershipTransferToServer(b.id, b.addr).Error(); err != nil {
			t.Fatalf("leadership transfer to B failed: %v", err)
		}
		if !assuranceMultiWaitNode(b.raft, 5*time.Second) {
			t.Fatalf("B did not become leader after transfer")
		}
		leader = b
	}
	assuranceMultiEmit(assuranceMultiEvent{
		"event":          "assurance.recovsnap.start",
		"leader":         leader.name,
		"configured_ids": assuranceMultiSortedIDs(configuration),
	})

	// Give A a command to apply, then restart it with the flag on.
	if err := leader.raft.Apply([]byte("before-restart"), 2*time.Second).Error(); err != nil {
		t.Fatalf("pre-restart apply failed: %v", err)
	}
	if !assuranceMultiWaitFSMCommand(a, 3*time.Second) {
		t.Fatalf("A's FSM applied no command before the restart")
	}
	if err := a.raft.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown A failed: %v", err)
	}
	_, trans1 := NewInmemTransport(a.addr)
	trans1.Connect(b.addr, b.trans)
	trans1.Connect(c.addr, c.trans)
	b.trans.Connect(a.addr, trans1)
	c.trans.Connect(a.addr, trans1)
	a.trans = trans1

	confA := *a.conf
	confA.RestoreCommittedLogs = true
	fsmA := &MockFSM{}
	restarted, err := NewRaft(&confA, fsmA, a.logs, a.stable, a.snaps, trans1)
	if err != nil {
		t.Fatalf("flag-on restart of A failed: %v", err)
	}
	a.raft = restarted
	a.fsm = fsmA
	defer func() { _ = restarted.Shutdown().Error() }()

	staged, _ := a.logs.GetCommitIndex()
	aLast := assuranceMultiLastIndex(a)
	logConfigIndex, logConfigVoters, logConfigIDs := assuranceMultiLogConfig(a.logs, aLast)
	confs := assuranceMultiConfigurations(restarted)
	assuranceMultiEmit(assuranceMultiEvent{
		"event":                   "assurance.recovsnap.flag_on_restart",
		"node":                    "A",
		"restore_committed_logs":  true,
		"snapshot_index":          0,
		"staged_commit_index":     staged,
		"a_log_last_index":        aLast,
		"log_config_index":        logConfigIndex,
		"log_config_voters":       logConfigVoters,
		"log_config_ids":          logConfigIDs,
		"latest_config_index":     confs.latestIndex,
		"latest_config_voters":    assuranceMultiVoters(confs.latest),
		"latest_config_ids":       assuranceMultiSortedIDs(confs.latest),
		"committed_config_index":  confs.committedIndex,
		"committed_config_voters": assuranceMultiVoters(confs.committed),
	})

	// Commit one more command and wait until A's FSM has applied it: runFSM refuses a
	// snapshot request while its own last applied index is zero, and the replayed range may
	// contain only configuration and no-op entries for a plain FSM.
	if err := leader.raft.Apply([]byte("after-restart"), 2*time.Second).Error(); err != nil {
		t.Fatalf("post-restart apply failed: %v", err)
	}
	if !assuranceMultiWaitFSMCommand(a, 3*time.Second) {
		t.Fatalf("A's FSM applied no command after the restart")
	}

	// A takes a snapshot through the normal path and the harness reads its metadata.
	if err := restarted.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot on A failed: %v", err)
	}
	snaps, err := a.snaps.List()
	if err != nil || len(snaps) == 0 {
		t.Fatalf("no snapshot metadata on A: %v", err)
	}
	meta := snaps[0]
	snapVoters := assuranceMultiVoters(meta.Configuration)
	snapIDs := assuranceMultiSortedIDs(meta.Configuration)
	snapshotMatchesLogConfig := meta.ConfigurationIndex == logConfigIndex &&
		snapVoters == logConfigVoters && snapIDs == logConfigIDs
	assuranceMultiEmit(assuranceMultiEvent{
		"event":                              "assurance.recovsnap.snapshot",
		"node":                               "A",
		"restore_committed_logs":             true,
		"snapshot_index":                     meta.Index,
		"snapshot_config_index":              meta.ConfigurationIndex,
		"snapshot_config_voters":             snapVoters,
		"snapshot_config_ids":                snapIDs,
		"log_config_index":                   logConfigIndex,
		"log_config_voters":                  logConfigVoters,
		"log_config_ids":                     logConfigIDs,
		"snapshot_config_matches_log_config": snapshotMatchesLogConfig,
	})

	// Restart A again, this time with the replay disabled: the configuration now comes from
	// the snapshot the node itself wrote.
	if err := restarted.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown of restarted A failed: %v", err)
	}
	_, trans2 := NewInmemTransport(a.addr)
	trans2.Connect(b.addr, b.trans)
	trans2.Connect(c.addr, c.trans)
	b.trans.Connect(a.addr, trans2)
	c.trans.Connect(a.addr, trans2)
	a.trans = trans2

	confA2 := *a.conf
	confA2.RestoreCommittedLogs = false
	fsmA2 := &MockFSM{}
	restarted2, err := NewRaft(&confA2, fsmA2, a.logs, a.stable, a.snaps, trans2)
	if err != nil {
		t.Fatalf("flag-off restart of A failed: %v", err)
	}
	a.raft = restarted2
	a.fsm = fsmA2
	defer func() { _ = restarted2.Shutdown().Error() }()

	confs2 := assuranceMultiConfigurations(restarted2)
	leaderObserved := assuranceMultiWaitNode(restarted2, 1500*time.Millisecond)
	snapIndex2, _ := restarted2.getLastSnapshot()
	assuranceMultiEmit(assuranceMultiEvent{
		"event":                               "assurance.recovsnap.flag_off_restart",
		"node":                                "A",
		"restore_committed_logs":              false,
		"restored_snapshot_index":             snapIndex2,
		"latest_config_index":                 confs2.latestIndex,
		"latest_config_voters":                assuranceMultiVoters(confs2.latest),
		"latest_config_ids":                   assuranceMultiSortedIDs(confs2.latest),
		"committed_config_index":              confs2.committedIndex,
		"log_config_index":                    logConfigIndex,
		"log_config_voters":                   logConfigVoters,
		"log_config_ids":                      logConfigIDs,
		"leader_observed":                     leaderObserved,
		"final_state":                         restarted2.State().String(),
		"empty_config_after_flag_off_restart": assuranceMultiVoters(confs2.latest) == 0,
	})

	_ = restarted2.Shutdown().Error()
}

// TestAssuranceReplayBlockedMemberAvailability
//
// Sourced question: what does a member that cannot start cost the cluster? A node whose
// startup replay exceeds the FSM channel's capacity never returns from NewRaft, so it
// never participates, and the group runs with one member fewer. This harness builds a
// three-voter cluster whose committed log is far above any snapshot, restarts one member
// with and without the replay, and then stops one more member: with the replay (which
// blocks) the surviving pair cannot commit, without it the surviving pair still can.
func assuranceRunAvailabilityCase(t *testing.T, caseName string, restoreCommittedLogs bool, commands int, maxAppendEntries int) {
	t.Helper()

	a := assuranceMultiNewNode(t, "A")
	b := assuranceMultiNewNode(t, "B")
	c := assuranceMultiNewNode(t, "C")
	nodes := []*assuranceMultiNode{a, b, c}
	configuration := assuranceMultiConfig(nodes)
	for _, n := range nodes {
		n.conf.MaxAppendEntries = maxAppendEntries
		// Keep the whole committed log above the snapshot so the restart has a large replay.
		n.conf.SnapshotThreshold = 1 << 30
		n.conf.SnapshotInterval = time.Hour
	}

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
	}
	leader := assuranceMultiLeader(nodes, 5*time.Second)
	if leader == nil {
		t.Fatalf("no leader was elected")
	}
	for _, n := range nodes {
		if n != leader {
			defer func(r *Raft) { _ = r.Shutdown().Error() }(n.raft)
		}
	}
	defer func(r *Raft) { _ = r.Shutdown().Error() }(leader.raft)

	if leader == a {
		target := b
		if err := a.raft.LeadershipTransferToServer(target.id, target.addr).Error(); err != nil {
			t.Fatalf("leadership transfer away from A failed: %v", err)
		}
		if !assuranceMultiWaitNode(target.raft, 5*time.Second) {
			t.Fatalf("transfer target did not become leader")
		}
		leader = target
	}

	for i := 0; i < commands; i++ {
		if err := leader.raft.Apply([]byte("filler"), 5*time.Second).Error(); err != nil {
			t.Fatalf("filler apply %d failed: %v", i, err)
		}
	}
	staged, _ := a.logs.GetCommitIndex()
	aLast := assuranceMultiLastIndex(a)
	snapA, _ := a.raft.getLastSnapshot()
	a.fsm = &MockFSM{}
	assuranceMultiEmit(assuranceMultiEvent{
		"event":                 "assurance.availability.prefix",
		"case":                  caseName,
		"leader":                leader.name,
		"commands":              commands,
		"max_append_entries":    maxAppendEntries,
		"a_staged_commit_index": staged,
		"a_log_last_index":      aLast,
		"a_snapshot_index":      snapA,
		"replay_batches":        (staged - snapA + uint64(maxAppendEntries) - 1) / uint64(maxAppendEntries),
	})

	// Restart A over its own stores with the case's replay setting.
	if err := a.raft.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown A failed: %v", err)
	}
	_, newTrans := NewInmemTransport(a.addr)
	newTrans.Connect(b.addr, b.trans)
	newTrans.Connect(c.addr, c.trans)
	b.trans.Connect(a.addr, newTrans)
	c.trans.Connect(a.addr, newTrans)
	a.trans = newTrans

	confA := *a.conf
	confA.RestoreCommittedLogs = restoreCommittedLogs
	type restartResult struct {
		raft     *Raft
		err      error
		returned bool
		elapsed  int64
	}
	ch := make(chan restartResult, 1)
	go func() {
		start := time.Now()
		r, err := NewRaft(&confA, a.fsm, a.logs, a.stable, a.snaps, newTrans)
		ch <- restartResult{raft: r, err: err, returned: true, elapsed: time.Since(start).Milliseconds()}
	}()
	const waitMS = 8000
	var res restartResult
	select {
	case res = <-ch:
	case <-time.After(waitMS * time.Millisecond):
	}
	excerpt, mentions := "", 0
	if !res.returned {
		buf := make([]byte, 1<<20)
		n := runtime.Stack(buf, true)
		excerpt, mentions = assuranceMultiStackExcerpt(string(buf[:n]), "restoreFromCommittedLogs")
	}
	assuranceMultiEmit(assuranceMultiEvent{
		"event":                  "assurance.availability.restart." + caseName,
		"case":                   caseName,
		"node":                   "A",
		"restore_committed_logs": restoreCommittedLogs,
		"max_append_entries":     maxAppendEntries,
		"replay_entries":         staged,
		"new_raft_returned":      res.returned,
		"elapsed_ms":             res.elapsed,
		"wait_ms":                waitMS,
		"stack_mentions":         mentions,
	})
	if res.returned && res.raft != nil {
		defer func() { _ = res.raft.Shutdown().Error() }()
	}

	// With two members live the group should still commit.
	commitWhileTwoLive := leader.raft.Apply([]byte("while-two-live"), 3*time.Second).Error()

	// Stop the member that is neither the leader nor A: the surviving pair is {leader, A}
	// when A is running, and {leader} when A never started.
	stopped := b
	if leader == b {
		stopped = c
	}
	if stopped == a {
		t.Fatalf("refusing to stop the restarted node")
	}
	stopErr := stopped.raft.Shutdown().Error()
	commitAfterStop := leader.raft.Apply([]byte("after-stop"), 3*time.Second).Error()

	outcome := assuranceMultiEvent{
		"event":                    "assurance.availability.outcome." + caseName,
		"case":                     caseName,
		"node":                     "A",
		"restore_committed_logs":   restoreCommittedLogs,
		"a_new_raft_returned":      res.returned,
		"stopped_node":             stopped.name,
		"stop_error":               fmt.Sprint(stopErr),
		"commit_while_two_live_ok": commitWhileTwoLive == nil,
		"commit_after_stop_ok":     commitAfterStop == nil,
		"commit_after_stop_error":  fmt.Sprint(commitAfterStop),
		"stack_mentions_on_block":  mentions,
		"blocked_stack_excerpt":    excerpt,
	}
	assuranceMultiEmit(outcome)
	if res.returned && res.raft != nil {
		_ = res.raft.Shutdown().Error()
	}
}

func TestAssuranceReplayBlockedMemberAvailability(t *testing.T) {
	const commands = 3000
	const maxAppendEntries = 16 // bound: 128 * 16 = 2048 replayed entries
	assuranceRunAvailabilityCase(t, "replay_on", true, commands, maxAppendEntries)
	assuranceRunAvailabilityCase(t, "replay_off", false, commands, maxAppendEntries)
	// Same flag-on case at the library's default batch size, where the bound is 128 * 64 = 8192
	// replayed entries: the consequence should not depend on the smaller batch size above.
	assuranceRunAvailabilityCase(t, "replay_on_default_batch", true, 9000, 64)
}

// TestAssuranceRecoveredVoterAuthorityAttempt
//
// Sourced question: in a multi-node group, does a voter that recovers without a
// configuration still attempt to acquire authority when it is needed? A node whose
// tracked configuration is empty refuses to start an election at all, so it is a voter
// that can never become a candidate; the same node with the same log and the replay
// disabled recovers its configuration and does attempt one.
func assuranceRunAuthorityCase(t *testing.T, caseName string, restoreCommittedLogs bool) {
	t.Helper()

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
	}
	leader := assuranceMultiLeader(nodes, 5*time.Second)
	if leader == nil {
		t.Fatalf("no leader was elected")
	}
	for i := 0; i < 3; i++ {
		if err := leader.raft.Apply([]byte("filler"), 3*time.Second).Error(); err != nil {
			t.Fatalf("filler apply %d failed: %v", i, err)
		}
	}
	// The case needs A's persisted commit index to be non-zero, otherwise the startup scan
	// runs from index 1, processes the configuration entry and A recovers a configuration;
	// keep committing until A's store reports one.
	staged, _ := a.logs.GetCommitIndex()
	extra := 0
	for staged == 0 && extra < 20 {
		if err := leader.raft.Apply([]byte("premise-filler"), 3*time.Second).Error(); err != nil {
			t.Fatalf("premise filler apply %d failed: %v", extra, err)
		}
		extra++
		time.Sleep(10 * time.Millisecond)
		staged, _ = a.logs.GetCommitIndex()
	}
	if staged == 0 {
		t.Fatalf("A's persisted commit index never advanced above zero")
	}
	if err := a.raft.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown A failed: %v", err)
	}

	_, newTrans := NewInmemTransport(a.addr)
	newTrans.Connect(b.addr, b.trans)
	newTrans.Connect(c.addr, c.trans)
	b.trans.Connect(a.addr, newTrans)
	c.trans.Connect(a.addr, newTrans)
	a.trans = newTrans

	confA := *a.conf
	confA.RestoreCommittedLogs = restoreCommittedLogs
	restartedFSM := &MockFSM{}
	restarted, err := NewRaft(&confA, restartedFSM, a.logs, a.stable, a.snaps, newTrans)
	if err != nil {
		t.Fatalf("restart of A failed: %v", err)
	}
	a.raft = restarted
	a.fsm = restartedFSM
	defer func() { _ = restarted.Shutdown().Error() }()

	confs := assuranceMultiConfigurations(restarted)
	assuranceMultiEmit(assuranceMultiEvent{
		"event":                  "assurance.authority.restart." + caseName,
		"case":                   caseName,
		"node":                   "A",
		"restore_committed_logs": restoreCommittedLogs,
		"staged_commit_index":    staged,
		"premise_filler_applies": extra,
		"latest_config_index":    confs.latestIndex,
		"latest_config_voters":   assuranceMultiVoters(confs.latest),
		"latest_config_ids":      assuranceMultiSortedIDs(confs.latest),
	})

	// Take away every other voter so that A is the only member left.
	if err := b.raft.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown B failed: %v", err)
	}
	if err := c.raft.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown C failed: %v", err)
	}

	// Sample the states the sole surviving voter passes through.
	seen := map[string]int{}
	deadline := time.Now().Add(1500 * time.Millisecond)
	for time.Now().Before(deadline) {
		seen[restarted.State().String()]++
		time.Sleep(5 * time.Millisecond)
	}
	_, _ = fmt.Sscanf("", "")
	samples := 0
	for _, n := range seen {
		samples += n
	}
	assuranceMultiEmit(assuranceMultiEvent{
		"event":                   "assurance.authority.attempt." + caseName,
		"case":                    caseName,
		"node":                    "A",
		"restore_committed_logs":  restoreCommittedLogs,
		"samples":                 samples,
		"follower_samples":        seen["Follower"],
		"candidate_samples":       seen["Candidate"],
		"leader_samples":          seen["Leader"],
		"attempted_candidacy":     seen["Candidate"] > 0,
		"observed_snapshot_index": func() uint64 { i, _ := restarted.getLastSnapshot(); return i }(),
		"final_state":             restarted.State().String(),
	})
}

func TestAssuranceRecoveredVoterAuthorityAttempt(t *testing.T) {
	assuranceRunAuthorityCase(t, "empty_config", true)
	assuranceRunAuthorityCase(t, "recovered_config", false)
}

// TestAssuranceEmptyConfigVoterStillVotes
//
// Sourced question: does a voter that recovers without a configuration still support a
// healthy peer's candidacy, even though it never becomes a candidate itself? Vote
// admission checks membership only when the tracked configuration is non-empty, so the
// defective node may still grant a vote; this harness puts a two-voter group in exactly
// that position and observes whether the healthy peer can be elected with its vote.
func TestAssuranceEmptyConfigVoterStillVotes(t *testing.T) {
	a := assuranceMultiNewNode(t, "A")
	b := assuranceMultiNewNode(t, "B")
	nodes := []*assuranceMultiNode{a, b}
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
	}
	leader := assuranceMultiLeader(nodes, 5*time.Second)
	if leader == nil {
		t.Fatalf("no leader was elected")
	}
	if leader != b {
		if err := leader.raft.LeadershipTransferToServer(b.id, b.addr).Error(); err != nil {
			t.Fatalf("leadership transfer to B failed: %v", err)
		}
		if !assuranceMultiWaitNode(b.raft, 5*time.Second) {
			t.Fatalf("B did not become leader after transfer")
		}
	}

	for i := 0; i < 3; i++ {
		if err := b.raft.Apply([]byte("filler"), 3*time.Second).Error(); err != nil {
			t.Fatalf("filler apply %d failed: %v", i, err)
		}
	}
	staged, _ := a.logs.GetCommitIndex()
	extra := 0
	for staged == 0 && extra < 20 {
		if err := b.raft.Apply([]byte("premise-filler"), 3*time.Second).Error(); err != nil {
			t.Fatalf("premise filler apply %d failed: %v", extra, err)
		}
		extra++
		time.Sleep(10 * time.Millisecond)
		staged, _ = a.logs.GetCommitIndex()
	}
	if staged == 0 {
		t.Fatalf("A's persisted commit index never advanced above zero")
	}

	// Restart A with the replay enabled: with a non-zero persisted commit index its startup
	// scan is skipped and it tracks no configuration at all.
	if err := a.raft.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown A failed: %v", err)
	}
	_, transA := NewInmemTransport(a.addr)
	transA.Connect(b.addr, b.trans)
	b.trans.Connect(a.addr, transA)
	a.trans = transA
	confA := *a.conf
	confA.RestoreCommittedLogs = true
	fsmA := &MockFSM{}
	restartedA, err := NewRaft(&confA, fsmA, a.logs, a.stable, a.snaps, transA)
	if err != nil {
		t.Fatalf("restart of A failed: %v", err)
	}
	a.raft = restartedA
	a.fsm = fsmA
	defer func() { _ = restartedA.Shutdown().Error() }()
	confsA := assuranceMultiConfigurations(restartedA)

	assuranceMultiEmit(assuranceMultiEvent{
		"event":                  "assurance.vote.restart",
		"node":                   "A",
		"restore_committed_logs": true,
		"staged_commit_index":    staged,
		"premise_filler_applies": extra,
		"latest_config_index":    confsA.latestIndex,
		"latest_config_voters":   assuranceMultiVoters(confsA.latest),
		"group_voters":           len(configuration.Servers),
	})

	// Restart B as well, so that it must campaign and can only win with A's vote.
	if err := b.raft.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown B failed: %v", err)
	}
	_, transB := NewInmemTransport(b.addr)
	transB.Connect(a.addr, transA)
	transA.Connect(b.addr, transB)
	b.trans = transB
	confB := *b.conf
	confB.RestoreCommittedLogs = false
	fsmB := &MockFSM{}
	restartedB, err := NewRaft(&confB, fsmB, b.logs, b.stable, b.snaps, transB)
	if err != nil {
		t.Fatalf("restart of B failed: %v", err)
	}
	b.raft = restartedB
	b.fsm = fsmB
	defer func() { _ = restartedB.Shutdown().Error() }()

	// Sample A's states while B campaigns.
	becameLeader := false
	seen := map[string]int{}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		seen[restartedA.State().String()]++
		if restartedB.State() == Leader {
			becameLeader = true
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	assuranceMultiEmit(assuranceMultiEvent{
		"event":                  "assurance.vote.empty_config",
		"node":                   "A",
		"restore_committed_logs": true,
		"staged_commit_index":    staged,
		"premise_filler_applies": extra,
		"a_latest_config_index":  confsA.latestIndex,
		"a_latest_config_voters": assuranceMultiVoters(confsA.latest),
		"b_became_leader":        becameLeader,
		"b_final_state":          restartedB.State().String(),
		"a_candidate_samples":    seen["Candidate"],
		"a_follower_samples":     seen["Follower"],
		"a_leader_samples":       seen["Leader"],
	})
}
