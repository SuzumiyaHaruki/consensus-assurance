// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated assurance harness. A three-server configuration with two voters and
// one non-voter elects a leader, the leader's route to the other voter is
// removed, and the leader then asks the library whether it is still the leader.
// The harness records the verification result together with the configuration
// that produced it. It reports raw fields only.

package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

func assuranceVerifyEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

type assuranceVerifyFSM struct{}

func (assuranceVerifyFSM) Apply(*Log) interface{}         { return nil }
func (assuranceVerifyFSM) Snapshot() (FSMSnapshot, error) { return assuranceVerifySnapshot{}, nil }
func (assuranceVerifyFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceVerifySnapshot struct{}

func (assuranceVerifySnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceVerifySnapshot) Release()                     {}

func TestAssuranceVerifyLeaderVoterQuorum(t *testing.T) {
	const (
		op      = "verify-leader-voter-quorum"
		cluster = "c1"
	)

	addr1, trans1 := NewInmemTransport(ServerAddress("n1"))
	addr2, trans2 := NewInmemTransport(ServerAddress("n2"))
	addr3, trans3 := NewInmemTransport(ServerAddress("n3"))
	trans1.Connect(addr2, trans2)
	trans2.Connect(addr1, trans1)
	trans1.Connect(addr3, trans3)
	trans3.Connect(addr1, trans1)
	trans2.Connect(addr3, trans3)
	trans3.Connect(addr2, trans2)

	configuration := Configuration{Servers: []Server{
		{ID: ServerID("n1"), Address: addr1, Suffrage: Voter},
		{ID: ServerID("n2"), Address: addr2, Suffrage: Voter},
		{ID: ServerID("n3"), Address: addr3, Suffrage: Nonvoter},
	}}

	type member struct {
		id    ServerID
		addr  ServerAddress
		trans *InmemTransport
		r     *Raft
	}
	members := []*member{
		{id: ServerID("n1"), addr: addr1, trans: trans1},
		{id: ServerID("n2"), addr: addr2, trans: trans2},
		{id: ServerID("n3"), addr: addr3, trans: trans3},
	}
	for _, m := range members {
		logStore := NewInmemStore()
		stableStore := NewInmemStore()
		snapStore := NewInmemSnapshotStore()
		conf := DefaultConfig()
		conf.LocalID = m.id
		conf.ProtocolVersion = 3
		conf.LogLevel = "ERROR"
		conf.HeartbeatTimeout = 500 * time.Millisecond
		conf.ElectionTimeout = 1 * time.Second
		conf.LeaderLeaseTimeout = 500 * time.Millisecond
		conf.CommitTimeout = 50 * time.Millisecond
		conf.SnapshotInterval = time.Hour
		conf.SnapshotThreshold = 100000
		conf.TrailingLogs = 100000
		if err := BootstrapCluster(conf, logStore, stableStore, snapStore, m.trans, configuration); err != nil {
			assuranceVerifyEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(m.id), "detail": "bootstrap: " + err.Error()})
			t.Fatalf("assurance: bootstrap %s: %v", m.id, err)
		}
		r, err := NewRaft(conf, assuranceVerifyFSM{}, logStore, stableStore, snapStore, m.trans)
		if err != nil {
			assuranceVerifyEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(m.id), "detail": "NewRaft: " + err.Error()})
			t.Fatalf("assurance: NewRaft %s: %v", m.id, err)
		}
		m.r = r
		defer func(r *Raft) { r.Shutdown().Error() }(r)
	}

	var leader *member
	waitUntil := time.Now().Add(5 * time.Second)
	for leader == nil {
		for _, m := range members {
			if m.r.State() == Leader {
				leader = m
			}
		}
		if time.Now().After(waitUntil) {
			assuranceVerifyEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "detail": "no leader elected"})
			t.Fatalf("assurance: no leader elected")
		}
		time.Sleep(10 * time.Millisecond)
	}
	if err := leader.r.Barrier(3 * time.Second).Error(); err != nil {
		assuranceVerifyEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(leader.id), "detail": "barrier: " + err.Error()})
		t.Fatalf("assurance: barrier: %v", err)
	}

	var otherVoter *member
	var nonVoter *member
	for _, m := range members {
		if m == leader {
			continue
		}
		if m.id == ServerID("n3") {
			nonVoter = m
		} else {
			otherVoter = m
		}
	}
	if otherVoter == nil || nonVoter == nil {
		t.Fatalf("assurance: unexpected membership")
	}

	voters, nonvoters := 0, 0
	for _, server := range configuration.Servers {
		if server.Suffrage == Voter {
			voters++
		} else {
			nonvoters++
		}
	}
	quorumSize := voters/2 + 1

	assuranceVerifyEvent(map[string]interface{}{
		"event":          "verification_setup",
		"cluster":        cluster,
		"op":             op,
		"node":           string(leader.id),
		"term":           leader.r.CurrentTerm(),
		"voters":         voters,
		"nonvoters":      nonvoters,
		"quorum_size":    quorumSize,
		"other_voter":    string(otherVoter.id),
		"non_voter":      string(nonVoter.id),
		"leader_state":   leader.r.State().String(),
	})

	// Remove the leader's route to the only other voter, so the leader can no
	// longer reach a quorum of voters but can still reach the non-voter.
	leader.trans.Disconnect(otherVoter.addr)
	time.Sleep(200 * time.Millisecond)

	type verifyOutcome struct {
		result string
		err    error
	}
	done := make(chan verifyOutcome, 1)
	go func() {
		err := leader.r.VerifyLeader().Error()
		if err != nil {
			done <- verifyOutcome{result: "error", err: err}
			return
		}
		done <- verifyOutcome{result: "success"}
	}()
	outcome := verifyOutcome{result: "unfinished"}
	select {
	case outcome = <-done:
	case <-time.After(3 * time.Second):
		outcome = verifyOutcome{result: "unfinished"}
	}

	detail := ""
	if outcome.err != nil {
		detail = outcome.err.Error()
	}
	stats := leader.r.Stats()
	assuranceVerifyEvent(map[string]interface{}{
		"event":                  "verification_observed",
		"cluster":                cluster,
		"op":                     op,
		"node":                   string(leader.id),
		"voters":                 voters,
		"nonvoters":              nonvoters,
		"quorum_size":            quorumSize,
		"other_voter":            string(otherVoter.id),
		"non_voter":              string(nonVoter.id),
		"other_voter_reachable":  false,
		"verification_result":    outcome.result,
		"verification_error":     detail,
		"leader_state":           leader.r.State().String(),
		"leader_stats_state":     stats["state"],
	})
}
