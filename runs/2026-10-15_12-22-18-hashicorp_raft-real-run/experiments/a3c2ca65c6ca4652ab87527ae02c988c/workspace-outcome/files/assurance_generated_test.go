// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"sync/atomic"
	"testing"
	"time"
)

type assuranceProbeNode struct {
	id    ServerID
	addr  ServerAddress
	trans *InmemTransport
	slow  *assuranceSlowStore
	raft  *Raft
}

// assuranceSlowStore models a leader whose disk stalls: while armed, StoreLogs
// blocks the caller, which for the leader is its main loop.
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
		n.slow = &assuranceSlowStore{LogStore: store, armed: new(int32), stalls: new(int32), delay: 900 * time.Millisecond}
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

func assuranceConnect(a, b *assuranceProbeNode) {
	a.trans.Connect(b.addr, b.trans)
	b.trans.Connect(a.addr, a.trans)
}

func assuranceDisconnect(a, b *assuranceProbeNode) {
	a.trans.Disconnect(b.addr)
	b.trans.Disconnect(a.addr)
}

// TestAssuranceVerifyRegisteredThenStalled asks whether a VerifyLeader request
// that was registered before the leader's main loop stalls can still complete
// successfully during the stall, by counting the acknowledgement of a
// non-voter that is reconnected after a voter majority has elected a
// successor. The vote path runs on replication goroutines, so it does not need
// the stalled main loop.
func TestAssuranceVerifyRegisteredThenStalled(t *testing.T) {
	for _, delay := range []int{250, 300, 350, 400, 450, 500} {
		assuranceRunRegisteredStallTrial(t, delay)
	}
}

func assuranceRunRegisteredStallTrial(t *testing.T, reconnectAfterMs int) {
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
				assuranceConnect(a, b)
			}
		}
	}
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
	voterCount := 0
	for _, s := range latest.Servers {
		if s.Suffrage == Voter {
			voterCount++
		}
	}
	quorum := voterCount/2 + 1
	leaderTermBefore := leader.raft.getCurrentTerm()

	assuranceEmit(t, map[string]interface{}{
		"event":              "assurance_registered_setup",
		"reconnect_after_ms": reconnectAfterMs,
		"leader_id":          string(leader.id),
		"nonvoter_id":        string(nv.id),
		"voter_count":        voterCount,
		"quorum_size":        quorum,
		"lease_ms":           leader.raft.config().LeaderLeaseTimeout.Milliseconds(),
		"stall_delay_ms":     leader.slow.delay.Milliseconds(),
	})

	// Isolate the leader: it cannot reach any voter, and not the non-voter
	// either, so its verify has no second acknowledgement available yet.
	for _, n := range nodes[:3] {
		if n != leader {
			assuranceDisconnect(leader, n)
			assuranceDisconnect(nv, n)
		}
	}
	assuranceDisconnect(leader, nv)

	startAt := time.Now()
	verify := leader.raft.VerifyLeader()
	// Let the main loop register the request before it is blocked.
	time.Sleep(30 * time.Millisecond)

	// Stall the leader's main loop so its lease case cannot run, then reconnect
	// the non-voter after the delay while a voter majority elects.
	atomic.StoreInt32(leader.slow.armed, 1)
	_ = leader.raft.Apply([]byte("stall"), 5*time.Second)

	var (
		otherLeaderBefore int32
		otherLeaderFirst  int64 = -1
		maxTermSeen       uint64
		sampled           int32
	)
	stopSampling := make(chan struct{})
	go func() {
		tick := time.NewTicker(time.Millisecond)
		defer tick.Stop()
		for {
			select {
			case <-stopSampling:
				return
			case <-tick.C:
				atomic.AddInt32(&sampled, 1)
				if term := assuranceMaxTerm(nodes); term > atomic.LoadUint64(&maxTermSeen) {
					atomic.StoreUint64(&maxTermSeen, term)
				}
				for _, id := range assuranceLeaderIDs(nodes) {
					if id != string(leader.id) {
						atomic.StoreInt32(&otherLeaderBefore, 1)
						if atomic.LoadInt64(&otherLeaderFirst) < 0 {
							atomic.StoreInt64(&otherLeaderFirst, time.Since(startAt).Milliseconds())
						}
					}
				}
			}
		}
	}()

	reconnectAt := time.Duration(reconnectAfterMs) * time.Millisecond
	time.Sleep(reconnectAt)
	assuranceConnect(leader, nv)

	verifyDone := make(chan error, 1)
	go func() { verifyDone <- verify.Error() }()
	verifyErr := "pending"
	verdictMs := int64(-1)
	select {
	case err := <-verifyDone:
		verdictMs = time.Since(startAt).Milliseconds()
		if err == nil {
			verifyErr = "nil"
		} else {
			verifyErr = err.Error()
		}
	case <-time.After(4 * time.Second):
	}
	close(stopSampling)
	time.Sleep(5 * time.Millisecond)

	other := atomic.LoadInt32(&otherLeaderBefore) == 1
	first := atomic.LoadInt64(&otherLeaderFirst)
	assuranceEmit(t, map[string]interface{}{
		"event":                      "assurance_registered_result",
		"reconnect_after_ms":         reconnectAfterMs,
		"leader_id":                  string(leader.id),
		"verify_error":               verifyErr,
		"verdict_ms":                 verdictMs,
		"other_leader_seen":          other,
		"other_leader_first_ms":      first,
		"other_leader_before_verdict": other && first >= 0 && verdictMs >= 0 && first < verdictMs,
		"max_term_seen":              atomic.LoadUint64(&maxTermSeen),
		"leader_term_before":         leaderTermBefore,
		"leader_term_after":          leader.raft.getCurrentTerm(),
		"leader_state_after":         leader.raft.State().String(),
		"sampled_total":              atomic.LoadInt32(&sampled),
		"stalls_triggered":           atomic.LoadInt32(leader.slow.stalls),
	})
}
