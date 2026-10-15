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

type staleElectNode struct {
	id     ServerID
	trans  *InmemTransport
	logs   *InmemCommitTrackingStore
	stable *InmemStore
	snaps  *InmemSnapshotStore
	raft   *Raft
}

func staleElectEmit(fields map[string]interface{}) {
	b, err := json.Marshal(fields)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func staleElectIDs(c Configuration) string {
	ids := make([]string, 0, len(c.Servers))
	for _, s := range c.Servers {
		ids = append(ids, string(s.ID))
	}
	sort.Strings(ids)
	return strings.Join(ids, ",")
}

func staleElectStates(nodes map[ServerID]*staleElectNode, ids []ServerID) (string, []string) {
	leaders := []string{}
	terms := []string{}
	for _, id := range ids {
		r := nodes[id].raft
		if r == nil {
			continue
		}
		if r.State() == Leader {
			leaders = append(leaders, string(id))
		}
		terms = append(terms, fmt.Sprintf("%s:%d", id, r.getCurrentTerm()))
	}
	sort.Strings(leaders)
	return strings.Join(leaders, ","), terms
}

func staleElectConfigIDs(r *Raft) string {
	if r == nil {
		return ""
	}
	f := r.GetConfiguration()
	if err := f.Error(); err != nil {
		return ""
	}
	return staleElectIDs(f.Configuration())
}

// TestAssuranceStaleConfigElectionWitness grows a real 5-node in-memory cluster,
// leaves node A's snapshot behind a committed configuration change, restarts A with
// RestoreCommittedLogs, partitions {A,C} from {B,D,E} and observes whether the
// stale-configured node becomes leader with fewer votes than the current
// configuration requires while the other partition elects its own leader.
func TestAssuranceStaleConfigElectionWitness(t *testing.T) {
	const mode = "defect_restart"
	ids := []ServerID{"A", "B", "C", "D", "E"}

	newConf := func(id ServerID, restoreCommitted bool) *Config {
		c := DefaultConfig()
		c.LocalID = id
		c.HeartbeatTimeout = 50 * time.Millisecond
		c.ElectionTimeout = 50 * time.Millisecond
		c.LeaderLeaseTimeout = 50 * time.Millisecond
		c.CommitTimeout = 5 * time.Millisecond
		c.SnapshotInterval = 10 * time.Minute
		c.TrailingLogs = 0
		c.Logger = hclog.NewNullLogger()
		c.RestoreCommittedLogs = restoreCommitted
		return c
	}

	nodes := map[ServerID]*staleElectNode{}
	for _, id := range ids {
		_, tr := NewInmemTransport(ServerAddress(id))
		nodes[id] = &staleElectNode{
			id:     id,
			trans:  tr,
			logs:   NewInmemCommitTrackingStore(),
			stable: NewInmemStore(),
			snaps:  NewInmemSnapshotStore(),
		}
	}
	connect := func(a, b ServerID) {
		nodes[a].trans.Connect(ServerAddress(b), nodes[b].trans)
		nodes[b].trans.Connect(ServerAddress(a), nodes[a].trans)
	}
	for i := range ids {
		for j := range ids {
			if i != j {
				connect(ids[i], ids[j])
			}
		}
	}
	cut := func(a, b ServerID) {
		nodes[a].trans.Disconnect(ServerAddress(b))
		nodes[b].trans.Disconnect(ServerAddress(a))
	}

	start := func(id ServerID, restoreCommitted bool) *Raft {
		n := nodes[id]
		r, err := NewRaft(newConf(id, restoreCommitted), new(MockFSM), n.logs, n.stable, n.snaps, n.trans)
		if err != nil {
			t.Fatalf("%s: NewRaft: %v", id, err)
		}
		n.raft = r
		return r
	}

	// Cluster starts as {A,B,C} bootstrapped from A.
	cfgABC := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "A", Address: "A"},
		{Suffrage: Voter, ID: "B", Address: "B"},
		{Suffrage: Voter, ID: "C", Address: "C"},
	}}
	bootConf := newConf("A", false)
	if err := BootstrapCluster(bootConf, nodes["A"].logs, nodes["A"].stable, nodes["A"].snaps, nodes["A"].trans, cfgABC); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	start("A", true)
	start("B", true)
	start("C", true)

	waitLeader := func(candidates []ServerID, d time.Duration) ServerID {
		deadline := time.Now().Add(d)
		for time.Now().Before(deadline) {
			for _, id := range candidates {
				if r := nodes[id].raft; r != nil && r.State() == Leader {
					return id
				}
			}
			time.Sleep(10 * time.Millisecond)
		}
		return ""
	}

	if first := waitLeader([]ServerID{"A", "B", "C"}, 10*time.Second); first == "" {
		t.Fatalf("no initial leader")
	}
	rA := nodes["A"].raft
	if rA.State() != Leader {
		// Transfer leadership to A so that the snapshot and the stale restart are A's.
		lid := waitLeader([]ServerID{"B", "C"}, 10*time.Second)
		if lid != "" {
			f := nodes[lid].raft.LeadershipTransferToServer("A", "A")
			_ = f.Error()
		}
		if deadline := time.Now().Add(10 * time.Second); !time.Now().After(deadline) {
			for time.Now().Before(deadline) && rA.State() != Leader {
				time.Sleep(10 * time.Millisecond)
			}
		}
	}

	// Commit a few entries, then snapshot A so that A's snapshot records {A,B,C}.
	for i := 0; i < 3; i++ {
		f := rA.Apply([]byte(fmt.Sprintf("pre-%d", i)), 3*time.Second)
		if err := f.Error(); err != nil {
			t.Fatalf("pre apply: %v", err)
		}
	}
	// Wait for the followers to have applied the entries.
	barrier := rA.Barrier(3 * time.Second)
	if err := barrier.Error(); err != nil {
		t.Fatalf("barrier: %v", err)
	}
	snapF := rA.Snapshot()
	if err := snapF.Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	snapList, _ := nodes["A"].snaps.List()
	if len(snapList) == 0 {
		t.Fatalf("no snapshot on A")
	}
	snapIdx := snapList[0].Index
	snapCfg := staleElectIDs(snapList[0].Configuration)

	// Bring D and E up as empty followers and add them as voters through the leader.
	start("D", true)
	start("E", true)
	for _, id := range []ServerID{"D", "E"} {
		f := rA.AddVoter(id, ServerAddress(id), 0, 5*time.Second)
		if err := f.Error(); err != nil {
			t.Fatalf("AddVoter %s: %v", id, err)
		}
	}
	// One more committed entry so that every follower stages a commit index at or
	// above the new configuration entry.
	f := rA.Apply([]byte("after-config"), 3*time.Second)
	if err := f.Error(); err != nil {
		t.Fatalf("after-config apply: %v", err)
	}

	// Locate the newest configuration entry in A's log.
	lastLogIdx, _ := nodes["A"].logs.LastIndex()
	var cfgEntryIdx uint64
	var cfgEntryIDs string
	for i := uint64(1); i <= lastLogIdx; i++ {
		var l Log
		if err := nodes["A"].logs.GetLog(i, &l); err != nil || l.Type != LogConfiguration {
			continue
		}
		cfgEntryIdx = i
		cfgEntryIDs = staleElectIDs(DecodeConfiguration(l.Data))
	}
	storedCommit, _ := nodes["A"].logs.GetCommitIndex()

	staleElectEmit(map[string]interface{}{
		"event":                        "fixture",
		"mode":                         mode,
		"local_id":                     "A",
		"snapshot_index":               snapIdx,
		"snapshot_config_ids":          snapCfg,
		"config_entry_index":           cfgEntryIdx,
		"config_entry_ids":             cfgEntryIDs,
		"stored_commit_index":          storedCommit,
		"log_last_index":               lastLogIdx,
		"a_reported_config_ids":        staleElectConfigIDs(rA),
		"cluster_voter_ids":            "A,B,C,D,E",
		"commit_covers_config_entry":   storedCommit >= cfgEntryIdx,
		"snapshot_before_config_entry": cfgEntryIdx > snapIdx,
	})

	// A goes down; the partition is cut while it is down, then A is restarted with
	// RestoreCommittedLogs and only its link to C restored.
	if sf := rA.Shutdown(); sf != nil {
		_ = sf.Error()
	}
	for _, p := range []ServerID{"B", "D", "E"} {
		cut("A", p)
		cut("C", p)
	}
	_, newTransA := NewInmemTransport(ServerAddress("A"))
	nodes["A"].trans = newTransA
	connect("A", "C")
	// A's links to the majority partition stay closed: connect only A and C.
	newTransA.Disconnect("B")
	newTransA.Disconnect("D")
	newTransA.Disconnect("E")

	restarted := start("A", true)
	restartCfg := staleElectConfigIDs(restarted)
	staleElectEmit(map[string]interface{}{
		"event":               "restart",
		"mode":                mode,
		"local_id":            "A",
		"state":               restarted.State().String(),
		"reported_config_ids": restartCfg,
		"last_applied":        restarted.getLastApplied(),
		"config_entry_ids":    cfgEntryIDs,
		"stored_commit_index": storedCommit,
	})

	// Both partitions try to elect.
	minorityLeader := waitLeader([]ServerID{"A", "C"}, 15*time.Second)
	majorityLeader := waitLeader([]ServerID{"B", "D", "E"}, 15*time.Second)
	time.Sleep(500 * time.Millisecond)

	minorityLeaders, minorityTerms := staleElectStates(nodes, []ServerID{"A", "C"})
	majorityLeaders, majorityTerms := staleElectStates(nodes, []ServerID{"B", "D", "E"})

	// What each side reports as its configuration, and whether writes commit.
	restartCfg = staleElectConfigIDs(restarted)
	cCfg := staleElectConfigIDs(nodes["C"].raft)
	majorityCfg := staleElectConfigIDs(nodes[majorityLeader].raft)
	minorityWriteErr := "none"
	var minorityWriteIndex, majorityWriteIndex uint64
	var minorityWriteTerm, majorityWriteTerm uint64
	if minorityLeader != "" {
		wf := nodes[minorityLeader].raft.Apply([]byte("minority-write"), 3*time.Second)
		if err := wf.Error(); err != nil {
			minorityWriteErr = err.Error()
		} else {
			minorityWriteIndex = wf.Index()
			minorityWriteTerm = nodes[minorityLeader].raft.getCurrentTerm()
		}
	}
	majorityWriteErr := "none"
	if majorityLeader != "" {
		wf := nodes[majorityLeader].raft.Apply([]byte("majority-write"), 3*time.Second)
		if err := wf.Error(); err != nil {
			majorityWriteErr = err.Error()
		} else {
			majorityWriteIndex = wf.Index()
			majorityWriteTerm = nodes[majorityLeader].raft.getCurrentTerm()
		}
	}

	// Compare the entries both leaders committed at that index.
	conflicting := false
	var minorityData, majorityData string
	if minorityWriteIndex > 0 && majorityWriteIndex > 0 {
		var ml, jl Log
		errM := nodes[minorityLeader].logs.GetLog(minorityWriteIndex, &ml)
		errJ := nodes[majorityLeader].logs.GetLog(majorityWriteIndex, &jl)
		if errM == nil && errJ == nil {
			minorityData = string(ml.Data)
			majorityData = string(jl.Data)
			conflicting = minorityWriteIndex == majorityWriteIndex && minorityWriteTerm == majorityWriteTerm &&
				minorityData != majorityData
		}
	}
	leaderCount := 0
	if minorityLeaders != "" {
		leaderCount += len(strings.Split(minorityLeaders, ","))
	}
	if majorityLeaders != "" {
		leaderCount += len(strings.Split(majorityLeaders, ","))
	}

	staleElectEmit(map[string]interface{}{
		"event":                         "outcome",
		"mode":                          mode,
		"local_id":                      "A",
		"minority_partition":            "A,C",
		"minority_leaders":              minorityLeaders,
		"minority_terms":                strings.Join(minorityTerms, ","),
		"majority_leaders":              majorityLeaders,
		"majority_terms":                strings.Join(majorityTerms, ","),
		"leader_count":                  leaderCount,
		"stale_config_node_is_leader":   minorityLeader == "A",
		"correct_config_node_is_leader": minorityLeader == "C",
		"restart_config_ids":            restartCfg,
		"c_config_ids":                  cCfg,
		"majority_config_ids":           majorityCfg,
		"minority_write_error":          minorityWriteErr,
		"majority_write_error":          majorityWriteErr,
		"minority_write_committed":      minorityWriteErr == "none",
		"minority_write_index":          minorityWriteIndex,
		"majority_write_index":          majorityWriteIndex,
		"minority_write_term":           minorityWriteTerm,
		"majority_write_term":           majorityWriteTerm,
		"minority_write_data":           minorityData,
		"majority_write_data":           majorityData,
		"conflicting_commits":           conflicting,
	})

	// Heal the partition: restore the full mesh and let the cluster run on.
	for i := range ids {
		for j := range ids {
			if i != j {
				connect(ids[i], ids[j])
			}
		}
	}
	var loneLeader ServerID
	healDeadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(healDeadline) {
		found := []ServerID{}
		for _, id := range ids {
			if r := nodes[id].raft; r != nil && r.State() == Leader {
				found = append(found, id)
			}
		}
		if len(found) == 1 {
			loneLeader = found[0]
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	postHealErr := "none"
	if loneLeader != "" {
		wf := nodes[loneLeader].raft.Apply([]byte("post-heal"), 5*time.Second)
		if err := wf.Error(); err != nil {
			postHealErr = err.Error()
		}
	}
	time.Sleep(300 * time.Millisecond)

	// What each node now holds at the index both leaders committed at, and which
	// configuration the restarted node uses while the cluster runs on.
	conflictIndex := minorityWriteIndex
	payloads := []string{}
	entryTerms := []string{}
	consistent := true
	var firstPayload string
	lastIndexes := []string{}
	for _, id := range ids {
		n := nodes[id]
		var l Log
		if err := n.logs.GetLog(conflictIndex, &l); err == nil {
			p := string(l.Data)
			if firstPayload == "" {
				firstPayload = p
			} else if p != firstPayload {
				consistent = false
			}
			payloads = append(payloads, fmt.Sprintf("%s:%s", id, p))
			entryTerms = append(entryTerms, fmt.Sprintf("%s:%d", id, l.Term))
		}
		li, _ := n.logs.LastIndex()
		lastIndexes = append(lastIndexes, fmt.Sprintf("%s:%d", id, li))
	}
	var aLastIndex uint64
	if idx, err := nodes["A"].logs.LastIndex(); err == nil {
		aLastIndex = idx
	}
	healedStates, _ := staleElectStates(nodes, ids)
	allTermsEqual := len(entryTerms) > 0
	for _, t := range entryTerms {
		if !strings.HasSuffix(t, fmt.Sprintf(":%d", minorityWriteTerm)) {
			allTermsEqual = false
		}
	}
	leaderCfg := ""
	leaderLastIndex := uint64(0)
	if loneLeader != "" {
		leaderCfg = staleElectConfigIDs(nodes[loneLeader].raft)
		if idx, err := nodes[loneLeader].logs.LastIndex(); err == nil {
			leaderLastIndex = idx
		}
	}
	behind := 0
	for _, id := range ids {
		if idx, err := nodes[id].logs.LastIndex(); err == nil && idx < leaderLastIndex {
			behind++
		}
	}
	// What each node's FSM actually applied for the two conflicting writes.
	appliedWrites := func(r *Raft) string {
		fsm := getMockFSM(r.fsm)
		if fsm == nil {
			return ""
		}
		found := []string{}
		for _, l := range fsm.Logs() {
			switch string(l) {
			case "minority-write", "majority-write":
				found = append(found, string(l))
			}
		}
		sort.Strings(found)
		return strings.Join(found, "+")
	}
	applied := []string{}
	appliedConsistent := true
	firstApplied := ""
	for _, id := range ids {
		w := appliedWrites(nodes[id].raft)
		if firstApplied == "" {
			firstApplied = w
		} else if w != firstApplied {
			appliedConsistent = false
		}
		applied = append(applied, fmt.Sprintf("%s:%s", id, w))
	}
	aApplied := appliedWrites(nodes["A"].raft)
	bApplied := appliedWrites(nodes["B"].raft)
	staleElectEmit(map[string]interface{}{
		"event":                              "healed",
		"mode":                               mode,
		"local_id":                           "A",
		"healed_leaders":                     healedStates,
		"lone_leader":                        string(loneLeader),
		"conflict_index":                     conflictIndex,
		"entry_payloads_at_conflict_index":   strings.Join(payloads, ","),
		"entry_terms_at_conflict_index":      strings.Join(entryTerms, ","),
		"entry_consistent_at_conflict_index": consistent,
		"same_term_conflicting_payload":      !consistent && allTermsEqual,
		"log_last_indexes":                   strings.Join(lastIndexes, ","),
		"a_log_last_index":                   aLastIndex,
		"a_log_advanced_after_heal":          aLastIndex > conflictIndex,
		"a_config_ids_after_heal":            staleElectConfigIDs(nodes["A"].raft),
		"b_config_ids_after_heal":            staleElectConfigIDs(nodes["B"].raft),
		"leader_config_ids_after_heal":       leaderCfg,
		"leader_log_last_index":              leaderLastIndex,
		"nodes_with_log_behind_leader":       behind,
		"fsm_applied_writes":                 strings.Join(applied, ","),
		"fsm_applied_consistent":             appliedConsistent,
		"a_fsm_applied_writes":               aApplied,
		"b_fsm_applied_writes":               bApplied,
		"post_heal_apply_error":              postHealErr,
	})

	// Repair phase: put a node holding the current configuration in charge, take a
	// snapshot on it while A is unreachable so its log is compacted past A, then
	// reconnect A and see whether a snapshot install replaces the divergent entry
	// and applied state.
	repairLeader := ServerID("")
	for _, id := range []ServerID{"B", "D", "E"} {
		if r := nodes[id].raft; r != nil && r.State() == Leader {
			repairLeader = id
			break
		}
	}
	transferred := false
	if repairLeader == "" {
		for _, id := range ids {
			if r := nodes[id].raft; r != nil && r.State() == Leader {
				if f := r.LeadershipTransferToServer("B", "B"); f != nil {
					_ = f.Error()
				}
				transferred = true
				break
			}
		}
		dl := time.Now().Add(10 * time.Second)
		for time.Now().Before(dl) {
			for _, id := range []ServerID{"B", "D", "E"} {
				if r := nodes[id].raft; r != nil && r.State() == Leader {
					repairLeader = id
				}
			}
			if repairLeader != "" {
				break
			}
			time.Sleep(10 * time.Millisecond)
		}
	}
	repairApplies := 0
	snapshotIndex := uint64(0)
	snapshotErr := "none"
	if repairLeader != "" {
		for _, p := range ids {
			if p != "A" {
				cut("A", p)
			}
		}
		for i := 0; i < 10; i++ {
			wf := nodes[repairLeader].raft.Apply([]byte(fmt.Sprintf("repair-%d", i)), 3*time.Second)
			if err := wf.Error(); err != nil {
				snapshotErr = err.Error()
				break
			}
			repairApplies++
		}
		if sf := nodes[repairLeader].raft.Snapshot(); sf != nil {
			if err := sf.Error(); err != nil {
				snapshotErr = err.Error()
			}
		}
		if l, err := nodes[repairLeader].snaps.List(); err == nil && len(l) > 0 {
			snapshotIndex = l[0].Index
		}
		for _, p := range ids {
			if p != "A" {
				connect("A", p)
			}
		}
		// Wait for A to install the snapshot the leader can no longer serve as logs.
		dl := time.Now().Add(15 * time.Second)
		for time.Now().Before(dl) {
			if idx, _ := nodes["A"].raft.getLastSnapshot(); idx >= snapshotIndex && snapshotIndex > 0 {
				break
			}
			time.Sleep(20 * time.Millisecond)
		}
	}
	time.Sleep(300 * time.Millisecond)
	aSnapshotIdx, _ := nodes["A"].raft.getLastSnapshot()
	aAppliedAfter := appliedWrites(nodes["A"].raft)
	repairWrites := []string{}
	repairConsistent := true
	firstRepair := ""
	for _, id := range ids {
		w := appliedWrites(nodes[id].raft)
		if firstRepair == "" {
			firstRepair = w
		} else if w != firstRepair {
			repairConsistent = false
		}
		repairWrites = append(repairWrites, fmt.Sprintf("%s:%s", id, w))
	}
	_, aEntryErr := func() (Log, error) {
		var l Log
		err := nodes["A"].logs.GetLog(conflictIndex, &l)
		return l, err
	}()
	staleElectEmit(map[string]interface{}{
		"event":                               "repaired",
		"mode":                                mode,
		"local_id":                            "A",
		"repair_leader":                       string(repairLeader),
		"leadership_transferred":              transferred,
		"repair_applies":                      repairApplies,
		"repair_snapshot_index":               snapshotIndex,
		"repair_snapshot_error":               snapshotErr,
		"a_last_snapshot_index":               aSnapshotIdx,
		"snapshot_installed_on_a":             snapshotIndex > 0 && aSnapshotIdx >= snapshotIndex,
		"a_fsm_applied_writes_after_snapshot": aAppliedAfter,
		"minority_write_present_on_a_after_snapshot": strings.Contains(aAppliedAfter, "minority-write"),
		"a_config_ids_after_snapshot":                staleElectConfigIDs(nodes["A"].raft),
		"a_conflict_index_entry_missing":             aEntryErr != nil,
		"fsm_applied_writes_after_snapshot":          strings.Join(repairWrites, ","),
		"fsm_applied_consistent_after_snapshot":      repairConsistent,
	})
	for _, id := range ids {
		if r := nodes[id].raft; r != nil {
			if sf := r.Shutdown(); sf != nil {
				_ = sf.Error()
			}
		}
	}
}
