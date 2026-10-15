// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

func noSnapEmit(fields map[string]interface{}) {
	b, err := json.Marshal(fields)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func noSnapIDs(c Configuration) string {
	ids := make([]string, 0, len(c.Servers))
	for _, s := range c.Servers {
		ids = append(ids, string(s.ID))
	}
	sort.Strings(ids)
	return strings.Join(ids, ",")
}

// TestAssuranceNoSnapshotRestartConfiguration asks what configuration a node ends
// up with when it is restarted with Config.RestoreCommittedLogs while it has no
// snapshot at all, so the only record of its membership besides the log is
// nothing, and the log scan is what would normally rebuild it.
func TestAssuranceNoSnapshotRestartConfiguration(t *testing.T) {
	const mode = "no_snapshot_restart"
	ids := []ServerID{"A", "B", "C"}

	newConf := func(id ServerID, restoreCommitted bool) *Config {
		c := DefaultConfig()
		c.LocalID = id
		c.HeartbeatTimeout = 50 * time.Millisecond
		c.ElectionTimeout = 50 * time.Millisecond
		c.LeaderLeaseTimeout = 50 * time.Millisecond
		c.CommitTimeout = 5 * time.Millisecond
		c.SnapshotInterval = 10 * time.Minute
		c.Logger = hclog.NewNullLogger()
		c.RestoreCommittedLogs = restoreCommitted
		return c
	}

	trans := map[ServerID]*InmemTransport{}
	logs := map[ServerID]*InmemCommitTrackingStore{}
	stable := map[ServerID]*InmemStore{}
	snaps := map[ServerID]*InmemSnapshotStore{}
	rafts := map[ServerID]*Raft{}
	for _, id := range ids {
		_, tr := NewInmemTransport(ServerAddress(id))
		trans[id] = tr
		logs[id] = NewInmemCommitTrackingStore()
		stable[id] = NewInmemStore()
		snaps[id] = NewInmemSnapshotStore()
	}
	connect := func(a, b ServerID) {
		trans[a].Connect(ServerAddress(b), trans[b])
		trans[b].Connect(ServerAddress(a), trans[a])
	}
	for i := range ids {
		for j := range ids {
			if i != j {
				connect(ids[i], ids[j])
			}
		}
	}
	start := func(id ServerID, restoreCommitted bool) *Raft {
		r, err := NewRaft(newConf(id, restoreCommitted), new(MockFSM), logs[id], stable[id], snaps[id], trans[id])
		if err != nil {
			t.Fatalf("%s: NewRaft: %v", id, err)
		}
		rafts[id] = r
		return r
	}

	cfg := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "A", Address: "A"},
		{Suffrage: Voter, ID: "B", Address: "B"},
		{Suffrage: Voter, ID: "C", Address: "C"},
	}}
	if err := BootstrapCluster(newConf("A", true), logs["A"], stable["A"], snaps["A"], trans["A"], cfg); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	a := start("A", true)
	start("B", true)
	start("C", true)

	waitLeader := func(candidates []ServerID, d time.Duration) ServerID {
		deadline := time.Now().Add(d)
		for time.Now().Before(deadline) {
			for _, id := range candidates {
				if r := rafts[id]; r != nil && r.State() == Leader {
					return id
				}
			}
			time.Sleep(10 * time.Millisecond)
		}
		return ""
	}
	leaderID := waitLeader(ids, 10*time.Second)
	if leaderID == "" {
		t.Fatalf("no leader")
	}
	// Keep A as a follower so that the restart under test is a follower restart.
	if leaderID == "A" {
		if f := a.LeadershipTransferToServer("B", "B"); f != nil {
			_ = f.Error()
		}
		deadline := time.Now().Add(10 * time.Second)
		for time.Now().Before(deadline) && rafts["B"].State() != Leader {
			time.Sleep(10 * time.Millisecond)
		}
	}
	if rafts["B"].State() != Leader {
		t.Fatalf("B is not leader")
	}

	// Commit entries, including the configuration entry, but take no snapshot on A.
	for i := 0; i < 10; i++ {
		if err := rafts["B"].Apply([]byte(fmt.Sprintf("cmd-%d", i)), 3*time.Second).Error(); err != nil {
			t.Fatalf("apply: %v", err)
		}
	}
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if idx, err := logs["A"].GetCommitIndex(); err == nil && idx > 0 {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	snapList, _ := snaps["A"].List()
	stagedCommit, _ := logs["A"].GetCommitIndex()
	lastLog, _ := logs["A"].LastIndex()
	configBefore := noSnapIDs(a.getLatestConfiguration())

	noSnapEmit(map[string]interface{}{
		"event":              "fixture",
		"mode":               mode,
		"local_id":           "A",
		"a_snapshots":        len(snapList),
		"a_staged_commit":    stagedCommit,
		"a_log_last_index":   lastLog,
		"a_config_before":    configBefore,
		"a_reported_config":  noSnapIDs(a.getLatestConfiguration()),
		"leader":             "B",
		"committed_commands": 10,
	})

	// Restart A from its own stores, once with the feature and once without it.
	attempt := func(name string, restoreCommitted bool, window time.Duration) {
		if sf := rafts["A"].Shutdown(); sf != nil {
			_ = sf.Error()
		}
		_, newTrans := NewInmemTransport(ServerAddress("A"))
		trans["A"] = newTrans
		for _, id := range ids {
			if id != "A" {
				trans[id].Disconnect("A")
				connect("A", id)
			}
		}
		done := make(chan *Raft, 1)
		go func() {
			r, err := NewRaft(newConf("A", restoreCommitted), new(MockFSM), logs["A"], stable["A"], snaps["A"], newTrans)
			if err != nil {
				done <- nil
				return
			}
			done <- r
		}()
		select {
		case r := <-done:
			if r == nil {
				noSnapEmit(map[string]interface{}{"event": name, "mode": mode, "local_id": "A", "newraft_returned": true, "error": "NewRaft returned an error"})
				return
			}
			rafts["A"] = r
			time.Sleep(300 * time.Millisecond)
			noSnapEmit(map[string]interface{}{
				"event":                      name,
				"mode":                       mode,
				"local_id":                   "A",
				"newraft_returned":           true,
				"state":                      r.State().String(),
				"last_applied":               r.getLastApplied(),
				"reported_config_ids":        noSnapIDs(r.getLatestConfiguration()),
				"reported_config_list_len":   len(r.getLatestConfiguration().Servers),
				"total_voters_in_log_config": len(cfg.Servers),
			})
		case <-time.After(window):
			noSnapEmit(map[string]interface{}{"event": name, "mode": mode, "local_id": "A", "newraft_returned": false, "window_ms": window.Milliseconds()})
		}
	}

	attempt("restart_with_feature", true, 10*time.Second)
	attempt("restart_without_feature", false, 10*time.Second)

	for _, id := range ids {
		if r := rafts[id]; r != nil {
			if sf := r.Shutdown(); sf != nil {
				_ = sf.Error()
			}
		}
	}
}
