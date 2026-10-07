// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated assurance harness. A five-server configuration with three voters and
// two non-voters elects a leader, the leader's routes to both other voters are
// removed so only non-voters remain reachable, and the leader then asks the
// library whether it is still the leader. It reports raw fields only.

package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

func assuranceVerifyTwoEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

type assuranceVerifyTwoFSM struct{}

func (assuranceVerifyTwoFSM) Apply(*Log) interface{}         { return nil }
func (assuranceVerifyTwoFSM) Snapshot() (FSMSnapshot, error) { return assuranceVerifyTwoSnapshot{}, nil }
func (assuranceVerifyTwoFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceVerifyTwoSnapshot struct{}

func (assuranceVerifyTwoSnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceVerifyTwoSnapshot) Release()                     {}

func TestAssuranceVerifyLeaderTwoNonvoters(t *testing.T) {
	const (
		op      = "verify-leader-two-nonvoters"
		cluster = "c1"
	)

	ids := []ServerID{"n1", "n2", "n3", "n4", "n5"}
	addrs := make([]ServerAddress, len(ids))
	trans := make([]*InmemTransport, len(ids))
	for i, id := range ids {
		addrs[i], trans[i] = NewInmemTransport(ServerAddress(id))
	}
	for i := range ids {
		for j := range ids {
			if i != j {
				trans[i].Connect(addrs[j], trans[j])
			}
		}
	}
	configuration := Configuration{Servers: []Server{
		{ID: "n1", Address: addrs[0], Suffrage: Voter},
		{ID: "n2", Address: addrs[1], Suffrage: Voter},
		{ID: "n3", Address: addrs[2], Suffrage: Voter},
		{ID: "n4", Address: addrs[3], Suffrage: Nonvoter},
		{ID: "n5", Address: addrs[4], Suffrage: Nonvoter},
	}}

	rafts := make([]*Raft, len(ids))
	for i, id := range ids {
		logStore := NewInmemStore()
		stableStore := NewInmemStore()
		snapStore := NewInmemSnapshotStore()
		conf := DefaultConfig()
		conf.LocalID = id
		conf.ProtocolVersion = 3
		conf.LogLevel = "ERROR"
		conf.HeartbeatTimeout = 500 * time.Millisecond
		conf.ElectionTimeout = 1 * time.Second
		conf.LeaderLeaseTimeout = 500 * time.Millisecond
		conf.CommitTimeout = 50 * time.Millisecond
		conf.SnapshotInterval = time.Hour
		conf.SnapshotThreshold = 100000
		conf.TrailingLogs = 100000
		if err := BootstrapCluster(conf, logStore, stableStore, snapStore, trans[i], configuration); err != nil {
			assuranceVerifyTwoEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(id), "detail": "bootstrap: " + err.Error()})
			t.Fatalf("assurance: bootstrap %s: %v", id, err)
		}
		r, err := NewRaft(conf, assuranceVerifyTwoFSM{}, logStore, stableStore, snapStore, trans[i])
		if err != nil {
			assuranceVerifyTwoEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(id), "detail": "NewRaft: " + err.Error()})
			t.Fatalf("assurance: NewRaft %s: %v", id, err)
		}
		rafts[i] = r
		defer func(r *Raft) { r.Shutdown().Error() }(r)
	}

	leaderIdx := -1
	waitUntil := time.Now().Add(5 * time.Second)
	for leaderIdx < 0 {
		for i := 0; i < 3; i++ {
			if rafts[i].State() == Leader {
				leaderIdx = i
			}
		}
		if time.Now().After(waitUntil) {
			assuranceVerifyTwoEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "detail": "no leader elected"})
			t.Fatalf("assurance: no leader elected")
		}
		time.Sleep(10 * time.Millisecond)
	}
	leader := rafts[leaderIdx]
	if err := leader.Barrier(3 * time.Second).Error(); err != nil {
		assuranceVerifyTwoEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(ids[leaderIdx]), "detail": "barrier: " + err.Error()})
		t.Fatalf("assurance: barrier: %v", err)
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

	assuranceVerifyTwoEvent(map[string]interface{}{
		"event":        "verification_setup",
		"cluster":      cluster,
		"op":           op,
		"node":         string(ids[leaderIdx]),
		"term":         leader.CurrentTerm(),
		"voters":       voters,
		"nonvoters":    nonvoters,
		"quorum_size":  quorumSize,
		"non_voters":   "n4,n5",
		"leader_state": leader.State().String(),
	})

	// Remove the leader's routes to both other voters, leaving only the two
	// non-voters reachable.
	for i := 0; i < 3; i++ {
		if i == leaderIdx {
			continue
		}
		trans[leaderIdx].Disconnect(addrs[i])
	}
	time.Sleep(200 * time.Millisecond)

	type outcome struct {
		result string
		err    error
	}
	done := make(chan outcome, 1)
	go func() {
		err := leader.VerifyLeader().Error()
		if err != nil {
			done <- outcome{result: "error", err: err}
			return
		}
		done <- outcome{result: "success"}
	}()
	out := outcome{result: "unfinished"}
	select {
	case out = <-done:
	case <-time.After(3 * time.Second):
		out = outcome{result: "unfinished"}
	}

	detail := ""
	if out.err != nil {
		detail = out.err.Error()
	}
	stats := leader.Stats()
	assuranceVerifyTwoEvent(map[string]interface{}{
		"event":                 "verification_observed",
		"cluster":               cluster,
		"op":                    op,
		"node":                  string(ids[leaderIdx]),
		"voters":                voters,
		"nonvoters":             nonvoters,
		"quorum_size":           quorumSize,
		"non_voters":            "n4,n5",
		"other_voter_reachable": false,
		"verification_result":   out.result,
		"verification_error":    detail,
		"leader_state":          leader.State().String(),
		"leader_stats_state":    stats["state"],
	})
}
