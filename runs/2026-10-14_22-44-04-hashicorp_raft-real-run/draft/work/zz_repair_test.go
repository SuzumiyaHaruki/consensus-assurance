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

func ecrEmit(fields map[string]interface{}) {
	b, err := json.Marshal(fields)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func ecrIDs(c Configuration) string {
	ids := make([]string, 0, len(c.Servers))
	for _, s := range c.Servers {
		ids = append(ids, string(s.ID))
	}
	sort.Strings(ids)
	return strings.Join(ids, ",")
}

// TestAssuranceEmptyConfigurationRepair asks whether the empty configuration a
// RestoreCommittedLogs restart can leave behind is refilled by ordinary
// replication of a later configuration entry, and whether the vote admission
// that the empty configuration allowed is closed again once it is.
func TestAssuranceEmptyConfigurationRepair(t *testing.T) {
	const mode = "empty_configuration_repair"
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
	ecrEmit(map[string]interface{}{
		"event":              "fixture",
		"mode":               mode,
		"local_id":           "A",
		"a_snapshots":        len(snapList),
		"a_staged_commit":    int(stagedCommit),
		"a_log_last_index":   int(lastLog),
		"a_reported_config":  ecrIDs(rafts["A"].getLatestConfiguration()),
		"a_log_config_ids":   ecrIDs(bootCfg),
		"leader":             "B",
		"committed_commands": 10,
	})

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
	// settle cuts the node off and waits long enough (twenty heartbeat timeouts)
	// that it no longer recognises a leader and any election gate has had its
	// chance to fire, so the probe answer reflects the configuration the node
	// holds and not a leader it still remembers.
	settle := func() (campaigning bool, hasLeader bool, state string) {
		isolate()
		deadline := time.Now().Add(1000 * time.Millisecond)
		for time.Now().Before(deadline) {
			if st := rafts["A"].State(); st == Candidate || st == Leader {
				campaigning = true
			}
			time.Sleep(5 * time.Millisecond)
		}
		_, leaderSeen := rafts["A"].LeaderWithID()
		return campaigning, leaderSeen != "", rafts["A"].State().String()
	}

	// probe asks the target for a vote on behalf of the outside candidate P, with
	// a term above the target's and a log level with the target's, so that only
	// the target's view of the configuration can decide the answer.
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

	// Phase 1: the node holds the committed configuration. Isolated (so it knows
	// no leader) it refuses the outside candidate.
	cfgCampaigning, cfgHasLeader, cfgState := settle()
	cfgServers := len(rafts["A"].getLatestConfiguration().Servers)
	cfgIDs := ecrIDs(rafts["A"].getLatestConfiguration())
	granted, reqTerm, respTerm, errStr := probeVote("A")
	ecrEmit(map[string]interface{}{
		"event":                "configured_probe",
		"mode":                 mode,
		"local_id":             "A",
		"configured_servers":   cfgServers,
		"config_ids":           cfgIDs,
		"candidate_id":         "P",
		"candidate_in_config":  strings.Contains(","+cfgIDs+",", ",P,"),
		"has_leader":           cfgHasLeader,
		"campaigning_observed": cfgCampaigning,
		"probe_term":           int(reqTerm),
		"response_term":        int(respTerm),
		"response_granted":     granted,
		"probe_error":          errStr,
		"state":                cfgState,
	})

	// Phase 2: restart with the feature and no snapshot, which leaves the
	// configuration empty, then isolate again and repeat the identical probe.
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
			ecrEmit(map[string]interface{}{"event": "restart_with_feature", "mode": mode, "local_id": "A", "newraft_returned": true, "error": "NewRaft returned an error"})
			t.Fatalf("restart failed")
		}
		rafts["A"] = r
		time.Sleep(300 * time.Millisecond)
		ecrEmit(map[string]interface{}{
			"event":                    "restart_with_feature",
			"mode":                     mode,
			"local_id":                 "A",
			"newraft_returned":         true,
			"state":                    r.State().String(),
			"last_applied":             int(r.getLastApplied()),
			"reported_config_ids":      ecrIDs(r.getLatestConfiguration()),
			"reported_config_list_len": len(r.getLatestConfiguration().Servers),
			"a_log_config_ids":         ecrIDs(bootCfg),
		})
	case <-time.After(10 * time.Second):
		ecrEmit(map[string]interface{}{"event": "restart_with_feature", "mode": mode, "local_id": "A", "newraft_returned": false})
		t.Fatalf("restart did not return")
	}

	emptyCampaigning, emptyHasLeader, emptyState := settle()
	emptyCfgServers := len(rafts["A"].getLatestConfiguration().Servers)
	emptyGranted, emptyReqTerm, emptyRespTerm, emptyErrStr := probeVote("A")
	ecrEmit(map[string]interface{}{
		"event":                "empty_config_probe",
		"mode":                 mode,
		"local_id":             "A",
		"configured_servers":   emptyCfgServers,
		"config_ids":           ecrIDs(rafts["A"].getLatestConfiguration()),
		"candidate_id":         "P",
		"candidate_in_config":  false,
		"has_leader":           emptyHasLeader,
		"campaigning_observed": emptyCampaigning,
		"probe_term":           int(emptyReqTerm),
		"response_term":        int(emptyRespTerm),
		"response_granted":     emptyGranted,
		"probe_error":          emptyErrStr,
		"state":                emptyState,
		"last_applied":         int(rafts["A"].getLastApplied()),
		"a_log_config_ids":     ecrIDs(bootCfg),
	})

	// Phase 3: put the node back in contact with its leader and let the cluster
	// append one ordinary configuration entry, then look at what the node now
	// holds and ask it for the same vote again.
	reconnect()
	changeDeadline := 3 * time.Second
	changeErr := ""
	if f := rafts["B"].AddVoter("D", "D", 0, changeDeadline); f != nil {
		if err := f.Error(); err != nil {
			changeErr = err.Error()
		}
	}
	time.Sleep(600 * time.Millisecond)
	afterIDs := ecrIDs(rafts["A"].getLatestConfiguration())
	ecrEmit(map[string]interface{}{
		"event":              "after_configuration_entry",
		"mode":               mode,
		"local_id":           "A",
		"configured_servers": len(rafts["A"].getLatestConfiguration().Servers),
		"config_ids":         afterIDs,
		"holds_new_member":   strings.Contains(","+afterIDs+",", ",D,"),
		"change_error":       changeErr,
		"a_log_last_index":   int(rafts["A"].LastIndex()),
		"a_staged_commit":    int(mustCommitIndex(logs["A"])),
		"leader_config_ids":  ecrIDs(rafts["B"].getLatestConfiguration()),
		"leader_state":       rafts["B"].State().String(),
		"a_leader":           string(rafts["A"].Leader()),
		"a_state":            rafts["A"].State().String(),
	})

	repairedCampaigning, repairedHasLeader, repairedState := settle()
	repairedCfgServers := len(rafts["A"].getLatestConfiguration().Servers)
	repairedGranted, repairedReqTerm, repairedRespTerm, repairedErrStr := probeVote("A")
	ecrEmit(map[string]interface{}{
		"event":                "repaired_probe",
		"mode":                 mode,
		"local_id":             "A",
		"configured_servers":   repairedCfgServers,
		"config_ids":           ecrIDs(rafts["A"].getLatestConfiguration()),
		"candidate_id":         "P",
		"candidate_in_config":  strings.Contains(","+ecrIDs(rafts["A"].getLatestConfiguration())+",", ",P,"),
		"has_leader":           repairedHasLeader,
		"campaigning_observed": repairedCampaigning,
		"probe_term":           int(repairedReqTerm),
		"response_term":        int(repairedRespTerm),
		"response_granted":     repairedGranted,
		"probe_error":          repairedErrStr,
		"state":                repairedState,
		"a_log_config_ids":     ecrIDs(bootCfg),
	})

	for _, id := range ids {
		if r := rafts[id]; r != nil {
			if sf := r.Shutdown(); sf != nil {
				_ = sf.Error()
			}
		}
	}
}

func mustCommitIndex(s *InmemCommitTrackingStore) uint64 {
	idx, err := s.GetCommitIndex()
	if err != nil {
		return 0
	}
	return idx
}
