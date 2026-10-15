// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

// assuranceProbeNode is one real Raft instance in this process, with its own
// store, snapshot store and in-memory transport.
type assuranceProbeNode struct {
	id    ServerID
	addr  ServerAddress
	trans *InmemTransport
	raft  *Raft
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

// assuranceNewNode only allocates a transport; starting the Raft instance is a
// separate step so that every transport can be wired first.
func assuranceNewNode(t *testing.T) *assuranceProbeNode {
	addr, trans := NewInmemTransport("")
	return &assuranceProbeNode{
		addr:  addr,
		trans: trans,
		id:    ServerID("server-" + string(addr)),
	}
}

func assuranceStartNode(t *testing.T, n *assuranceProbeNode, bootstrap *Configuration) {
	pc := assuranceProbeConfig(t, string(n.id), n.id)
	store := NewInmemStore()
	snap := NewInmemSnapshotStore()
	if bootstrap != nil {
		if err := BootstrapCluster(pc, store, store, snap, n.trans, *bootstrap); err != nil {
			t.Fatalf("BootstrapCluster failed: %v", err)
		}
	}
	r, err := NewRaft(pc, &MockFSM{}, store, store, snap, n.trans)
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
		time.Sleep(10 * time.Millisecond)
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

func assurancePartition(nodes []*assuranceProbeNode, near map[ServerAddress]bool) {
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
}

// assuranceVerify observes VerifyLeader() at the leader, capturing the actual
// returned endpoint (nil error, a concrete error string, or still pending).
func assuranceVerify(leader *Raft, wait time.Duration) string {
	f := leader.VerifyLeader()
	done := make(chan error, 1)
	go func() { done <- f.Error() }()
	select {
	case err := <-done:
		if err == nil {
			return "nil"
		}
		return err.Error()
	case <-time.After(wait):
		return "pending"
	}
}

// assuranceRunCase builds a real cluster of three voters plus one non-voter,
// joins the non-voter through the leader's AddNonvoter API, then partitions the
// leader so that only the peers listed in keep can be reached, and observes
// VerifyLeader() on the leader.
func assuranceRunCase(t *testing.T, tag string, keepNonvoter bool, keepVoter bool) {
	var voters Configuration
	var nodes []*assuranceProbeNode
	for i := 0; i < 3; i++ {
		n := assuranceNewNode(t)
		nodes = append(nodes, n)
		voters.Servers = append(voters.Servers, Server{Suffrage: Voter, ID: n.id, Address: n.addr})
	}
	// Fourth node joins as a non-voter later, started without a configuration.
	nv := assuranceNewNode(t)
	nodes = append(nodes, nv)
	// Wire every transport to every other transport before starting anything.
	for _, a := range nodes {
		for _, b := range nodes {
			if a != b {
				a.trans.Connect(b.addr, b.trans)
			}
		}
	}
	for _, n := range nodes[:3] {
		assuranceStartNode(t, n, &voters)
	}
	assuranceStartNode(t, nv, nil)

	conf := assuranceProbeConfig(t, tag, "")
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
	// Wait until the leader's latest configuration carries the non-voter and
	// the non-voter has been contacted at least once.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if assuranceHasServer(leader.raft.getLatestConfiguration(), nv.id) {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if !assuranceHasServer(leader.raft.getLatestConfiguration(), nv.id) {
		t.Fatalf("non-voter %v never appeared in the leader configuration", nv.id)
	}
	time.Sleep(300 * time.Millisecond)

	// Identify a surviving voter and the non-voter by ID, and build the
	// partition around the leader.
	var keptVoter *assuranceProbeNode
	for _, n := range nodes[:3] {
		if n != leader {
			keptVoter = n
			break
		}
	}
	near := map[ServerAddress]bool{leader.addr: true}
	if keepNonvoter {
		near[nv.addr] = true
	}
	if keepVoter {
		near[keptVoter.addr] = true
	}

	latest := leader.raft.getLatestConfiguration()
	var voterIDs, nonvoterIDs []string
	for _, s := range latest.Servers {
		if s.Suffrage == Voter {
			voterIDs = append(voterIDs, string(s.ID))
		} else {
			nonvoterIDs = append(nonvoterIDs, string(s.ID))
		}
	}
	quorum := (len(voterIDs) / 2) + 1

	assurancePartition(nodes, near)
	start := time.Now()
	verifyErr := assuranceVerify(leader.raft, 900*time.Millisecond)
	elapsed := time.Since(start)

	maxOtherTerm := uint64(0)
	otherStates := []string{}
	for _, n := range nodes {
		if n == leader {
			continue
		}
		if t2 := n.raft.getCurrentTerm(); t2 > maxOtherTerm {
			maxOtherTerm = t2
		}
		otherStates = append(otherStates, string(n.id)+"="+n.raft.State().String())
	}

	event := map[string]interface{}{
		"case":                tag,
		"leader_id":           string(leader.id),
		"leader_addr":         string(leader.addr),
		"kept_nonvoter":       keepNonvoter,
		"kept_voter":          keepVoter,
		"kept_nonvoter_id":    string(nv.id),
		"voters":              voterIDs,
		"nonvoters":           nonvoterIDs,
		"quorum_size":         quorum,
		"leader_term":         leader.raft.getCurrentTerm(),
		"other_max_term":      maxOtherTerm,
		"other_states":        otherStates,
		"leader_state_after":  leader.raft.State().String(),
		"verify_error":        verifyErr,
		"elapsed_ms":          elapsed.Milliseconds(),
		"leader_lease_timeout": conf.LeaderLeaseTimeout.String(),
	}
	b, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceVerifyLeaderNonvoterQuorum probes whether VerifyLeader on a
// leader that can only reach a non-voter reports success, compared with the
// same partition keeping one voter, and with no reachable peer at all.
func TestAssuranceVerifyLeaderNonvoterQuorum(t *testing.T) {
	assuranceRunCase(t, "keep-nonvoter", true, false)
	assuranceRunCase(t, "keep-voter", false, true)
	assuranceRunCase(t, "keep-none", false, false)
}
