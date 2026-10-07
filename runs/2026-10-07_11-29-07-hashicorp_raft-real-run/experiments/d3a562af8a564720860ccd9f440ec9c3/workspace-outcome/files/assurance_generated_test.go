// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated assurance harness. A single node commits entries, takes a snapshot
// and is shut down; the node is then constructed again over the same stores so
// the library restores that snapshot at startup. The harness records the index
// the restarted node publishes as its commit index beside the snapshot it
// restored and the indexes it reports as applied and last. It reports raw
// fields only.

package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"strconv"
	"testing"
	"time"
)

func assuranceRestoreEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

type assuranceRestoreFSM struct{}

func (assuranceRestoreFSM) Apply(*Log) interface{}         { return nil }
func (assuranceRestoreFSM) Snapshot() (FSMSnapshot, error) { return assuranceRestoreSnapshot{}, nil }
func (assuranceRestoreFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceRestoreSnapshot struct{}

func (assuranceRestoreSnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceRestoreSnapshot) Release()                     {}

func TestAssuranceRestoreCommitContext(t *testing.T) {
	const (
		op      = "restart-restore-commit-context"
		cluster = "c1"
		node    = ServerID("n1")
	)

	// The stores outlive the Raft instance, so the restart restores the state
	// the first instance left behind.
	logStore := NewInmemStore()
	stableStore := NewInmemStore()
	snapStore := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport(ServerAddress("n1"))

	conf := DefaultConfig()
	conf.LocalID = node
	conf.ProtocolVersion = 3
	conf.LogLevel = "ERROR"
	conf.SnapshotInterval = time.Hour
	conf.SnapshotThreshold = 100000
	conf.TrailingLogs = 100000
	cfg := Configuration{Servers: []Server{{ID: node, Address: addr, Suffrage: Voter}}}
	if err := BootstrapCluster(conf, logStore, stableStore, snapStore, trans, cfg); err != nil {
		assuranceRestoreEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(node), "detail": "bootstrap: " + err.Error()})
		t.Fatalf("assurance: bootstrap: %v", err)
	}
	r, err := NewRaft(conf, assuranceRestoreFSM{}, logStore, stableStore, snapStore, trans)
	if err != nil {
		assuranceRestoreEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(node), "detail": "NewRaft: " + err.Error()})
		t.Fatalf("assurance: NewRaft: %v", err)
	}

	waitUntil := time.Now().Add(5 * time.Second)
	for r.State() != Leader {
		if time.Now().After(waitUntil) {
			assuranceRestoreEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(node), "detail": "node never became leader"})
			t.Fatalf("assurance: node never became leader")
		}
		time.Sleep(5 * time.Millisecond)
	}
	for i := 0; i < 40; i++ {
		if err := r.Apply([]byte("entry"), 2*time.Second).Error(); err != nil {
			assuranceRestoreEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(node), "detail": fmt.Sprintf("apply %d: %v", i, err)})
			t.Fatalf("assurance: apply %d: %v", i, err)
		}
	}
	if err := r.Barrier(3 * time.Second).Error(); err != nil {
		assuranceRestoreEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(node), "detail": "barrier: " + err.Error()})
		t.Fatalf("assurance: barrier: %v", err)
	}
	if err := r.Snapshot().Error(); err != nil {
		assuranceRestoreEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(node), "detail": "snapshot: " + err.Error()})
		t.Fatalf("assurance: snapshot: %v", err)
	}
	metas, err := snapStore.List()
	if err != nil || len(metas) == 0 {
		assuranceRestoreEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(node), "detail": fmt.Sprintf("no snapshot produced (err=%v, n=%d)", err, len(metas))})
		t.Fatalf("assurance: no snapshot produced: %v", err)
	}
	meta := metas[0]
	assuranceRestoreEvent(map[string]interface{}{
		"event":          "snapshot_committed_before_restart",
		"cluster":        cluster,
		"op":             op,
		"node":           string(node),
		"index":          meta.Index,
		"term":           meta.Term,
		"commit_index":   r.CommitIndex(),
		"applied_index":  r.AppliedIndex(),
		"last_index":     r.LastIndex(),
	})
	if err := r.Shutdown().Error(); err != nil {
		assuranceRestoreEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(node), "detail": "shutdown: " + err.Error()})
		t.Fatalf("assurance: shutdown: %v", err)
	}

	// Construct the node again over the same stores. The election timers are
	// long only so that nothing campaigns before the context is read.
	restartConf := DefaultConfig()
	restartConf.LocalID = node
	restartConf.ProtocolVersion = 3
	restartConf.LogLevel = "ERROR"
	restartConf.HeartbeatTimeout = 5 * time.Second
	restartConf.ElectionTimeout = 5 * time.Second
	restartConf.LeaderLeaseTimeout = 5 * time.Second
	restartConf.CommitTimeout = 5 * time.Second
	restartConf.SnapshotInterval = time.Hour
	restartConf.SnapshotThreshold = 100000
	restartConf.TrailingLogs = 100000
	_, restartTrans := NewInmemTransport(ServerAddress("n1"))
	restarted, err := NewRaft(restartConf, assuranceRestoreFSM{}, logStore, stableStore, snapStore, restartTrans)
	if err != nil {
		assuranceRestoreEvent(map[string]interface{}{"event": "assurance_setup_failed", "cluster": cluster, "op": op, "node": string(node), "detail": "restart NewRaft: " + err.Error()})
		t.Fatalf("assurance: restart NewRaft: %v", err)
	}
	defer func() { restarted.Shutdown().Error() }()

	stats := restarted.Stats()
	restored := stats["last_snapshot_index"] == strconv.FormatUint(meta.Index, 10)
	assuranceRestoreEvent(map[string]interface{}{
		"event":                "restore_context_observed",
		"cluster":              cluster,
		"op":                   op,
		"node":                 string(node),
		"restored":             restored,
		"snapshot_index":       meta.Index,
		"last_snapshot_index":  stats["last_snapshot_index"],
		"commit_index":         restarted.CommitIndex(),
		"applied_index":        restarted.AppliedIndex(),
		"last_index":           restarted.LastIndex(),
		"stats_commit":         stats["commit_index"],
		"stats_applied":        stats["applied_index"],
		"node_state":           restarted.State().String(),
	})
}
