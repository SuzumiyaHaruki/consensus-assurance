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

func ecvEmit(fields map[string]interface{}) {
	b, err := json.Marshal(fields)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func ecvIDs(c Configuration) string {
	ids := make([]string, 0, len(c.Servers))
	for _, s := range c.Servers {
		ids = append(ids, string(s.ID))
	}
	sort.Strings(ids)
	return strings.Join(ids, ",")
}

// TestAssuranceEmptyConfigurationVote asks whether a node that came up with an
// empty configuration grants its vote to a candidate that appears in no
// configuration it holds, and whether such a grant can elect a leader the
// cluster's committed configuration would not admit.
func TestAssuranceEmptyConfigurationVote(t *testing.T) {
	const mode = "empty_configuration_vote"
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
	// The probe is a transport whose identity appears in no configuration of the
	// cluster under test. It stands in for a candidate that the committed
	// membership of {A,B,C} does not admit.
	probeAddr, probe := NewInmemTransport(ServerAddress("P"))
	probe.Connect(ServerAddress("A"), trans["A"])
	trans["A"].Connect(probeAddr, probe)

	start := func(id ServerID, restoreCommitted bool) *Raft {
		r, err := NewRaft(newConf(id, restoreCommitted), new(MockFSM), logs[id], stable[id], snaps[id], trans[id])
		if err != nil {
			t.Fatalf("%s: NewRaft: %v", id, err)
		}
		rafts[id] = r
		return r
	}

	bootCfg := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "A", Address: "A"},
		{Suffrage: Voter, ID: "B", Address: "B"},
		{Suffrage: Voter, ID: "C", Address: "C"},
	}}
	if err := BootstrapCluster(newConf("A", true), logs["A"], stable["A"], snaps["A"], trans["A"], bootCfg); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	start("A", true)
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
	if leaderID == "A" {
		if f := rafts["A"].LeadershipTransferToServer("B", "B"); f != nil {
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
	ecvEmit(map[string]interface{}{
		"event":              "fixture",
		"mode":               mode,
		"local_id":           "A",
		"a_snapshots":        len(snapList),
		"a_staged_commit":    int(stagedCommit),
		"a_log_last_index":   int(lastLog),
		"a_reported_config":  ecvIDs(rafts["A"].getLatestConfiguration()),
		"a_log_config_ids":   ecvIDs(bootCfg),
		"leader":             "B",
		"committed_commands": 10,
	})

	// isolate cuts the node off from the rest of the cluster so that the vote it
	// casts cannot be attributed to a leader it still recognises.
	isolate := func() {
		for _, id := range ids {
			if id != "A" {
				trans["A"].Disconnect(ServerAddress(id))
				trans[id].Disconnect("A")
			}
		}
	}
	reconnect := func() {
		for _, id := range ids {
			if id != "A" {
				connect("A", id)
			}
		}
	}

	// probe asks the target for a vote on behalf of the outside candidate P, with
	// a term above the target's and a log at least as up to date as the target's,
	// so that only the target's view of the configuration can decide the answer.
	probeVote := func(target ServerID) (granted bool, reqTerm uint64, respTerm uint64, errStr string) {
		r := rafts[target]
		reqTerm = r.getCurrentTerm() + 1
		lastIdx, lastTerm := r.getLastEntry()
		req := &RequestVoteRequest{
			RPCHeader: RPCHeader{
				ProtocolVersion: ProtocolVersionMax,
				ID:              []byte("P"),
				Addr:            probe.EncodePeer("P", probeAddr),
			},
			Term:         reqTerm,
			Candidate:    probe.EncodePeer("P", probeAddr),
			LastLogIndex: lastIdx,
			LastLogTerm:  lastTerm,
		}
		resp := &RequestVoteResponse{}
		if err := probe.RequestVote("P", ServerAddress(target), req, resp); err != nil {
			return false, reqTerm, 0, err.Error()
		}
		return resp.Granted, reqTerm, resp.Term, ""
	}

	// Phase 1: the node still holds the committed configuration. It is isolated
	// (so it knows no leader) and then asked for a vote by the outside candidate.
	isolate()
	termStart := rafts["A"].getCurrentTerm()
	campaigning := false
	isoDeadline := time.Now().Add(1200 * time.Millisecond)
	for time.Now().Before(isoDeadline) {
		if st := rafts["A"].State(); st == Candidate || st == Leader {
			campaigning = true
		}
		time.Sleep(5 * time.Millisecond)
	}
	_, leaderSeen := rafts["A"].LeaderWithID()
	ecvEmit(map[string]interface{}{
		"event":                "configured_isolated",
		"mode":                 mode,
		"local_id":             "A",
		"configured_servers":   len(rafts["A"].getLatestConfiguration().Servers),
		"config_ids":           ecvIDs(rafts["A"].getLatestConfiguration()),
		"campaigning_observed": campaigning,
		"term_start":           int(termStart),
		"term_end":             int(rafts["A"].getCurrentTerm()),
		"has_leader":           leaderSeen != "",
		"state":                rafts["A"].State().String(),
	})
	cfgServers := len(rafts["A"].getLatestConfiguration().Servers)
	cfgIDs := ecvIDs(rafts["A"].getLatestConfiguration())
	granted, reqTerm, respTerm, errStr := probeVote("A")
	ecvEmit(map[string]interface{}{
		"event":               "configured_probe",
		"mode":                mode,
		"local_id":            "A",
		"configured_servers":  cfgServers,
		"config_ids":          cfgIDs,
		"candidate_id":        "P",
		"candidate_in_config": strings.Contains(","+cfgIDs+",", ",P,"),
		"has_leader":          leaderSeen != "",
		"probe_term":          int(reqTerm),
		"response_term":       int(respTerm),
		"response_granted":    granted,
		"probe_error":         errStr,
		"state":               rafts["A"].State().String(),
		"a_log_config_ids":    ecvIDs(bootCfg),
	})

	// Phase 2: restart the node with Config.RestoreCommittedLogs while it holds no
	// snapshot, which is the shape recorded earlier as leaving the configuration
	// empty. Then isolate it again (so it knows no leader) and repeat the exact
	// same probe.
	if sf := rafts["A"].Shutdown(); sf != nil {
		_ = sf.Error()
	}
	_, newTrans := NewInmemTransport(ServerAddress("A"))
	trans["A"] = newTrans
	reconnect()
	probe.Connect(ServerAddress("A"), newTrans)
	newTrans.Connect(probeAddr, probe)

	done := make(chan *Raft, 1)
	go func() {
		r, err := NewRaft(newConf("A", true), new(MockFSM), logs["A"], stable["A"], snaps["A"], newTrans)
		if err != nil {
			done <- nil
			return
		}
		done <- r
	}()
	select {
	case r := <-done:
		if r == nil {
			ecvEmit(map[string]interface{}{"event": "restart_with_feature", "mode": mode, "local_id": "A", "newraft_returned": true, "error": "NewRaft returned an error"})
			t.Fatalf("restart failed")
		}
		rafts["A"] = r
		time.Sleep(300 * time.Millisecond)
		ecvEmit(map[string]interface{}{
			"event":                    "restart_with_feature",
			"mode":                     mode,
			"local_id":                 "A",
			"newraft_returned":         true,
			"state":                    r.State().String(),
			"last_applied":             int(r.getLastApplied()),
			"reported_config_ids":      ecvIDs(r.getLatestConfiguration()),
			"reported_config_list_len": len(r.getLatestConfiguration().Servers),
			"a_log_config_ids":         ecvIDs(bootCfg),
		})
	case <-time.After(10 * time.Second):
		ecvEmit(map[string]interface{}{"event": "restart_with_feature", "mode": mode, "local_id": "A", "newraft_returned": false})
		t.Fatalf("restart did not return")
	}

	isolate()
	emptyTermStart := rafts["A"].getCurrentTerm()
	emptyCampaigning := false
	emptyDeadline := time.Now().Add(1200 * time.Millisecond)
	for time.Now().Before(emptyDeadline) {
		if st := rafts["A"].State(); st == Candidate || st == Leader {
			emptyCampaigning = true
		}
		time.Sleep(5 * time.Millisecond)
	}
	_, emptyLeaderSeen := rafts["A"].LeaderWithID()
	emptyCfgServers := len(rafts["A"].getLatestConfiguration().Servers)
	emptyCfgIDs := ecvIDs(rafts["A"].getLatestConfiguration())
	emptyGranted, emptyReqTerm, emptyRespTerm, emptyErrStr := probeVote("A")
	ecvEmit(map[string]interface{}{
		"event":                "empty_config_probe",
		"mode":                 mode,
		"local_id":             "A",
		"configured_servers":   emptyCfgServers,
		"config_ids":           emptyCfgIDs,
		"candidate_id":         "P",
		"candidate_in_config":  strings.Contains(","+emptyCfgIDs+",", ",P,"),
		"has_leader":           emptyLeaderSeen != "",
		"campaigning_observed": emptyCampaigning,
		"term_start":           int(emptyTermStart),
		"term_end":             int(rafts["A"].getCurrentTerm()),
		"probe_term":           int(emptyReqTerm),
		"response_term":        int(emptyRespTerm),
		"response_granted":     emptyGranted,
		"probe_error":          emptyErrStr,
		"state":                rafts["A"].State().String(),
		"last_applied":         int(rafts["A"].getLastApplied()),
		"a_log_config_ids":     ecvIDs(bootCfg),
	})

	// Phase 3: give the outside candidate a real Raft instance whose own log
	// records the configuration {A,X}. Its log is a copy of A's log with the
	// bootstrap configuration replaced, so its last entry stays level with A's and
	// the vote cannot be refused for being out of date.
	aLast, err := logs["A"].LastIndex()
	if err != nil {
		t.Fatalf("last index: %v", err)
	}
	xCfg := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "A", Address: "A"},
		{Suffrage: Voter, ID: "X", Address: "X"},
	}}
	xLogs := NewInmemStore()
	xStable := NewInmemStore()
	xConfigIndex := uint64(0)
	firstType := ""
	for i := uint64(1); i <= aLast; i++ {
		var e Log
		if err := logs["A"].GetLog(i, &e); err != nil {
			t.Fatalf("get log %d: %v", i, err)
		}
		if i == 1 {
			firstType = e.Type.String()
		}
		if i == 1 && e.Type == LogConfiguration {
			e = Log{Index: 1, Term: e.Term, Type: LogConfiguration, Data: EncodeConfiguration(xCfg)}
		}
		if e.Type == LogConfiguration {
			xConfigIndex = i
		}
		if err := xLogs.StoreLog(&e); err != nil {
			t.Fatalf("store x log %d: %v", i, err)
		}
	}
	aTerm := rafts["A"].getCurrentTerm()
	if err := xStable.SetUint64(keyCurrentTerm, aTerm); err != nil {
		t.Fatalf("x term: %v", err)
	}
	xSnaps := NewInmemSnapshotStore()
	_, xTrans := NewInmemTransport(ServerAddress("X"))
	xTrans.Connect(ServerAddress("A"), trans["A"])
	trans["A"].Connect(ServerAddress("X"), xTrans)

	xConf := newConf("X", false)
	x, err := NewRaft(xConf, new(MockFSM), xLogs, xStable, xSnaps, xTrans)
	if err != nil {
		t.Fatalf("x: NewRaft: %v", err)
	}
	aIndexBefore := rafts["A"].LastIndex()
	xDeadline := time.Now().Add(6 * time.Second)
	for time.Now().Before(xDeadline) && x.State() != Leader {
		time.Sleep(10 * time.Millisecond)
	}
	time.Sleep(300 * time.Millisecond)
	aLeader, aLeaderID := rafts["A"].LeaderWithID()
	ecvEmit(map[string]interface{}{
		"event":                  "outsider_election",
		"mode":                   mode,
		"local_id":               "A",
		"x_config_ids":           ecvIDs(x.getLatestConfiguration()),
		"x_log_config_index":     int(xConfigIndex),
		"x_log_first_entry_type": firstType,
		"x_log_last_index":       int(aLast),
		"x_state":                x.State().String(),
		"x_term":                 int(x.getCurrentTerm()),
		"x_is_leader":            x.State() == Leader,
		"a_state":                rafts["A"].State().String(),
		"a_term":                 int(rafts["A"].getCurrentTerm()),
		"a_leader":               string(aLeader),
		"a_leader_id":            string(aLeaderID),
		"a_followed_outsider":    rafts["A"].State() == Follower && string(aLeader) == "X",
		"a_config_servers":       len(rafts["A"].getLatestConfiguration().Servers),
		"a_config_ids":           ecvIDs(rafts["A"].getLatestConfiguration()),
		"a_log_config_ids":       ecvIDs(bootCfg),
		"a_log_index_before":     int(aIndexBefore),
		"a_log_index_after":      int(rafts["A"].LastIndex()),
		"legit_leader_state":     rafts["B"].State().String(),
		"legit_leader_id":        "B",
		"legit_leader_term":      int(rafts["B"].getCurrentTerm()),
		"two_leaders_observed":   x.State() == Leader && rafts["B"].State() == Leader,
	})

	if sf := x.Shutdown(); sf != nil {
		_ = sf.Error()
	}
	for _, id := range ids {
		if r := rafts[id]; r != nil {
			if sf := r.Shutdown(); sf != nil {
				_ = sf.Error()
			}
		}
	}
}
