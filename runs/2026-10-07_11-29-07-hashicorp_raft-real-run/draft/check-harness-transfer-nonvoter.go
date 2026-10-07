// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated assurance harness. A three-voter configuration with one non-voter
// elects a leader, the leader is asked to transfer leadership to the non-voter,
// and the harness records what the non-voter becomes and what the transfer
// reports. It reports raw fields only.

package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

func assuranceTransferEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

type assuranceTransferFSM struct{}

func (assuranceTransferFSM) Apply(*Log) interface{}         { return nil }
func (assuranceTransferFSM) Snapshot() (FSMSnapshot, error) { return assuranceTransferSnapshot{}, nil }
func (assuranceTransferFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceTransferSnapshot struct{}

func (assuranceTransferSnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceTransferSnapshot) Release()                     {}

func TestAssuranceLeadershipTransferToNonvoter(t *testing.T) {
	const (
		op      = "leadership-transfer-to-nonvoter"
		cluster = "c1"
	)

	ids := []ServerID{"n1", "n2", "n3", "n4"}
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
			assuranceTransferEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(id), "detail": "bootstrap: " + err.Error()})
			t.Fatalf("assurance: bootstrap %s: %v", id, err)
		}
		r, err := NewRaft(conf, assuranceTransferFSM{}, logStore, stableStore, snapStore, trans[i])
		if err != nil {
			assuranceTransferEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(id), "detail": "NewRaft: " + err.Error()})
			t.Fatalf("assurance: NewRaft %s: %v", id, err)
		}
		rafts[i] = r
		defer func(r *Raft) { r.Shutdown().Error() }(r)
	}

	leaderIdx := -1
	waitUntil := time.Now().Add(5 * time.Second)
	for leaderIdx < 0 {
		for i, id := range ids {
			if id == "n4" {
				continue
			}
			if rafts[i].State() == Leader {
				leaderIdx = i
			}
		}
		if time.Now().After(waitUntil) {
			assuranceTransferEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "detail": "no leader elected"})
			t.Fatalf("assurance: no leader elected")
		}
		time.Sleep(10 * time.Millisecond)
	}
	leader := rafts[leaderIdx]
	if err := leader.Barrier(3 * time.Second).Error(); err != nil {
		assuranceTransferEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(ids[leaderIdx]), "detail": "barrier: " + err.Error()})
		t.Fatalf("assurance: barrier: %v", err)
	}
	// Let the leader replicate to the non-voter so the transfer has work to do.
	time.Sleep(300 * time.Millisecond)

	// Lengthen every server's election timeout through the library's own
	// configuration reload, so the voting servers do not start elections of
	// their own while the non-voter campaigns.
	for i, id := range ids {
		if err := rafts[i].ReloadConfig(ReloadableConfig{
			HeartbeatTimeout:    500 * time.Millisecond,
			ElectionTimeout:     30 * time.Second,
			SnapshotInterval:    time.Hour,
			SnapshotThreshold:   100000,
			TrailingLogs:        100000,
		}); err != nil {
			assuranceTransferEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(id), "detail": "reload config: " + err.Error()})
			t.Fatalf("assurance: reload config %s: %v", id, err)
		}
	}
	time.Sleep(100 * time.Millisecond)

	assuranceTransferEvent(map[string]interface{}{
		"event":            "transfer_requested",
		"cluster":          cluster,
		"op":               op,
		"node":             string(ids[leaderIdx]),
		"term":             leader.CurrentTerm(),
		"target":           "n4",
		"target_suffrage":  "Nonvoter",
		"voters":           3,
		"nonvoters":        1,
		"leader_state":     leader.State().String(),
		"target_state":     rafts[3].State().String(),
	})

	type outcome struct {
		result string
		err    error
	}
	done := make(chan outcome, 1)
	go func() {
		err := leader.LeadershipTransferToServer(ServerID("n4"), addrs[3]).Error()
		if err != nil {
			done <- outcome{result: "error", err: err}
			return
		}
		done <- outcome{result: "success"}
	}()
	out := outcome{result: "unfinished"}
	select {
	case out = <-done:
	case <-time.After(4 * time.Second):
		out = outcome{result: "unfinished"}
	}

	// Give the target the election window it would need, sampling its state so
	// a transient leadership is not missed by a single final read.
	sequence := []string{rafts[3].State().String()}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		state := rafts[3].State().String()
		if state != sequence[len(sequence)-1] {
			sequence = append(sequence, state)
		}
		time.Sleep(10 * time.Millisecond)
	}

	detail := ""
	if out.err != nil {
		detail = out.err.Error()
	}
	becameLeader := rafts[3].State() == Leader
	assuranceTransferEvent(map[string]interface{}{
		"event":              "transfer_observed",
		"cluster":            cluster,
		"op":                 op,
		"node":               "n4",
		"target_suffrage":    "Nonvoter",
		"voters":             3,
		"nonvoters":          1,
		"transfer_result":    out.result,
		"transfer_error":     detail,
		"target_state":       rafts[3].State().String(),
		"target_state_sequence": sequence,
		"target_term":        rafts[3].CurrentTerm(),
		"target_became_leader": becameLeader,
		"source_state":       leader.State().String(),
	})
}
