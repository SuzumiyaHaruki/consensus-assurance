// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package raft

// Audited-run harness. It drives the unmodified library through its own public
// API plus the package's in-memory test facilities, and reports what it
// observes as CA_EVENT JSON lines on stdout. It does not assert the outcome
// under investigation; it records observations.

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

const assuranceEventPrefix = "CA_EVENT "

func assuranceEmit(kind string, kv map[string]interface{}) {
	kv["event"] = kind
	b, err := json.Marshal(kv)
	if err != nil {
		fmt.Printf("%s{\"event\":\"marshal_error\",\"kind\":%q}\n", assuranceEventPrefix, kind)
		return
	}
	fmt.Println(assuranceEventPrefix + string(b))
}

func assuranceErrString(err error) interface{} {
	if err == nil {
		return nil
	}
	return err.Error()
}

func assuranceWaitFor(cond func() bool, timeout time.Duration) bool {
	limit := time.Now().Add(timeout)
	for {
		if cond() {
			return true
		}
		if time.Now().After(limit) {
			return cond()
		}
		time.Sleep(2 * time.Millisecond)
	}
}

func assuranceNodes(rafts []*Raft) map[string]interface{} {
	out := make(map[string]interface{}, len(rafts))
	for _, r := range rafts {
		out[string(r.localID)] = map[string]interface{}{
			"state": r.State().String(),
			"term":  r.CurrentTerm(),
		}
	}
	return out
}

func assuranceNodeList(rafts []*Raft) []string {
	out := make([]string, 0, len(rafts))
	for _, r := range rafts {
		out = append(out, string(r.localID))
	}
	return out
}

func assuranceConfigServers(c Configuration) []map[string]interface{} {
	out := make([]map[string]interface{}, 0, len(c.Servers))
	for _, s := range c.Servers {
		out = append(out, map[string]interface{}{
			"id":       string(s.ID),
			"suffrage": s.Suffrage.String(),
		})
	}
	return out
}

// assuranceObserver records vote campaigns and leadership transitions observed
// through the library's observer mechanism for the duration of a scenario.
type assuranceObserver struct {
	start    time.Time
	mu       sync.Mutex
	votes    []map[string]interface{}
	states   []map[string]interface{}
	stopOnce sync.Once
	stopCh   chan struct{}
}

func assuranceStartObserver(chans ...chan Observation) *assuranceObserver {
	o := &assuranceObserver{start: time.Now(), stopCh: make(chan struct{})}
	for _, ch := range chans {
		go func(ch chan Observation) {
			for {
				select {
				case <-o.stopCh:
					return
				case obs := <-ch:
					o.record(obs)
				}
			}
		}(ch)
	}
	return o
}

func (o *assuranceObserver) record(obs Observation) {
	switch d := obs.Data.(type) {
	case *RequestVoteRequest:
		o.recordVote(obs.Raft, *d)
	case RequestVoteRequest:
		o.recordVote(obs.Raft, d)
	case RaftState:
		o.mu.Lock()
		o.states = append(o.states, map[string]interface{}{
			"t_ms":  float64(time.Since(o.start).Nanoseconds()) / 1e6,
			"node":  string(obs.Raft.localID),
			"state": d.String(),
		})
		o.mu.Unlock()
	}
}

func (o *assuranceObserver) recordVote(r *Raft, d RequestVoteRequest) {
	candidate := r.trans.DecodePeer(d.RPCHeader.Addr)
	o.mu.Lock()
	o.votes = append(o.votes, map[string]interface{}{
		"t_ms":             float64(time.Since(o.start).Nanoseconds()) / 1e6,
		"received_by":      string(r.localID),
		"candidate_id":     string(d.RPCHeader.ID),
		"candidate_addr":   string(candidate),
		"term":             d.Term,
		"last_log_index":   d.LastLogIndex,
		"last_log_term":    d.LastLogTerm,
		"transfer_flagged": d.LeadershipTransfer,
	})
	o.mu.Unlock()
}

func (o *assuranceObserver) stop() ([]map[string]interface{}, []map[string]interface{}) {
	o.stopOnce.Do(func() { close(o.stopCh) })
	time.Sleep(10 * time.Millisecond)
	o.mu.Lock()
	defer o.mu.Unlock()
	votes := o.votes
	states := o.states
	o.votes = nil
	o.states = nil
	return votes, states
}

// assuranceSampleStates polls every node for a window and reports timestamped
// state transitions. Sampling can miss intermediate transitions; the reported
// sequence is exactly what the sampler saw.
func assuranceSampleStates(rafts []*Raft, window time.Duration) []map[string]interface{} {
	var log []map[string]interface{}
	last := make(map[string]string, len(rafts))
	start := time.Now()
	record := func() {
		for _, r := range rafts {
			id := string(r.localID)
			st := r.State().String()
			if last[id] != st {
				last[id] = st
				log = append(log, map[string]interface{}{
					"t_ms":  float64(time.Since(start).Nanoseconds()) / 1e6,
					"node":  id,
					"state": st,
					"term":  r.CurrentTerm(),
				})
			}
		}
	}
	record()
	limit := time.Now().Add(window)
	for time.Now().Before(limit) {
		time.Sleep(2 * time.Millisecond)
		record()
	}
	return log
}

func assuranceLeaders(rafts []*Raft) []string {
	var out []string
	for _, r := range rafts {
		if r.State() == Leader {
			out = append(out, string(r.localID))
		}
	}
	return out
}

// assuranceFaultStore wraps the library's in-memory store with a legal
// LogStore that can return an error from StoreLogs on demand. StoreLogs is
// allowed to fail by the interface; the wrapper keeps counting attempts so the
// receipt can show whether the library even reached the store again.
type assuranceFaultStore struct {
	*InmemStore
	remaining int32 // StoreLogs calls still to fail (atomic)
	attempts  int32 // StoreLogs calls seen (atomic)
	delivered int32 // StoreLogs calls that reached the store (atomic)
}

func (s *assuranceFaultStore) StoreLogs(logs []*Log) error {
	atomic.AddInt32(&s.attempts, 1)
	if atomic.LoadInt32(&s.remaining) > 0 {
		atomic.AddInt32(&s.remaining, -1)
		return fmt.Errorf("assurance: injected StoreLogs failure")
	}
	atomic.AddInt32(&s.delivered, 1)
	return s.InmemStore.StoreLogs(logs)
}

// assuranceNode is a hand-built raft instance using the library's own
// in-memory transport, store and snapshot store, so that one node can be given
// the fault wrapper.
type assuranceNode struct {
	id    ServerID
	addr  ServerAddress
	store *assuranceFaultStore
	fsm   *MockFSM
	trans *InmemTransport
	snaps *InmemSnapshotStore
	raft  *Raft
}

// assuranceTightCompaction makes snapshots cheap and compaction aggressive, so
// that a leader can be forced to stop serving log entries and send a snapshot
// instead. It is set by the subtest that needs it and reset afterwards.
var assuranceTightCompaction bool

func assuranceBuildNodes(t *testing.T, n int) []*assuranceNode {
	t.Helper()
	nodes := make([]*assuranceNode, n)
	var configuration Configuration
	for i := 0; i < n; i++ {
		addr, trans := NewInmemTransport("")
		nodes[i] = &assuranceNode{
			id:    ServerID("server-" + string(addr)),
			addr:  addr,
			store: &assuranceFaultStore{InmemStore: NewInmemStore()},
			fsm:   &MockFSM{},
			trans: trans,
			snaps: NewInmemSnapshotStore(),
		}
		configuration.Servers = append(configuration.Servers, Server{
			Suffrage: Voter,
			ID:       nodes[i].id,
			Address:  addr,
		})
	}
	assuranceWire(nodes, false)

	conf := inmemConfig(t)
	if assuranceTightCompaction {
		conf.SnapshotThreshold = 1
		conf.TrailingLogs = 0
		conf.SnapshotInterval = time.Hour
	}
	for i := range nodes {
		peerConf := *conf
		peerConf.LocalID = nodes[i].id
		if err := BootstrapCluster(&peerConf, nodes[i].store, nodes[i].store, nodes[i].snaps, nodes[i].trans, configuration); err != nil {
			t.Fatalf("bootstrap: %v", err)
		}
		r, err := NewRaft(&peerConf, nodes[i].fsm, nodes[i].store, nodes[i].store, nodes[i].snaps, nodes[i].trans)
		if err != nil {
			t.Fatalf("newraft: %v", err)
		}
		nodes[i].raft = r
	}
	return nodes
}

// assuranceWire connects every pair, or disconnects the target from every other
// node in both directions when isolate is true.
func assuranceWire(nodes []*assuranceNode, isolate bool) {
	for i := range nodes {
		for j := range nodes {
			if i == j {
				continue
			}
			if isolate && (nodes[i].id == nodes[0].id || nodes[j].id == nodes[0].id) {
				nodes[i].trans.Disconnect(nodes[j].addr)
				continue
			}
			nodes[i].trans.Connect(nodes[j].addr, nodes[j].trans)
		}
	}
}

func (n *assuranceNode) close() {
	if n.raft != nil {
		n.raft.Shutdown().Error()
	}
	if n.trans != nil {
		n.trans.Close()
	}
}

func assuranceWaitLeader(nodes []*assuranceNode, timeout time.Duration) *assuranceNode {
	limit := time.Now().Add(timeout)
	for time.Now().Before(limit) {
		var found *assuranceNode
		count := 0
		for _, n := range nodes {
			if n.raft.State() == Leader {
				count++
				found = n
			}
		}
		if count == 1 {
			time.Sleep(60 * time.Millisecond)
			if found.raft.State() == Leader {
				return found
			}
		}
		time.Sleep(5 * time.Millisecond)
	}
	return nil
}

func assuranceExcept(nodes []*assuranceNode, skip *assuranceNode) []*assuranceNode {
	out := make([]*assuranceNode, 0, len(nodes)-1)
	for _, n := range nodes {
		if n != skip {
			out = append(out, n)
		}
	}
	return out
}

// assuranceStoreProbe reports what the node's cached certificate says and what
// the wrapped store actually holds.
func assuranceStoreProbe(n *assuranceNode) map[string]interface{} {
	certIdx, certTerm := n.raft.getLastEntry()
	var probe Log
	getErr := n.store.GetLog(certIdx, &probe)
	first, _ := n.store.FirstIndex()
	last, _ := n.store.LastIndex()
	out := map[string]interface{}{
		"node":             string(n.id),
		"state":            n.raft.State().String(),
		"term":             n.raft.CurrentTerm(),
		"cert_last_index":  certIdx,
		"cert_last_term":   certTerm,
		"reported_last":    n.raft.LastIndex(),
		"commit_index":     n.raft.CommitIndex(),
		"applied_index":    n.raft.AppliedIndex(),
		"store_first":      first,
		"store_last":       last,
		"store_attempts":   atomic.LoadInt32(&n.store.attempts),
		"store_delivered":  atomic.LoadInt32(&n.store.delivered),
		"cert_entry_error": assuranceErrString(getErr),
	}
	if getErr == nil {
		out["cert_entry_term"] = probe.Term
	}
	return out
}

// TestAssuranceTruncationStoreFailure runs the same legal single-cluster
// history twice: once with a healthy store (control) and once with a store that
// returns an error for the StoreLogs call that follows a conflicting-suffix
// deletion. Both cases record the node's certificate, the store contents, the
// indexes and the retry behaviour of the leader afterwards.
func TestAssuranceTruncationStoreFailure(t *testing.T) {
	cases := []struct {
		mode  string
		n     int
		steps int
	}{
		{"control", 3, 1},
		{"injected_store_error", 3, 1},
		{"injected_store_error_then_restart", 3, 1},
		{"injected_store_error_then_snapshot", 3, 0},
		{"control_five_voters", 5, 2},
		{"injected_store_error_five_voters", 5, 2},
	}
	for _, c := range cases {
		c := c
		t.Run(c.mode, func(t *testing.T) {
			assuranceTightCompaction = c.mode == "injected_store_error_then_snapshot"
			defer func() { assuranceTightCompaction = false }()
			assuranceRunTruncationCase(t, c.mode, c.n, c.steps)
		})
	}
}

// restart rebuilds a node on the same durable state, which is what the library
// itself does at startup: NewRaft reads the last log index from the log store
// and rescans configuration entries. Shutdown closes the transport (it
// implements WithClose), so the restart takes a fresh transport at the same
// address and the peers are rewired to it, as a real process restart would.
func (n *assuranceNode) restart(t *testing.T, peers []*assuranceNode) {
	t.Helper()
	n.raft.Shutdown().Error()
	addr, trans := NewInmemTransport(n.addr)
	n.addr = addr
	n.trans = trans
	for _, p := range peers {
		if p == n {
			continue
		}
		p.trans.Connect(n.addr, trans)
		trans.Connect(p.addr, p.trans)
	}
	conf := inmemConfig(t)
	conf.LocalID = n.id
	r, err := NewRaft(conf, &MockFSM{}, n.store, n.store, n.snaps, n.trans)
	if err != nil {
		t.Fatalf("restart of %s failed: %v", n.id, err)
	}
	n.raft = r
}

func assuranceRunTruncationCase(t *testing.T, mode string, n int, steps int) {
	t.Helper()
	faulted := strings.HasPrefix(mode, "injected_store_error")
	nodes := assuranceBuildNodes(t, n)
	defer func() {
		for _, n := range nodes {
			n.close()
		}
	}()

	diverging := assuranceWaitLeader(nodes, 4*time.Second)
	if diverging == nil {
		t.Fatalf("[%s] no initial leader", mode)
	}
	others := assuranceExcept(nodes, diverging)

	// Put the node now holding leadership first so the wire helper isolates it.
	ordered := append([]*assuranceNode{diverging}, others...)
	assuranceWire(ordered, true)

	// The isolated leader keeps accepting client work into its own log.
	diverging.raft.Apply([]byte("assurance-divergent-1"), 0)
	diverging.raft.Apply([]byte("assurance-divergent-2"), 0)
	wantDivergent := diverging.raft.LastIndex() + 2
	assuranceWaitFor(func() bool { return diverging.raft.LastIndex() >= wantDivergent }, time.Second)

	// The majority elects a new leader and commits different entries.
	l2 := assuranceWaitLeader(others, 4*time.Second)
	if l2 == nil {
		t.Fatalf("[%s] majority did not elect a leader", mode)
	}
	for i := 0; i < 2; i++ {
		f := l2.raft.Apply([]byte(fmt.Sprintf("assurance-replacement-%d", i)), 2*time.Second)
		if err := f.Error(); err != nil {
			t.Fatalf("[%s] majority apply failed: %v", mode, err)
		}
	}

	assuranceEmit("truncation_before_heal", map[string]interface{}{
		"mode":               mode,
		"diverging_id":       string(diverging.id),
		"majority_leader":    string(l2.id),
		"diverging_probe":    assuranceStoreProbe(diverging),
		"majority_leader_st": assuranceStoreProbe(l2),
	})

	if faulted {
		atomic.StoreInt32(&diverging.store.remaining, 1000000)
	}

	// Heal and watch for a bounded window.
	assuranceWire(ordered, false)
	start := time.Now()
	var certIdx []uint64
	var storeLast []uint64
	var attempts []int32
	for time.Now().Before(start.Add(1500 * time.Millisecond)) {
		p := assuranceStoreProbe(diverging)
		certIdx = append(certIdx, p["cert_last_index"].(uint64))
		storeLast = append(storeLast, p["store_last"].(uint64))
		attempts = append(attempts, atomic.LoadInt32(&diverging.store.attempts))
		time.Sleep(25 * time.Millisecond)
	}
	afterHeal := assuranceStoreProbe(diverging)
	currentLeader := assuranceWaitLeader(nodes, time.Second)
	leaderView := map[string]interface{}{"leader": nil}
	if currentLeader != nil {
		leaderView = assuranceStoreProbe(currentLeader)
		leaderView["leader"] = string(currentLeader.id)
	}
	assuranceEmit("truncation_after_heal", map[string]interface{}{
		"mode":               mode,
		"diverging_probe":    afterHeal,
		"leader_probe":       leaderView,
		"cert_index_samples": certIdx,
		"store_last_samples": storeLast,
		"store_attempts":     attempts,
		"window_ms":          1500,
	})

	// Remove the fault and give the library a further fair window to recover.
	atomic.StoreInt32(&diverging.store.remaining, 0)
	time.Sleep(1200 * time.Millisecond)
	assuranceEmit("truncation_after_disarm", map[string]interface{}{
		"mode":            mode,
		"diverging_probe": assuranceStoreProbe(diverging),
	})

	// Restart-repair boundary: only the mode that asks for it restarts the node
	// on the same durable state, then watches whether the node converges.
	if mode == "injected_store_error_then_snapshot" {
		leaderForSnap := assuranceWaitLeader(nodes, time.Second)
		if leaderForSnap == nil {
			assuranceEmit("truncation_after_snapshot", map[string]interface{}{
				"mode":   mode,
				"reason": "no leader before the snapshot phase",
			})
			return
		}
		beforeFirst, _ := diverging.store.FirstIndex()
		snapErr := make(chan error, 1)
		go func() { snapErr <- leaderForSnap.raft.Snapshot().Error() }()
		var serr error
		select {
		case serr = <-snapErr:
		case <-time.After(3 * time.Second):
		}
		afterFirst, _ := diverging.store.FirstIndex()
		// Produce a new entry after the snapshot install, so the observation shows
		// whether replication resumes rather than only that state is consistent.
		leaderForSnap.raft.Apply([]byte("assurance-after-snapshot"), 0)
		startSnap := time.Now()
		var certs, stores, commits, firsts []interface{}
		for i := 0; i < 20; i++ {
			certIdx, _ := diverging.raft.getLastEntry()
			last, _ := diverging.store.LastIndex()
			first, _ := diverging.store.FirstIndex()
			certs = append(certs, certIdx)
			stores = append(stores, last)
			commits = append(commits, diverging.raft.CommitIndex())
			firsts = append(firsts, first)
			time.Sleep(200 * time.Millisecond)
		}
		assuranceEmit("truncation_after_snapshot", map[string]interface{}{
			"mode":                mode,
			"snapshot_error":      assuranceErrString(serr),
			"store_first_before":  beforeFirst,
			"store_first_after":   afterFirst,
			"cert_samples":        certs,
			"store_last_samples":  stores,
			"store_first_samples": firsts,
			"commit_samples":      commits,
			"diverging_probe":     assuranceStoreProbe(diverging),
			"leader_probe":        assuranceStoreProbe(leaderForSnap),
			"elapsed_ms":          float64(time.Since(startSnap).Nanoseconds()) / 1e6,
		})
		return
	}

	if mode == "injected_store_error_then_restart" {
		diverging.restart(t, nodes)
		startRestart := time.Now()
		var certs, stores, commits []interface{}
		converged := assuranceWaitFor(func() bool {
			last, err := diverging.store.LastIndex()
			certIdx, certTerm := diverging.raft.getLastEntry()
			probe := assuranceStoreProbe(diverging)
			_ = probe
			return err == nil && certIdx == last && certTerm > 0
		}, 4*time.Second)
		for i := 0; i < 20; i++ {
			certIdx, _ := diverging.raft.getLastEntry()
			last, _ := diverging.store.LastIndex()
			certs = append(certs, certIdx)
			stores = append(stores, last)
			commits = append(commits, diverging.raft.CommitIndex())
			time.Sleep(200 * time.Millisecond)
		}
		assuranceEmit("truncation_after_restart", map[string]interface{}{
			"mode":               mode,
			"converged":          converged,
			"cert_samples":       certs,
			"store_last_samples": stores,
			"commit_samples":     commits,
			"diverging_probe":    assuranceStoreProbe(diverging),
			"elapsed_ms":         float64(time.Since(startRestart).Nanoseconds()) / 1e6,
		})
		return
	}

	// Escalation phase: a three-voter cluster is expected to keep making
	// progress with one voter down. Remove the remaining healthy voter and see
	// whether the leader can still commit a new entry, in this mode and in the
	// control alike.
	leaderNow := assuranceWaitLeader(nodes, time.Second)
	if leaderNow == nil {
		assuranceEmit("peer_loss_after_wedge", map[string]interface{}{
			"mode":   mode,
			"reason": "no leader before the peer-loss phase",
		})
		return
	}
	isolated := map[ServerID]bool{}
	for step := 0; step < steps; step++ {
		var healthy *assuranceNode
		for _, n := range nodes {
			if n != diverging && n != leaderNow && !isolated[n.id] {
				healthy = n
				break
			}
		}
		if healthy == nil {
			assuranceEmit("peer_loss_after_wedge", map[string]interface{}{
				"mode":   mode,
				"reason": "no further voter available to remove",
				"step":   step,
			})
			return
		}
		isolated[healthy.id] = true
		for _, n := range nodes {
			if n == healthy {
				continue
			}
			healthy.trans.Disconnect(n.addr)
			n.trans.Disconnect(healthy.addr)
		}
		assuranceRunPeerLossStep(t, mode, step, nodes, diverging, leaderNow, healthy)
	}
	return
}

// assuranceRunPeerLossStep removes one voter (already isolated by the caller)
// and records whether the leader can still commit a new entry.
func assuranceRunPeerLossStep(t *testing.T, mode string, step int, nodes []*assuranceNode, diverging, leaderNow, healthy *assuranceNode) {
	t.Helper()
	future := leaderNow.raft.Apply([]byte("assurance-after-peer-loss"), 0)
	done := make(chan error, 1)
	go func() { done <- future.Error() }()
	commitBefore := leaderNow.raft.CommitIndex()
	applied := uint64(0)
	if f := future.(IndexFuture); f != nil {
		_ = applied
	}
	var commits []uint64
	resolved := false
	var futureErr error
	limit := time.Now().Add(1500 * time.Millisecond)
	for time.Now().Before(limit) {
		select {
		case futureErr = <-done:
			resolved = true
		default:
		}
		commits = append(commits, leaderNow.raft.CommitIndex())
		time.Sleep(25 * time.Millisecond)
	}
	assuranceEmit("peer_loss_after_wedge", map[string]interface{}{
		"mode":               mode,
		"step":               step,
		"voters":             len(nodes),
		"removed_voter":      string(healthy.id),
		"leader":             string(leaderNow.id),
		"leader_state":       leaderNow.raft.State().String(),
		"leader_term":        leaderNow.raft.CurrentTerm(),
		"commit_before":      commitBefore,
		"commit_samples":     commits,
		"apply_future_done":  resolved,
		"apply_future_error": assuranceErrString(futureErr),
		"leader_probe":       assuranceStoreProbe(leaderNow),
		"wedged_node_probe":  assuranceStoreProbe(diverging),
		"state_and_term":     assuranceNodes(assuranceRafts(nodes)),
		"window_ms":          1500,
	})
}

func assuranceRafts(nodes []*assuranceNode) []*Raft {
	out := make([]*Raft, 0, len(nodes))
	for _, n := range nodes {
		out = append(out, n.raft)
	}
	return out
}

// TestAssuranceAddVoterAbsentServer follows the growth sequence the library
// documents (bootstrap one voter, then AddVoter the next server). In one case
// the named server is not running yet and is only started afterwards; in the
// control it is running before the call. Both record the outstanding
// configuration entry, the leader's state, whether a leader exists at all,
// whether a later client write is accepted, and whether the cluster recovers
// once the named server appears.
func TestAssuranceAddVoterAbsentServer(t *testing.T) {
	for _, c := range []struct {
		mode     string
		nonvoter bool
		present  bool
	}{
		{"absent_server", false, false},
		{"control_present_server", false, true},
		{"absent_server_nonvoter", true, false},
		{"present_server_nonvoter", true, true},
	} {
		c := c
		t.Run(c.mode, func(t *testing.T) {
			assuranceRunGrowthCase(t, c.mode, c.nonvoter, c.present)
		})
	}
}

func assuranceRunGrowthCase(t *testing.T, mode string, nonvoter bool, present bool) {
	t.Helper()
	c := MakeCluster(1, t, inmemConfig(t))
	defer c.Close()

	leader := c.Leader()
	leaderAddr := leader.localAddr
	lastBefore := leader.LastIndex()
	configIndex := lastBefore + 1

	// The future server's identity and transport exist, but nothing is wired
	// and no raft runs on it until the recovery step.
	bAddr, bTrans := NewInmemTransport("")
	bID := ServerID("server-" + string(bAddr))
	bStore := NewInmemStore()
	bSnaps := NewInmemSnapshotStore()
	bConf := inmemConfig(t)
	bConf.LocalID = bID
	var bRaft *Raft
	defer func() {
		if bRaft != nil {
			bRaft.Shutdown().Error()
		}
		bTrans.Close()
	}()
	startB := func() {
		if bRaft != nil {
			return
		}
		c.trans[0].Connect(bAddr, bTrans)
		bTrans.Connect(leaderAddr, c.trans[0])
		r, err := NewRaft(bConf, &MockFSM{}, bStore, bStore, bSnaps, bTrans)
		if err != nil {
			t.Fatalf("[%s] newraft for the named server: %v", mode, err)
		}
		bRaft = r
	}
	if present {
		startB()
	}

	assuranceEmit("growth_before", map[string]interface{}{
		"mode":             mode,
		"nonvoter":         nonvoter,
		"leader":           string(leader.localID),
		"state":            leader.State().String(),
		"term":             leader.CurrentTerm(),
		"commit_index":     leader.CommitIndex(),
		"last_index":       lastBefore,
		"config_servers":   assuranceConfigServers(leader.GetConfiguration().Configuration()),
		"named_server":     string(bID),
		"named_server_up":  bRaft != nil,
		"config_entry_idx": configIndex,
	})

	var future IndexFuture
	if nonvoter {
		future = leader.AddNonvoter(bID, bAddr, 0, time.Second)
	} else {
		future = leader.AddVoter(bID, bAddr, 0, time.Second)
	}
	done := make(chan error, 1)
	go func() { done <- future.Error() }()

	var states, terms, commits, lasts []interface{}
	leadersSeen := 0
	resolved := false
	var futureErr error
	start := time.Now()
	limit := start.Add(1500 * time.Millisecond)
	for time.Now().Before(limit) {
		select {
		case futureErr = <-done:
			resolved = true
		default:
		}
		states = append(states, leader.State().String())
		terms = append(terms, leader.CurrentTerm())
		commits = append(commits, leader.CommitIndex())
		lasts = append(lasts, leader.LastIndex())
		if leader.State() == Leader {
			leadersSeen++
		}
		time.Sleep(25 * time.Millisecond)
	}

	assuranceEmit("growth_window", map[string]interface{}{
		"mode":                   mode,
		"leader_state_samples":   states,
		"term_samples":           terms,
		"commit_samples":         commits,
		"last_index_samples":     lasts,
		"leader_state_seen_ct":   leadersSeen,
		"future_resolved":        resolved,
		"future_error":           assuranceErrString(futureErr),
		"final_state":            leader.State().String(),
		"final_term":             leader.CurrentTerm(),
		"final_commit":           leader.CommitIndex(),
		"final_last_index":       leader.LastIndex(),
		"config_entry_committed": leader.CommitIndex() >= configIndex,
		"window_ms":              1500,
	})

	// Can a client still write? Use a bounded attempt so the harness cannot hang.
	writeErr := make(chan error, 1)
	go func() { writeErr <- leader.Apply([]byte("assurance-growth-write"), time.Second).Error() }()
	var werr error
	select {
	case werr = <-writeErr:
	case <-time.After(1200 * time.Millisecond):
	}
	assuranceEmit("growth_write_attempt", map[string]interface{}{
		"mode":        mode,
		"nonvoter":    nonvoter,
		"write_error": assuranceErrString(werr),
		"commit_now":  leader.CommitIndex(),
	})

	// Can the API repair the cluster without the named server? Both a removal of
	// the absent server and a non-voter replacement are legal calls an operator
	// would try; each is bounded here so the harness cannot hang.
	repair := func(call func() Future) interface{} {
		ch := make(chan error, 1)
		go func() { ch <- call().Error() }()
		select {
		case err := <-ch:
			return assuranceErrString(err)
		case <-time.After(1200 * time.Millisecond):
			return "no response within 1200ms"
		}
	}
	removeErr := repair(func() Future { return leader.RemoveServer(bID, 0, time.Second) })
	addNonvoterErr := repair(func() Future { return leader.AddNonvoter(bID, bAddr, 0, time.Second) })

	// A longer window on the unrepaired state: does any leader appear, and does
	// anything else change while the named server stays away?
	var states2, terms2, commits2 []interface{}
	windowStart := time.Now()
	for time.Now().Before(windowStart.Add(3000 * time.Millisecond)) {
		states2 = append(states2, leader.State().String())
		terms2 = append(terms2, leader.CurrentTerm())
		commits2 = append(commits2, leader.CommitIndex())
		time.Sleep(50 * time.Millisecond)
	}
	assuranceEmit("growth_api_repair_attempt", map[string]interface{}{
		"mode":                      mode,
		"remove_server_error":       removeErr,
		"add_nonvoter_error":        addNonvoterErr,
		"unrepaired_state_samples":  states2,
		"unrepaired_term_samples":   terms2,
		"unrepaired_commit_samples": commits2,
		"unrepaired_window_ms":      3000,
		"final_state":               leader.State().String(),
		"final_term":                leader.CurrentTerm(),
		"final_commit":              leader.CommitIndex(),
	})

	// Bring the named server up and see whether the cluster resumes.
	if !present {
		startB()
	}
	recovered := assuranceWaitFor(func() bool {
		return leader.CommitIndex() >= configIndex && (leader.State() == Leader || (bRaft != nil && bRaft.State() == Leader))
	}, 4*time.Second)
	leadersNow := map[string]interface{}{
		"original": leader.State().String(),
		"named":    "absent",
	}
	if bRaft != nil {
		leadersNow["named"] = bRaft.State().String()
	}
	assuranceEmit("growth_recovery", map[string]interface{}{
		"mode":             mode,
		"named_server_up":  bRaft != nil,
		"recovered":        recovered,
		"states":           leadersNow,
		"original_term":    leader.CurrentTerm(),
		"original_commit":  leader.CommitIndex(),
		"original_last":    leader.LastIndex(),
		"config_entry_idx": configIndex,
		"elapsed_ms":       float64(time.Since(start).Nanoseconds()) / 1e6,
	})
}

// TestAssuranceLeadershipTransferVoterControl transfers leadership to a voter
// in a plain 3-voter cluster: same API call, same library build, same harness.
// It is the positive control for target eligibility.
func TestAssuranceLeadershipTransferVoterControl(t *testing.T) {
	c := MakeCluster(3, t, inmemConfig(t))
	defer c.Close()

	leader := c.Leader()
	var target *Raft
	for _, r := range c.rafts {
		if r != leader {
			target = r
			break
		}
	}
	if target == nil {
		t.Fatalf("no follower available as transfer target")
	}

	obs := assuranceStartObserver(c.observationCh)
	assuranceEmit("control_transfer_before", map[string]interface{}{
		"nodes":          assuranceNodeList(c.rafts),
		"incumbent_id":   string(leader.localID),
		"target_id":      string(target.localID),
		"target_voter":   hasVote(leader.GetConfiguration().Configuration(), target.localID),
		"state_and_term": assuranceNodes(c.rafts),
	})

	start := time.Now()
	err := leader.LeadershipTransferToServer(target.localID, target.localAddr).Error()
	elapsed := time.Since(start)
	became := assuranceWaitFor(func() bool { return target.State() == Leader }, 2*time.Second)
	votes, states := obs.stop()

	assuranceEmit("control_transfer_after", map[string]interface{}{
		"future_error":            assuranceErrString(err),
		"future_elapsed_ms":       float64(elapsed.Nanoseconds()) / 1e6,
		"target_became_leader":    became,
		"incumbent_state":         leader.State().String(),
		"target_state":            target.State().String(),
		"state_and_term":          assuranceNodes(c.rafts),
		"observed_vote_requests":  votes,
		"observed_state_events":   states,
		"observed_state_event_ct": len(states),
		"elapsed_ms_to_leader":    float64(time.Since(start).Nanoseconds()) / 1e6,
	})
}

// TestAssuranceLeadershipTransferToNonvoter transfers leadership to a member
// added with the public AddNonvoter API that has caught up to the leader's log.
// It records the configuration the leader holds, whether the target learned it,
// the vote campaign the target emits, the sampled transitions, the value the
// transfer future returned, and whether a leader exists again afterwards.
func TestAssuranceLeadershipTransferToNonvoter(t *testing.T) {
	c := MakeCluster(3, t, inmemConfig(t))
	defer c.Close()
	c2 := MakeClusterNoBootstrap(1, t, inmemConfig(t))
	c.Merge(c2)
	c.FullyConnect()

	leader := c.Leader()
	nonvoter := c2.rafts[0]

	if err := leader.AddNonvoter(nonvoter.localID, nonvoter.localAddr, 0, 5*time.Second).Error(); err != nil {
		t.Fatalf("AddNonvoter failed: %v", err)
	}

	learned := assuranceWaitFor(func() bool {
		return len(nonvoter.GetConfiguration().Configuration().Servers) == 4
	}, 5*time.Second)

	applied := uint64(0)
	if learned {
		f := leader.Apply([]byte("assurance-nonvoter-transfer-proof"), 2*time.Second)
		if err := f.Error(); err != nil {
			t.Fatalf("apply failed: %v", err)
		}
		applied = f.Index()
	}
	caughtUp := assuranceWaitFor(func() bool {
		return nonvoter.LastIndex() >= applied && nonvoter.CommitIndex() >= applied
	}, 5*time.Second)

	leaderCfg := leader.GetConfiguration().Configuration()
	voters := make([]*Raft, 0, 3)
	for _, r := range c.rafts {
		if hasVote(leaderCfg, r.localID) {
			voters = append(voters, r)
		}
	}

	assuranceEmit("nonvoter_transfer_before", map[string]interface{}{
		"nodes":                       assuranceNodeList(c.rafts),
		"incumbent_id":                string(leader.localID),
		"target_id":                   string(nonvoter.localID),
		"leader_config_servers":       assuranceConfigServers(leaderCfg),
		"target_is_voter_on_leader":   hasVote(leaderCfg, nonvoter.localID),
		"target_in_config_on_leader":  inConfiguration(leaderCfg, nonvoter.localID),
		"target_learned_4_server_cfg": learned,
		"target_last_index":           nonvoter.LastIndex(),
		"target_commit_index":         nonvoter.CommitIndex(),
		"proof_entry_index":           applied,
		"target_caught_up_to_proof":   caughtUp,
		"voters":                      assuranceNodeList(voters),
		"state_and_term":              assuranceNodes(c.rafts),
	})

	obs := assuranceStartObserver(c.observationCh, c2.observationCh)

	start := time.Now()
	err := leader.LeadershipTransferToServer(nonvoter.localID, nonvoter.localAddr).Error()
	elapsed := time.Since(start)

	sampled := assuranceSampleStates(c.rafts, 500*time.Millisecond)
	votes, states := obs.stop()

	assuranceEmit("nonvoter_transfer_after", map[string]interface{}{
		"future_error":            assuranceErrString(err),
		"future_elapsed_ms":       float64(elapsed.Nanoseconds()) / 1e6,
		"target_state":            nonvoter.State().String(),
		"target_term":             nonvoter.CurrentTerm(),
		"incumbent_state":         leader.State().String(),
		"incumbent_term":          leader.CurrentTerm(),
		"leaders_after":           assuranceLeaders(c.rafts),
		"sampled_transitions":     sampled,
		"observed_vote_requests":  votes,
		"observed_state_events":   states,
		"observed_state_event_ct": len(states),
	})

	// Recovery window: does the cluster form a leader again, and after how long?
	recovered := assuranceWaitFor(func() bool { return len(assuranceLeaders(voters)) == 1 }, 3*time.Second)
	assuranceEmit("nonvoter_transfer_recovery", map[string]interface{}{
		"voters_have_one_leader": recovered,
		"leaders":                assuranceLeaders(voters),
		"elapsed_ms_since_call":  float64(time.Since(start).Nanoseconds()) / 1e6,
		"state_and_term":         assuranceNodes(c.rafts),
	})
}
