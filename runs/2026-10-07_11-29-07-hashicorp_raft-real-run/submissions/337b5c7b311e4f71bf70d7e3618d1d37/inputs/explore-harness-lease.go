// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated exploration harness. Three connected voters elect a leader, the
// leader's own reloadable intervals are lengthened through the public API, and
// the harness then records the leader's state and term, its peers' states and
// terms, and whether a peer still answers a probe. It reports raw fields only.

package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

func assuranceLeaseEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

type assuranceLeaseFSM struct{}

func (assuranceLeaseFSM) Apply(*Log) interface{}         { return nil }
func (assuranceLeaseFSM) Snapshot() (FSMSnapshot, error) { return assuranceLeaseSnapshot{}, nil }
func (assuranceLeaseFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceLeaseSnapshot struct{}

func (assuranceLeaseSnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceLeaseSnapshot) Release()                     {}

func assuranceLeaseWaitFor(cond func() bool, limit time.Duration) bool {
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if cond() {
			return true
		}
		time.Sleep(time.Millisecond)
	}
	return false
}

func assuranceLeaseNode(t *testing.T, id ServerID, addr ServerAddress) (*Raft, *InmemTransport) {
	conf := DefaultConfig()
	conf.LocalID = id
	conf.ProtocolVersion = 3
	conf.LogLevel = "ERROR"
	conf.HeartbeatTimeout = 5 * time.Second
	conf.ElectionTimeout = 6 * time.Second
	conf.LeaderLeaseTimeout = 5 * time.Second
	conf.CommitTimeout = 30 * time.Second
	conf.SnapshotInterval = time.Hour
	conf.SnapshotThreshold = 100000
	conf.TrailingLogs = 100000
	_, trans := NewInmemTransport(addr)
	r, err := NewRaft(conf, assuranceLeaseFSM{}, NewInmemStore(), NewInmemStore(), NewInmemSnapshotStore(), trans)
	if err != nil {
		t.Fatalf("assurance: NewRaft %s: %v", id, err)
	}
	return r, trans
}

func TestAssuranceLeaderLeaseCoherence(t *testing.T) {
	const op = "leader-lease-refresh-coherence"
	ids := []ServerID{"n1", "n2", "n3"}
	addrs := []ServerAddress{"lease-1", "lease-2", "lease-3"}

	rafts := make([]*Raft, 0, len(ids))
	transports := make([]*InmemTransport, 0, len(ids))
	for i, id := range ids {
		r, trans := assuranceLeaseNode(t, id, addrs[i])
		rafts = append(rafts, r)
		transports = append(transports, trans)
	}
	for i := range transports {
		for j := range transports {
			if i != j {
				transports[i].Connect(addrs[j], transports[j])
			}
		}
	}
	defer func() {
		for _, r := range rafts {
			r.Shutdown()
		}
	}()

	configuration := Configuration{}
	for i, id := range ids {
		configuration.Servers = append(configuration.Servers, Server{ID: id, Address: addrs[i], Suffrage: Voter})
	}
	for _, r := range rafts {
		if err := r.BootstrapCluster(configuration).Error(); err != nil {
			assuranceLeaseEvent(map[string]interface{}{"event": "assurance_setup_failed", "op": op, "detail": "bootstrap: " + err.Error()})
			t.Fatalf("assurance: bootstrap: %v", err)
		}
	}

	// Wait for one node to become the leader, then lengthen its own intervals so
	// the interval at which it refreshes contact with a reachable voter exceeds
	// the lease it was created with. Everything stays reachable throughout.
	var leader *Raft
	var leaderID ServerID
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) && leader == nil {
		for i, r := range rafts {
			if r.State() == Leader {
				leader, leaderID = r, ids[i]
			}
		}
		if leader == nil {
			time.Sleep(5 * time.Millisecond)
		}
	}
	if leader == nil {
		assuranceLeaseEvent(map[string]interface{}{"event": "assurance_setup_failed", "op": op, "detail": "no leader was elected"})
		t.Fatalf("assurance: no leader was elected")
	}
	reload := leader.ReloadableConfig()
	reload.HeartbeatTimeout = 300 * time.Second
	reload.ElectionTimeout = 300 * time.Second
	if err := leader.ReloadConfig(reload); err != nil {
		assuranceLeaseEvent(map[string]interface{}{"event": "assurance_setup_failed", "op": op, "detail": "reload: " + err.Error()})
		t.Fatalf("assurance: reload: %v", err)
	}
	admittedTerm := leader.CurrentTerm()

	// Give the leader time to miss its own lease, then look at it again.
	time.Sleep(12 * time.Second)

	leaderState := leader.State().String()
	leaderTerm := leader.CurrentTerm()
	followerStates := ""
	var probeReachable bool
	var probeTerm uint64
	for i, r := range rafts {
		if ids[i] == leaderID {
			continue
		}
		followerStates += fmt.Sprintf("%s=%s/%d ", ids[i], r.State().String(), r.CurrentTerm())
		if !probeReachable {
			_, trans := NewInmemTransport(ServerAddress("probe-1"))
			for j := range transports {
				trans.Connect(addrs[j], transports[j])
			}
			probe := AppendEntriesRequest{
				RPCHeader: RPCHeader{ProtocolVersion: 3, ID: []byte(leaderID), Addr: trans.EncodePeer(leaderID, addrs[0])},
				Term:      leaderTerm,
				Leader:    trans.EncodePeer(leaderID, addrs[0]),
			}
			var resp AppendEntriesResponse
			if err := trans.AppendEntries(ids[i], addrs[i], &probe, &resp); err == nil {
				probeReachable = resp.Success
				probeTerm = resp.Term
			}
			trans.Close()
		}
	}

	assuranceLeaseEvent(map[string]interface{}{
		"event":            "leader_claim_observed",
		"cluster":          ids[0],
		"op":               op,
		"node":             string(leaderID),
		"term":             admittedTerm,
		"state":            "Leader",
		"heartbeat_window": "5s before reload, 300s after",
	})
	assuranceLeaseEvent(map[string]interface{}{
		"event":            "lease_observation",
		"cluster":          ids[0],
		"op":               op,
		"leader_node":      string(leaderID),
		"leader_state":     leaderState,
		"leader_term":      leaderTerm,
		"follower_states":  followerStates,
		"probe_reachable":  probeReachable,
		"probe_term":       probeTerm,
		"lease_timeout_ms": int((5 * time.Second).Milliseconds()),
	})
}
