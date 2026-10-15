// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"sync/atomic"
	"testing"
	"time"
)

// assuranceProbeNode is one real Raft instance in this process, with its own
// store, snapshot store, transport and (optionally) a stalling log store.
type assuranceProbeNode struct {
	id    ServerID
	addr  ServerAddress
	trans *InmemTransport
	slow  *assuranceSlowStore
	raft  *Raft
}

// assuranceSlowStore models a leader whose disk stalls: while armed, StoreLogs
// blocks on the caller's goroutine, which for the leader is the main loop.
type assuranceSlowStore struct {
	LogStore
	armed  *int32
	stalls *int32
	delay  time.Duration
}

func (s *assuranceSlowStore) StoreLogs(logs []*Log) error {
	if atomic.LoadInt32(s.armed) == 1 {
		atomic.AddInt32(s.stalls, 1)
		time.Sleep(s.delay)
	}
	return s.LogStore.StoreLogs(logs)
}

func assuranceProbeConfig(t *testing.T, tag string, localID ServerID) *Config {
	conf := DefaultConfig()
	conf.HeartbeatTimeout = 200 * time.Millisecond
	conf.ElectionTimeout = 200 * time.Millisecond
	conf.LeaderLeaseTimeout = 200 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.LocalID = localID
	conf.Logger = newTestLoggerWithPrefix(t, tag)
	return conf
}

func assuranceNewNode() *assuranceProbeNode {
	addr, trans := NewInmemTransport("")
	return &assuranceProbeNode{addr: addr, trans: trans, id: ServerID("server-" + string(addr))}
}

func assuranceStartNode(t *testing.T, n *assuranceProbeNode, bootstrap *Configuration, stalling bool) {
	pc := assuranceProbeConfig(t, string(n.id), n.id)
	store := NewInmemStore()
	snap := NewInmemSnapshotStore()
	var logs LogStore = store
	if stalling {
		n.slow = &assuranceSlowStore{
			LogStore: store,
			armed:    new(int32),
			stalls:   new(int32),
			delay:    600 * time.Millisecond,
		}
		logs = n.slow
	}
	if bootstrap != nil {
		if err := BootstrapCluster(pc, logs, store, snap, n.trans, *bootstrap); err != nil {
			t.Fatalf("BootstrapCluster failed: %v", err)
		}
	}
	r, err := NewRaft(pc, &MockFSM{}, logs, store, snap, n.trans)
	if err != nil {
		t.Fatalf("NewRaft failed: %v", err)
	}
	n.raft = r
}

func assuranceWaitLeader(t *testing.T, nodes []*assuranceProbeNode, limit time.Duration) *assuranceProbeNode {
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		for _, n := range nodes {
			if n.raft.State() == Leader {
				return n
			}
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("no leader elected within %s", limit)
	return nil
}

func assuranceHasServer(c Configuration, id ServerID) bool {
	for _, s := range c.Servers {
		if s.ID == id {
			return true
		}
	}
	return false
}

func assuranceEmit(t *testing.T, event map[string]interface{}) {
	b, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	t.Log("CA_EVENT " + string(b))
}

func assuranceLeaderIDs(nodes []*assuranceProbeNode) []string {
	var ids []string
	for _, n := range nodes {
		if n.raft.State() == Leader {
			ids = append(ids, string(n.id))
		}
	}
	return ids
}

func assuranceMaxTerm(nodes []*assuranceProbeNode) uint64 {
	var maxTerm uint64
	for _, n := range nodes {
		if term := n.raft.getCurrentTerm(); term > maxTerm {
			maxTerm = term
		}
	}
	return maxTerm
}

// TestAssuranceVerifyLeaderDuringLeaderStall asks whether a leader whose main
// loop is stalled past its lease, while a voter majority elects a successor,
// can still return VerifyLeader success by counting a non-voter's
// acknowledgement. Each trial is a fresh cluster; the outcome hinges on which
// ready case the main loop serves first when the stall ends, so trials are
// reported individually.
func TestAssuranceVerifyLeaderDuringLeaderStall(t *testing.T) {
	const trials = 8
	for trial := 0; trial < trials; trial++ {
		assuranceRunStallTrial(t, trial)
	}
}

func assuranceRunStallTrial(t *testing.T, trial int) {
	var voters Configuration
	var nodes []*assuranceProbeNode
	for i := 0; i < 3; i++ {
		n := assuranceNewNode()
		nodes = append(nodes, n)
		voters.Servers = append(voters.Servers, Server{Suffrage: Voter, ID: n.id, Address: n.addr})
	}
	nv := assuranceNewNode()
	nodes = append(nodes, nv)
	for _, a := range nodes {
		for _, b := range nodes {
			if a != b {
				a.trans.Connect(b.addr, b.trans)
			}
		}
	}
	// Every voter gets a stalling store, but only the elected leader's is armed
	// later, so follower writes are unaffected while the leader is stalled.
	for _, n := range nodes[:3] {
		assuranceStartNode(t, n, &voters, true)
	}
	assuranceStartNode(t, nv, nil, false)
	defer func() {
		for _, n := range nodes {
			_ = n.raft.Shutdown().Error()
			_ = n.trans.Close()
		}
	}()

	leader := assuranceWaitLeader(t, nodes[:3], 10*time.Second)
	if err := leader.raft.AddNonvoter(nv.id, nv.addr, 0, 5*time.Second).Error(); err != nil {
		t.Fatalf("AddNonvoter failed: %v", err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) && !assuranceHasServer(leader.raft.getLatestConfiguration(), nv.id) {
		time.Sleep(5 * time.Millisecond)
	}
	if !assuranceHasServer(leader.raft.getLatestConfiguration(), nv.id) {
		t.Fatalf("non-voter %v never appeared in the leader configuration", nv.id)
	}
	time.Sleep(300 * time.Millisecond)

	latest := leader.raft.getLatestConfiguration()
	voterCount, nonvoterCount := 0, 0
	for _, s := range latest.Servers {
		if s.Suffrage == Voter {
			voterCount++
		} else {
			nonvoterCount++
		}
	}
	quorum := voterCount/2 + 1
	leaderTermBefore := leader.raft.getCurrentTerm()

	// Partition: the leader keeps only the non-voter.
	near := map[ServerAddress]bool{leader.addr: true, nv.addr: true}
	for _, a := range nodes {
		for _, b := range nodes {
			if a == b {
				continue
			}
			if near[a.addr] != near[b.addr] {
				a.trans.Disconnect(b.addr)
			}
		}
	}

	assuranceEmit(t, map[string]interface{}{
		"event":          "assurance_stall_setup",
		"trial":          trial,
		"leader_id":      string(leader.id),
		"nonvoter_id":    string(nv.id),
		"voter_count":    voterCount,
		"nonvoter_count": nonvoterCount,
		"quorum_size":    quorum,
		"stall_delay_ms": leader.slow.delay.Milliseconds(),
		"heartbeat_ms":   leader.raft.config().HeartbeatTimeout.Milliseconds(),
		"lease_ms":       leader.raft.config().LeaderLeaseTimeout.Milliseconds(),
	})

	// Sample leadership continuously from the partition onwards.
	var (
		sampledTotal     int32
		otherLeaderSeen  int32
		leaderNotLeader  int32
		maxTermSeen      uint64
		firstOtherLeader int64 = -1
	)
	startAt := time.Now()
	stopSampling := make(chan struct{})
	go func() {
		tick := time.NewTicker(time.Millisecond)
		defer tick.Stop()
		for {
			select {
			case <-stopSampling:
				return
			case <-tick.C:
				ids := assuranceLeaderIDs(nodes)
				atomic.AddInt32(&sampledTotal, 1)
				term := assuranceMaxTerm(nodes)
				if term > atomic.LoadUint64(&maxTermSeen) {
					atomic.StoreUint64(&maxTermSeen, term)
				}
				for _, id := range ids {
					if id != string(leader.id) {
						atomic.StoreInt32(&otherLeaderSeen, 1)
						if atomic.LoadInt64(&firstOtherLeader) < 0 {
							atomic.StoreInt64(&firstOtherLeader, time.Since(startAt).Milliseconds())
						}
					}
				}
				if leader.raft.State() != Leader {
					atomic.AddInt32(&leaderNotLeader, 1)
				}
			}
		}
	}()

	// Arm the stall, then make the leader write: the main loop blocks inside
	// StoreLogs, so its lease case cannot run while the voters time out.
	atomic.StoreInt32(leader.slow.armed, 1)
	applyFuture := leader.raft.Apply([]byte("stall"), 5*time.Second)

	// Queue a verify request while the leader is stalled.
	time.Sleep(300 * time.Millisecond)
	verify := leader.raft.VerifyLeader()
	verifyDone := make(chan error, 1)
	go func() { verifyDone <- verify.Error() }()
	verifyErr := "pending"
	var verifyReturnedMs int64 = -1
	select {
	case err := <-verifyDone:
		verifyReturnedMs = time.Since(startAt).Milliseconds()
		if err == nil {
			verifyErr = "nil"
		} else {
			verifyErr = err.Error()
		}
	case <-time.After(4 * time.Second):
	}

	otherLeader := atomic.LoadInt32(&otherLeaderSeen) == 1
	leaderStayed := atomic.LoadInt32(&leaderNotLeader) == 0
	otherLeaderFirst := atomic.LoadInt64(&firstOtherLeader)

	close(stopSampling)
	time.Sleep(5 * time.Millisecond)

	applyErr := "pending"
	select {
	case err := <-func() chan error {
		ch := make(chan error, 1)
		go func() { ch <- applyFuture.Error() }()
		return ch
	}():
		if err == nil {
			applyErr = "nil"
		} else {
			applyErr = err.Error()
		}
	case <-time.After(2 * time.Second):
	}

	assuranceEmit(t, map[string]interface{}{
		"event":                         "assurance_stall_trial",
		"trial":                         trial,
		"leader_id":                     string(leader.id),
		"nonvoter_id":                   string(nv.id),
		"leader_term_before":            leaderTermBefore,
		"voter_count":                   voterCount,
		"nonvoter_count":                nonvoterCount,
		"quorum_size":                   quorum,
		"stall_delay_ms":                leader.slow.delay.Milliseconds(),
		"stalls_triggered":              atomic.LoadInt32(leader.slow.stalls),
		"verify_error":                  verifyErr,
		"verify_returned_ms":            verifyReturnedMs,
		"leader_state_after":            leader.raft.State().String(),
		"leader_term_after":             leader.raft.getCurrentTerm(),
		"max_term_seen":                 atomic.LoadUint64(&maxTermSeen),
		"other_leader_seen":             otherLeader,
		"other_leader_first_ms":         otherLeaderFirst,
		"leader_never_left_leader":      leaderStayed,
		"sampled_total":                 atomic.LoadInt32(&sampledTotal),
		"leader_not_leader_samples":     atomic.LoadInt32(&leaderNotLeader),
		"apply_error":                   applyErr,
		"verify_success_with_successor": verifyErr == "nil" && otherLeader,
	})
}
