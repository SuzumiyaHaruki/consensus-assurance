// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated assurance harness. One node acts as the source of a committed
// snapshot and a second node installs that snapshot through the module's own
// InstallSnapshot path; the harness then records the index the installing node
// reports as its commit index beside the index the snapshot established and the
// index the node reports as applied and last. It reports raw fields only.

package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

func assuranceSnapEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

type assuranceSnapFSM struct{}

func (assuranceSnapFSM) Apply(*Log) interface{}         { return nil }
func (assuranceSnapFSM) Snapshot() (FSMSnapshot, error) { return assuranceSnapSnapshot{}, nil }
func (assuranceSnapFSM) Restore(rc io.ReadCloser) error { return rc.Close() }

type assuranceSnapSnapshot struct{}

func (assuranceSnapSnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceSnapSnapshot) Release()                     {}

func TestAssuranceSnapshotInstalledCommitContext(t *testing.T) {
	const (
		op      = "snapshot-installed-commit-context"
		cluster = "c1"
		srcID   = ServerID("n1")
		rcvID   = ServerID("n2")
	)

	// ---- Source node: a single-voter leader that commits entries and then
	// takes a snapshot, so the snapshot index is an index the source itself
	// reported as committed and applied.
	srcAddr, srcTrans := NewInmemTransport(ServerAddress("n1"))
	srcSnaps := NewInmemSnapshotStore()
	srcLog := NewInmemStore()
	srcStable := NewInmemStore()
	srcConf := DefaultConfig()
	srcConf.LocalID = srcID
	srcConf.ProtocolVersion = 3
	srcConf.LogLevel = "ERROR"
	srcConf.SnapshotInterval = time.Hour
	srcConf.SnapshotThreshold = 100000
	srcConf.TrailingLogs = 100000
	srcCfg := Configuration{Servers: []Server{{ID: srcID, Address: srcAddr, Suffrage: Voter}}}
	if err := BootstrapCluster(srcConf, srcLog, srcStable, srcSnaps, srcTrans, srcCfg); err != nil {
		assuranceSnapEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(srcID), "detail": "bootstrap source: " + err.Error()})
		t.Fatalf("assurance: bootstrap source: %v", err)
	}
	src, err := NewRaft(srcConf, assuranceSnapFSM{}, srcLog, srcStable, srcSnaps, srcTrans)
	if err != nil {
		assuranceSnapEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(srcID), "detail": "NewRaft source: " + err.Error()})
		t.Fatalf("assurance: NewRaft source: %v", err)
	}
	defer func() { src.Shutdown().Error() }()

	waitUntil := time.Now().Add(5 * time.Second)
	for src.State() != Leader {
		if time.Now().After(waitUntil) {
			assuranceSnapEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(srcID), "detail": "source never became leader"})
			t.Fatalf("assurance: source never became leader")
		}
		time.Sleep(5 * time.Millisecond)
	}
	for i := 0; i < 40; i++ {
		if err := src.Apply([]byte("entry"), 2*time.Second).Error(); err != nil {
			assuranceSnapEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(srcID), "detail": fmt.Sprintf("apply %d: %v", i, err)})
			t.Fatalf("assurance: apply %d: %v", i, err)
		}
	}
	if err := src.Barrier(3 * time.Second).Error(); err != nil {
		assuranceSnapEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(srcID), "detail": "barrier: " + err.Error()})
		t.Fatalf("assurance: barrier: %v", err)
	}
	if err := src.Snapshot().Error(); err != nil {
		assuranceSnapEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(srcID), "detail": "snapshot: " + err.Error()})
		t.Fatalf("assurance: snapshot: %v", err)
	}
	metas, err := srcSnaps.List()
	if err != nil || len(metas) == 0 {
		assuranceSnapEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(srcID), "detail": fmt.Sprintf("no snapshot produced (err=%v, n=%d)", err, len(metas))})
		t.Fatalf("assurance: no snapshot produced: %v", err)
	}
	meta := metas[0]
	_, reader, err := srcSnaps.Open(meta.ID)
	if err != nil {
		assuranceSnapEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(srcID), "detail": "open snapshot: " + err.Error()})
		t.Fatalf("assurance: open snapshot: %v", err)
	}
	defer reader.Close()

	assuranceSnapEvent(map[string]interface{}{
		"event":                "snapshot_committed_at_source",
		"cluster":              cluster,
		"op":                   op,
		"node":                 string(srcID),
		"index":                meta.Index,
		"term":                 meta.Term,
		"source_commit_index":  src.CommitIndex(),
		"source_applied_index": src.AppliedIndex(),
		"source_last_index":    src.LastIndex(),
	})

	// ---- Receiving node: a voter in the source cluster that installs the
	// snapshot. Its own election timeouts are long, so nothing but the
	// InstallSnapshot RPC below changes its state during the observation.
	rcvAddr, rcvTrans := NewInmemTransport(ServerAddress("n2"))
	rcvLog := NewInmemStore()
	rcvStable := NewInmemStore()
	rcvSnaps := NewInmemSnapshotStore()
	rcvConf := DefaultConfig()
	rcvConf.LocalID = rcvID
	rcvConf.ProtocolVersion = 3
	rcvConf.LogLevel = "ERROR"
	rcvConf.HeartbeatTimeout = 5 * time.Second
	rcvConf.ElectionTimeout = 5 * time.Second
	rcvConf.LeaderLeaseTimeout = 5 * time.Second
	rcvConf.CommitTimeout = 5 * time.Second
	rcvConf.SnapshotInterval = time.Hour
	rcvConf.SnapshotThreshold = 100000
	rcvCfg := Configuration{Servers: []Server{
		{ID: srcID, Address: srcAddr, Suffrage: Voter},
		{ID: rcvID, Address: rcvAddr, Suffrage: Voter},
	}}
	if err := BootstrapCluster(rcvConf, rcvLog, rcvStable, rcvSnaps, rcvTrans, rcvCfg); err != nil {
		assuranceSnapEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(rcvID), "detail": "bootstrap receiver: " + err.Error()})
		t.Fatalf("assurance: bootstrap receiver: %v", err)
	}
	rcv, err := NewRaft(rcvConf, assuranceSnapFSM{}, rcvLog, rcvStable, rcvSnaps, rcvTrans)
	if err != nil {
		assuranceSnapEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(rcvID), "detail": "NewRaft receiver: " + err.Error()})
		t.Fatalf("assurance: NewRaft receiver: %v", err)
	}
	defer func() { rcv.Shutdown().Error() }()

	// Route only this one RPC from the source transport to the receiver, so no
	// AppendEntries follows the install inside the observed prefix.
	srcTrans.Connect(rcvAddr, rcvTrans)

	req := &InstallSnapshotRequest{
		RPCHeader:          RPCHeader{ProtocolVersion: 3, ID: []byte(srcID), Addr: srcTrans.EncodePeer(srcID, srcAddr)},
		SnapshotVersion:    meta.Version,
		Term:               meta.Term,
		Leader:             srcTrans.EncodePeer(srcID, srcAddr),
		LastLogIndex:       meta.Index,
		LastLogTerm:        meta.Term,
		Configuration:      EncodeConfiguration(meta.Configuration),
		ConfigurationIndex: meta.ConfigurationIndex,
		Size:               meta.Size,
	}
	var resp InstallSnapshotResponse
	if err := srcTrans.InstallSnapshot(srcID, rcvAddr, req, &resp, reader); err != nil {
		assuranceSnapEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(rcvID), "detail": "install snapshot: " + err.Error()})
		t.Fatalf("assurance: install snapshot: %v", err)
	}
	assuranceSnapEvent(map[string]interface{}{
		"event":         "snapshot_installed",
		"cluster":       cluster,
		"op":            op,
		"node":          string(rcvID),
		"installed":     resp.Success,
		"term":          resp.Term,
		"request_index": meta.Index,
	})

	// Let the asynchronous FSM restore settle before reading the context.
	time.Sleep(200 * time.Millisecond)
	stats := rcv.Stats()
	assuranceSnapEvent(map[string]interface{}{
		"event":          "commit_context_observed",
		"cluster":        cluster,
		"op":             op,
		"node":           string(rcvID),
		"installed":      resp.Success,
		"snapshot_index": meta.Index,
		"commit_index":   rcv.CommitIndex(),
		"applied_index":  rcv.AppliedIndex(),
		"last_index":     rcv.LastIndex(),
		"stats_commit":   stats["commit_index"],
		"stats_applied":  stats["applied_index"],
		"stats_last_log_index":   stats["last_log_index"],
		"stats_last_snapshot_index": stats["last_snapshot_index"],
		"stats_last_log_term":    stats["last_log_term"],
		"node_state":     rcv.State().String(),
	})
}
