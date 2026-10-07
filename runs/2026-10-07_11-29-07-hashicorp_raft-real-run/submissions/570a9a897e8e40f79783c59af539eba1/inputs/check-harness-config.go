// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated assurance harness. One node bootstraps a single-voter
// configuration, and the harness compares the index the configuration future
// reports with the log index at which that configuration was established, and
// with the value the same future supplies to Stats. It reports raw fields only.

package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

func assuranceCfgEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

type assuranceCfgFSM struct{}

func (assuranceCfgFSM) Apply(*Log) interface{}         { return nil }
func (assuranceCfgFSM) Snapshot() (FSMSnapshot, error) { return assuranceCfgSnapshot{}, nil }
func (assuranceCfgFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceCfgSnapshot struct{}

func (assuranceCfgSnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceCfgSnapshot) Release()                     {}

func TestAssuranceConfigurationIndexReported(t *testing.T) {
	const (
		op   = "client-visible-configuration-index"
		node = ServerID("n1")
	)

	conf := DefaultConfig()
	conf.LocalID = node
	conf.ProtocolVersion = 3
	conf.LogLevel = "ERROR"
	conf.SnapshotInterval = time.Hour
	conf.SnapshotThreshold = 100000
	conf.TrailingLogs = 100000

	_, trans := NewInmemTransport(ServerAddress(node))
	r, err := NewRaft(conf, assuranceCfgFSM{}, NewInmemStore(), NewInmemStore(), NewInmemSnapshotStore(), trans)
	if err != nil {
		assuranceCfgEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(node), "op": op, "detail": err.Error()})
		t.Fatalf("assurance: NewRaft: %v", err)
	}
	defer func() { r.Shutdown().Error() }()

	configuration := Configuration{Servers: []Server{{ID: node, Address: trans.LocalAddr(), Suffrage: Voter}}}
	if err := r.BootstrapCluster(configuration).Error(); err != nil {
		assuranceCfgEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(node), "op": op, "detail": "bootstrap: " + err.Error()})
		t.Fatalf("assurance: bootstrap: %v", err)
	}

	// The bootstrap configuration entry is the only entry in the log, so the
	// index at which the configuration was established is the log's last index.
	established := r.LastIndex()

	future := r.GetConfiguration()
	if err := future.Error(); err != nil {
		assuranceCfgEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(node), "op": op, "detail": "get configuration: " + err.Error()})
		t.Fatalf("assurance: get configuration: %v", err)
	}
	reported := future.Index()
	returned := future.Configuration()
	statsIndex := r.Stats()["latest_configuration_index"]
	hasSelf, servers := false, len(returned.Servers)
	for _, server := range returned.Servers {
		if server.ID == node && server.Suffrage == Voter {
			hasSelf = true
		}
	}

	assuranceCfgEvent(map[string]interface{}{
		"event":          "configuration_established",
		"node":           string(node),
		"op":             op,
		"index":          established,
		"log_last_index": established,
	})
	assuranceCfgEvent(map[string]interface{}{
		"event":                  "configuration_index_observed",
		"node":                   string(node),
		"op":                     op,
		"reported_index":         reported,
		"stats_index":            statsIndex,
		"log_last_index":         r.LastIndex(),
		"configuration_has_self": hasSelf,
		"servers":                servers,
		"node_state":             r.State().String(),
	})
}
