package raft

import (
	"encoding/json"
	"fmt"
	"sync/atomic"
	"testing"
	"time"
)

// probeEmit writes one CA_EVENT JSON line to the test's stdout stream.
func probeEmit(t *testing.T, event map[string]interface{}) {
	t.Helper()
	payload, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("probe: cannot marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(payload))
}

// probeCountingTransport delegates to a real InmemTransport and counts the election
// RPCs actually sent by the instance under observation. It keeps the WithPreVote
// interface so the observed instance runs with pre-vote enabled.
type probeCountingTransport struct {
	*InmemTransport
	preVotes atomic.Int64
	votes    atomic.Int64
}

func (c *probeCountingTransport) RequestPreVote(id ServerID, target ServerAddress, args *RequestPreVoteRequest, resp *RequestPreVoteResponse) error {
	c.preVotes.Add(1)
	return c.InmemTransport.RequestPreVote(id, target, args, resp)
}

func (c *probeCountingTransport) RequestVote(id ServerID, target ServerAddress, args *RequestVoteRequest, resp *RequestVoteResponse) error {
	c.votes.Add(1)
	return c.InmemTransport.RequestVote(id, target, args, resp)
}

// probeConfigEntries scans the persisted log store for configuration-carrying entries and
// returns the last one together with the number found.
func probeConfigEntries(t *testing.T, logs LogStore, trans Transport) (Log, int) {
	t.Helper()
	first, err := logs.FirstIndex()
	if err != nil {
		t.Fatalf("probe: FirstIndex: %v", err)
	}
	last, err := logs.LastIndex()
	if err != nil {
		t.Fatalf("probe: LastIndex: %v", err)
	}
	var found Log
	var count int
	for i := first; i <= last; i++ {
		var entry Log
		if err := logs.GetLog(i, &entry); err != nil {
			continue
		}
		switch entry.Type {
		case LogConfiguration, LogAddPeerDeprecated, LogRemovePeerDeprecated:
			found = entry
			count++
		}
	}
	if count > 0 && found.Type != LogConfiguration {
		if conf, err := decodePeers(found.Data, trans); err == nil {
			found.Data = EncodeConfiguration(conf)
			found.Type = LogConfiguration
		}
	}
	return found, count
}

func probeDecodeConfig(t *testing.T, entry Log) Configuration {
	t.Helper()
	if entry.Type != LogConfiguration {
		return Configuration{}
	}
	return DecodeConfiguration(entry.Data)
}

func probeVoters(c Configuration) int {
	n := 0
	for _, s := range c.Servers {
		if s.Suffrage == Voter {
			n++
		}
	}
	return n
}

func probeServersJSON(c Configuration) string {
	ids := []string{}
	for _, s := range c.Servers {
		ids = append(ids, fmt.Sprintf("%s:%s", s.ID, s.Suffrage))
	}
	raw, err := json.Marshal(ids)
	if err != nil {
		return "[]"
	}
	return string(raw)
}

type probeCase struct {
	name              string
	peers             int
	restore           bool
	snapshot          bool
	removePeer        bool
	demotePeer        bool
	postRemoveApplies int
	stopPeerForApply  bool
	wait              time.Duration
}

// probeNonLeader returns the instance of the cluster that is not the given one.
func probeNonLeader(c *cluster, other *Raft) *Raft {
	for _, r := range c.rafts {
		if r != other {
			return r
		}
	}
	return nil
}

// probePayload scans a log store for a commit payload and returns whether it is still
// stored together with the index it occupies.
func probePayload(logs LogStore, payload string) (bool, uint64) {
	first, err := logs.FirstIndex()
	if err != nil {
		return false, 0
	}
	last, err := logs.LastIndex()
	if err != nil {
		return false, 0
	}
	for i := first; i <= last; i++ {
		var entry Log
		if err := logs.GetLog(i, &entry); err != nil {
			continue
		}
		if string(entry.Data) == payload {
			return true, entry.Index
		}
	}
	return false, 0
}

// probeRestart rebuilds one instance over its own durable stores and reconnects it, in
// both directions, with the other rebuilt instances.
func probeRestart(t *testing.T, name string, old *Raft, stable StableStore, recordRestore bool, live map[*Raft]*InmemTransport) *Raft {
	t.Helper()
	conf := old.config()
	conf.RestoreCommittedLogs = recordRestore
	addr, inner := NewInmemTransport(old.trans.LocalAddr())
	restarted, err := NewRaft(&conf, old.fsm, old.logs, stable, old.snapshots, inner)
	if err != nil {
		t.Fatalf("probe %s: restart failed: %v", name, err)
	}
	for _, peerTrans := range live {
		inner.Connect(peerTrans.LocalAddr(), peerTrans)
		peerTrans.Connect(addr, inner)
	}
	live[restarted] = inner
	return restarted
}

// probeRunSplitConfigCase partitions the peers of the committed configuration from the
// restarted leader, lets both sides run, and reports whether the cluster ends with two
// leaders and two histories.
func probeRunSplitConfigCase(t *testing.T, restore bool, wait time.Duration) {
	t.Helper()
	scenario := "split_configurations"

	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.RestoreCommittedLogs = restore
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})

	leader := c.Leader()
	leaderIdx := -1
	var victims []*Raft
	var victimIdx []int
	for i, r := range c.rafts {
		if r == leader {
			leaderIdx = i
			continue
		}
		victims = append(victims, r)
		victimIdx = append(victimIdx, i)
	}
	if leaderIdx < 0 || len(victims) != 2 {
		t.Fatalf("probe %s: unexpected cluster shape", scenario)
	}

	for _, victim := range victims {
		if err := leader.DemoteVoter(victim.localID, 0, 0).Error(); err != nil {
			t.Fatalf("probe %s: DemoteVoter failed: %v", scenario, err)
		}
	}
	var future Future
	for i := 0; i < 100; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: apply failed: %v", scenario, err)
	}
	if err := leader.Snapshot().Error(); err != nil {
		t.Fatalf("probe %s: snapshot failed: %v", scenario, err)
	}
	for _, victim := range victims {
		if err := leader.AddVoter(victim.localID, victim.localAddr, 0, 0).Error(); err != nil {
			t.Fatalf("probe %s: AddVoter failed: %v", scenario, err)
		}
	}
	for i := 0; i < 10; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-after-promote-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: post-promote apply failed: %v", scenario, err)
	}

	configEntry, configEntryCount := probeConfigEntries(t, leader.logs, leader.trans)
	logConfig := probeDecodeConfig(t, configEntry)

	// Partition the leader from the other two in both directions, then take it down.
	if leaderTrans, ok := leader.trans.(*InmemTransport); ok {
		for _, victim := range victims {
			if victimTrans, ok := victim.trans.(*InmemTransport); ok {
				leaderTrans.Disconnect(victimTrans.LocalAddr())
				victimTrans.Disconnect(leaderTrans.LocalAddr())
			}
		}
	}
	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("probe %s: leader shutdown failed: %v", scenario, err)
	}

	probeEmit(t, map[string]interface{}{
		"event":                  "split_inputs",
		"scenario":               scenario,
		"restore_committed_logs": restore,
		"log_config_index":       int(configEntry.Index),
		"log_config_count":       configEntryCount,
		"log_config_voters":      probeVoters(logConfig),
		"log_config_servers":     probeServersJSON(logConfig),
	})

	// The restarted former leader keeps only a fresh instance beside it.
	live := map[*Raft]*InmemTransport{}
	restarted := probeRestart(t, scenario, leader, c.stores[leaderIdx], restore, live)
	c.rafts[leaderIdx] = restarted

	newID := ServerID(fmt.Sprintf("server-new-%d", time.Now().UnixNano()))
	newConf := inmemConfig(t)
	newConf.RestoreCommittedLogs = false
	newConf.LocalID = newID
	newAddr, newTrans := NewInmemTransport("")
	newStore := NewInmemStore()
	newLogs := NewInmemCommitTrackingStore()
	_, newSnap := FileSnapTest(t)
	newRaft, err := NewRaft(newConf, &MockFSM{}, newLogs, newStore, newSnap, newTrans)
	if err != nil {
		t.Fatalf("probe %s: new instance failed: %v", scenario, err)
	}
	if leaderTrans, ok := restarted.trans.(*InmemTransport); ok {
		leaderTrans.Connect(newAddr, newTrans)
		newTrans.Connect(restarted.trans.LocalAddr(), leaderTrans)
	}

	firstSideLeader := false
	deadline := time.Now().Add(wait)
	for time.Now().Before(deadline) {
		if restarted.State() == Leader {
			firstSideLeader = true
			break
		}
		time.Sleep(2 * time.Millisecond)
	}
	firstSideConfigVoters := probeVoters(restarted.configurations.latest)
	firstSideTerm := restarted.getCurrentTerm()

	changeErr := ""
	if err := restarted.AddVoter(newID, newAddr, 0, 0).Error(); err != nil {
		changeErr = err.Error()
	}

	// The other two peers keep the committed configuration and elect among themselves.
	secondSideLeader := false
	secondSideTerm := uint64(0)
	var secondLeader *Raft
	deadline = time.Now().Add(wait)
	for time.Now().Before(deadline) {
		for _, victim := range victims {
			if victim.State() == Leader {
				secondSideLeader = true
				secondLeader = victim
				secondSideTerm = victim.getCurrentTerm()
			}
		}
		if secondSideLeader {
			break
		}
		time.Sleep(2 * time.Millisecond)
	}
	if secondLeader == nil {
		secondLeader = victims[0]
	}
	secondSideConfigVoters := probeVoters(secondLeader.configurations.latest)

	// Both sides try to commit, then each side is searched for the other's entry.
	firstPayload := fmt.Sprintf("first-side-%s-%d", scenario, time.Now().UnixNano())
	secondPayload := fmt.Sprintf("second-side-%s-%d", scenario, time.Now().UnixNano())
	firstApplyOK := restarted.Apply([]byte(firstPayload), 1500*time.Millisecond).Error() == nil
	secondApplyOK := secondLeader.Apply([]byte(secondPayload), 1500*time.Millisecond).Error() == nil
	time.Sleep(wait)

	firstHasSecond, _ := probePayload(restarted.logs, secondPayload)
	secondHasFirst := false
	for _, victim := range victims {
		if present, _ := probePayload(victim.logs, firstPayload); present {
			secondHasFirst = true
		}
	}
	secondHasSecond, _ := probePayload(secondLeader.logs, secondPayload)
	firstHasFirst, _ := probePayload(restarted.logs, firstPayload)

	probeEmit(t, map[string]interface{}{
		"event":                     "split_result",
		"scenario":                  scenario,
		"restore_committed_logs":    restore,
		"log_config_voters":         probeVoters(logConfig),
		"first_side_leader":         firstSideLeader,
		"first_side_term":           int(firstSideTerm),
		"first_side_config_voters":  firstSideConfigVoters,
		"first_side_change_error":   changeErr,
		"second_side_leader":        secondSideLeader,
		"second_side_term":          int(secondSideTerm),
		"second_side_config_voters": secondSideConfigVoters,
		"both_sides_leading":        firstSideLeader && secondSideLeader,
		"same_term":                 firstSideTerm == secondSideTerm,
		"first_apply_ok":            firstApplyOK,
		"second_apply_ok":           secondApplyOK,
		"first_has_first":           firstHasFirst,
		"first_has_second":          firstHasSecond,
		"second_has_first":          secondHasFirst,
		"second_has_second":         secondHasSecond,
		"cross_entries_seen":        boolCount(firstHasSecond) + boolCount(secondHasFirst),
		"wait_millis":               int(wait / time.Millisecond),
	})

	newRaft.Shutdown()
	c.Close()
}

func boolCount(v bool) int {
	if v {
		return 1
	}
	return 0
}

// probeRunClientChangeCase issues a client membership change to a node that is leading on
// a reconstructed configuration, then brings the demoted peers back and reports whether
// the change committed and whether they adopted it.
func probeRunClientChangeCase(t *testing.T, restore bool, wait time.Duration) {
	t.Helper()
	scenario := "client_change_on_reconstruction"

	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.RestoreCommittedLogs = restore
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})

	leader := c.Leader()
	leaderIdx := -1
	var victims []*Raft
	var victimIdx []int
	for i, r := range c.rafts {
		if r == leader {
			leaderIdx = i
			continue
		}
		victims = append(victims, r)
		victimIdx = append(victimIdx, i)
	}
	if leaderIdx < 0 || len(victims) != 2 {
		t.Fatalf("probe %s: unexpected cluster shape", scenario)
	}

	// Collapse to one voter, snapshot that configuration, then make three voters again.
	for _, victim := range victims {
		if err := leader.DemoteVoter(victim.localID, 0, 0).Error(); err != nil {
			t.Fatalf("probe %s: DemoteVoter failed: %v", scenario, err)
		}
	}
	var future Future
	for i := 0; i < 100; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: apply failed: %v", scenario, err)
	}
	if err := leader.Snapshot().Error(); err != nil {
		t.Fatalf("probe %s: snapshot failed: %v", scenario, err)
	}
	for _, victim := range victims {
		if err := leader.AddVoter(victim.localID, victim.localAddr, 0, 0).Error(); err != nil {
			t.Fatalf("probe %s: AddVoter failed: %v", scenario, err)
		}
	}
	for i := 0; i < 10; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-after-promote-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: post-promote apply failed: %v", scenario, err)
	}

	configEntry, configEntryCount := probeConfigEntries(t, leader.logs, leader.trans)
	logConfig := probeDecodeConfig(t, configEntry)
	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("probe %s: leader shutdown failed: %v", scenario, err)
	}
	for _, victim := range victims {
		if err := victim.Shutdown().Error(); err != nil {
			t.Fatalf("probe %s: victim shutdown failed: %v", scenario, err)
		}
	}

	probeEmit(t, map[string]interface{}{
		"event":                  "change_inputs",
		"scenario":               scenario,
		"restore_committed_logs": restore,
		"log_config_index":       int(configEntry.Index),
		"log_config_count":       configEntryCount,
		"log_config_voters":      probeVoters(logConfig),
		"log_config_servers":     probeServersJSON(logConfig),
	})

	// Restart only the former leader; the other two stay down for the change.
	live := map[*Raft]*InmemTransport{}
	restarted := probeRestart(t, scenario, leader, c.stores[leaderIdx], restore, live)
	c.rafts[leaderIdx] = restarted

	// A fresh fourth instance, started empty and connected to the restarted leader.
	newID := ServerID(fmt.Sprintf("server-new-%d", time.Now().UnixNano()))
	newConf := inmemConfig(t)
	newConf.RestoreCommittedLogs = false
	newConf.LocalID = newID
	newAddr, newTrans := NewInmemTransport("")
	newStore := NewInmemStore()
	newLogs := NewInmemCommitTrackingStore()
	newDir, newSnap := FileSnapTest(t)
	_ = newDir
	newFSM := &MockFSM{}
	newRaft, err := NewRaft(newConf, newFSM, newLogs, newStore, newSnap, newTrans)
	if err != nil {
		t.Fatalf("probe %s: new instance failed: %v", scenario, err)
	}
	if leaderTrans, ok := restarted.trans.(*InmemTransport); ok {
		leaderTrans.Connect(newAddr, newTrans)
		newTrans.Connect(restarted.trans.LocalAddr(), leaderTrans)
	}

	leaderWasLeader := false
	deadline := time.Now().Add(wait)
	for time.Now().Before(deadline) {
		if restarted.State() == Leader {
			leaderWasLeader = true
			break
		}
		time.Sleep(2 * time.Millisecond)
	}
	beforeVoters := probeVoters(restarted.configurations.latest)

	// The client membership change, computed from whatever configuration the node holds.
	changeErr := ""
	if err := restarted.AddVoter(newID, newAddr, 0, 0).Error(); err != nil {
		changeErr = err.Error()
	}
	time.Sleep(wait)

	changeCommitted := changeErr == ""
	leaderVoters := probeVoters(restarted.configurations.latest)
	leaderServers := probeServersJSON(restarted.configurations.latest)
	newVoters := probeVoters(newRaft.configurations.latest)
	newHasVote := hasVote(restarted.configurations.latest, newID)
	newInReplaced := inConfiguration(logConfig, newID)

	// Bring the demoted peers back with the flag disabled and see what they adopt.
	var rejoiners []*Raft
	for i, victim := range victims {
		rejoined := probeRestart(t, scenario, victim, c.stores[victimIdx[i]], false, live)
		c.rafts[victimIdx[i]] = rejoined
		rejoiners = append(rejoiners, rejoined)
	}
	if lt, ok := restarted.trans.(LoopbackTransport); ok {
		for _, rejoined := range rejoiners {
			if inner, ok := rejoined.trans.(*InmemTransport); ok {
				inner.Connect(lt.LocalAddr(), lt)
				lt.Connect(rejoined.trans.LocalAddr(), inner)
			}
		}
	}
	time.Sleep(wait)
	adopted := 0
	for _, rejoined := range rejoiners {
		rejoinedVoters := probeVoters(rejoined.configurations.latest)
		rejoinedServers := probeServersJSON(rejoined.configurations.latest)
		hasVote := hasVote(rejoined.configurations.latest, rejoined.localID)
		if rejoinedVoters == leaderVoters && rejoinedServers == leaderServers {
			adopted++
		}
		_ = hasVote
	}
	demotedHaveVotes := 0
	for _, rejoined := range rejoiners {
		if hasVote(rejoined.configurations.latest, rejoined.localID) {
			demotedHaveVotes++
		}
	}

	probeEmit(t, map[string]interface{}{
		"event":                       "change_result",
		"scenario":                    scenario,
		"restore_committed_logs":      restore,
		"stale_leader":                leaderWasLeader,
		"reconstructed_config_voters": beforeVoters,
		"replaced_config_voters":      probeVoters(logConfig),
		"change_committed":            changeCommitted,
		"change_error":                changeErr,
		"leader_config_voters":        leaderVoters,
		"leader_config_servers":       leaderServers,
		"new_member_has_vote":         newHasVote,
		"new_member_in_replaced":      newInReplaced,
		"new_member_config_voters":    newVoters,
		"demoted_peers_with_vote":     demotedHaveVotes,
		"demoted_peers_adopted":       adopted,
		"wait_millis":                 int(wait / time.Millisecond),
	})

	newRaft.Shutdown()
	c.Close()
}

// probeRunStaleCampaignCase makes one peer hold a snapshot of the configuration in which it
// was still a voter, removes its vote in the committed configuration, restarts it together
// with one peer that also reconstructs a configuration, and reports whether it campaigns on
// its own and becomes leader with support the committed configuration does not sanction.
func probeRunStaleCampaignCase(t *testing.T, restore bool, wait time.Duration) {
	t.Helper()
	scenario := "stale_campaign_wins"

	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.RestoreCommittedLogs = restore
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})

	leader := c.Leader()
	leaderIdx := -1
	var others []*Raft
	var otherIdx []int
	for i, r := range c.rafts {
		if r == leader {
			leaderIdx = i
			continue
		}
		others = append(others, r)
		otherIdx = append(otherIdx, i)
	}
	if leaderIdx < 0 || len(others) != 2 {
		t.Fatalf("probe %s: unexpected cluster shape", scenario)
	}
	stale, responder := others[0], others[1]

	var future Future
	for i := 0; i < 20; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-pre-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: apply failed: %v", scenario, err)
	}

	// The peer keeps a snapshot of its own view while it is still a voter.
	if err := stale.Snapshot().Error(); err != nil {
		t.Fatalf("probe %s: peer snapshot failed: %v", scenario, err)
	}
	metas, err := stale.snapshots.List()
	if err != nil || len(metas) == 0 {
		t.Fatalf("probe %s: no snapshot meta on the peer: %v", scenario, err)
	}
	snapshotConfigIndex := metas[0].ConfigurationIndex
	snapshotVoters := probeVoters(metas[0].Configuration)

	// Remove that peer's vote from the committed configuration.
	if err := leader.DemoteVoter(stale.localID, 0, 0).Error(); err != nil {
		t.Fatalf("probe %s: DemoteVoter failed: %v", scenario, err)
	}
	for i := 0; i < 10; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-post-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: post-demote apply failed: %v", scenario, err)
	}

	configEntry, configEntryCount := probeConfigEntries(t, stale.logs, stale.trans)
	logConfig := probeDecodeConfig(t, configEntry)
	store, ok := stale.logs.(CommitTrackingLogStore)
	if !ok {
		t.Fatalf("probe %s: log store does not track commits", scenario)
	}
	stagedCommitIndex, err := store.GetCommitIndex()
	if err != nil {
		t.Fatalf("probe %s: GetCommitIndex: %v", scenario, err)
	}

	probeEmit(t, map[string]interface{}{
		"event":                   "campaign_inputs",
		"scenario":                scenario,
		"restore_committed_logs":  restore,
		"log_config_index":        int(configEntry.Index),
		"log_config_count":        configEntryCount,
		"log_config_voters":       probeVoters(logConfig),
		"log_config_servers":      probeServersJSON(logConfig),
		"stale_is_member":         inConfiguration(logConfig, stale.localID),
		"stale_has_vote":          hasVote(logConfig, stale.localID),
		"snapshot_config_index":   int(snapshotConfigIndex),
		"snapshot_config_voters":  snapshotVoters,
		"snapshot_config_servers": probeServersJSON(metas[0].Configuration),
		"staged_commit_index":     int(stagedCommitIndex),
	})

	for _, r := range c.rafts {
		if err := r.Shutdown().Error(); err != nil {
			t.Fatalf("probe %s: shutdown failed: %v", scenario, err)
		}
	}

	// Only these two peers come back; the former leader stays down so no known leader
	// rejects the campaign.
	live := map[*Raft]*InmemTransport{}
	staleR := probeRestart(t, scenario, stale, c.stores[otherIdx[0]], restore, live)
	responderR := probeRestart(t, scenario, responder, c.stores[otherIdx[1]], restore, live)
	c.rafts[otherIdx[0]] = staleR
	c.rafts[otherIdx[1]] = responderR

	// Observe the requests the responder receives from the campaigning peer.
	preVotes := 0
	votes := 0
	observed := make(chan Observation, 4096)
	observer := NewObserver(observed, false, func(o *Observation) bool {
		if o.Raft != responderR {
			return false
		}
		switch o.Data.(type) {
		case RequestPreVoteRequest, RequestVoteRequest:
			return true
		}
		return false
	})
	responderR.RegisterObserver(observer)

	staleBecameLeader := false
	deadline := time.Now().Add(wait)
	for time.Now().Before(deadline) {
		if staleR.State() == Leader {
			staleBecameLeader = true
			break
		}
		time.Sleep(2 * time.Millisecond)
	}
	for {
		select {
		case o := <-observed:
			switch o.Data.(type) {
			case RequestPreVoteRequest:
				preVotes++
			case RequestVoteRequest:
				votes++
			}
			continue
		default:
		}
		break
	}

	probeEmit(t, map[string]interface{}{
		"event":                   "campaign_result",
		"scenario":                scenario,
		"restore_committed_logs":  restore,
		"stale_config_voters":     probeVoters(staleR.configurations.latest),
		"stale_log_config_voters": probeVoters(logConfig),
		"stale_has_vote_in_log":   hasVote(logConfig, stale.localID),
		"responder_config_voters": probeVoters(responderR.configurations.latest),
		"stale_became_leader":     staleBecameLeader,
		"stale_state":             staleR.State().String(),
		"responder_pre_votes":     preVotes,
		"responder_votes":         votes,
		"wait_millis":             int(wait / time.Millisecond),
	})

	c.Close()
}

// probeRunDiscardCase builds a five-voter committed configuration, acknowledges one commit
// on a reconstructed smaller configuration while the other four voters are down, then
// brings a majority of the committed configuration back and reports whether the
// acknowledged payload survives anywhere.
func probeRunDiscardCase(t *testing.T, restore bool, wait time.Duration) {
	t.Helper()
	scenario := "lost_entry_discard"

	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.RestoreCommittedLogs = restore
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              5,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})

	leader := c.Leader()
	leaderIdx := -1
	var victims []*Raft
	var victimIdx []int
	for i, r := range c.rafts {
		if r == leader {
			leaderIdx = i
			continue
		}
		victims = append(victims, r)
		victimIdx = append(victimIdx, i)
	}
	if leaderIdx < 0 || len(victims) != 4 {
		t.Fatalf("probe %s: unexpected cluster shape", scenario)
	}

	// Single voter first, snapshot that configuration, then five voters again.
	for _, victim := range victims {
		if err := leader.DemoteVoter(victim.localID, 0, 0).Error(); err != nil {
			t.Fatalf("probe %s: DemoteVoter failed: %v", scenario, err)
		}
	}
	var future Future
	for i := 0; i < 100; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: apply failed: %v", scenario, err)
	}
	if err := leader.Snapshot().Error(); err != nil {
		t.Fatalf("probe %s: snapshot failed: %v", scenario, err)
	}
	metas, err := leader.snapshots.List()
	if err != nil || len(metas) == 0 {
		t.Fatalf("probe %s: no snapshot meta: %v", scenario, err)
	}
	for _, victim := range victims {
		if err := leader.AddVoter(victim.localID, victim.localAddr, 0, 0).Error(); err != nil {
			t.Fatalf("probe %s: AddVoter failed: %v", scenario, err)
		}
	}
	for i := 0; i < 5; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-after-promote-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: post-promote apply failed: %v", scenario, err)
	}

	configEntry, configEntryCount := probeConfigEntries(t, leader.logs, leader.trans)
	logConfig := probeDecodeConfig(t, configEntry)
	store, ok := leader.logs.(CommitTrackingLogStore)
	if !ok {
		t.Fatalf("probe %s: log store does not track commits", scenario)
	}
	stagedCommitIndex, err := store.GetCommitIndex()
	if err != nil {
		t.Fatalf("probe %s: GetCommitIndex: %v", scenario, err)
	}

	probeEmit(t, map[string]interface{}{
		"event":                  "discard_inputs",
		"scenario":               scenario,
		"restore_committed_logs": restore,
		"log_config_index":       int(configEntry.Index),
		"log_config_count":       configEntryCount,
		"log_config_voters":      probeVoters(logConfig),
		"log_config_servers":     probeServersJSON(logConfig),
		"snapshot_index":         int(metas[0].Index),
		"snapshot_config_index":  int(metas[0].ConfigurationIndex),
		"snapshot_config_voters": probeVoters(metas[0].Configuration),
		"staged_commit_index":    int(stagedCommitIndex),
		"peers":                  5,
	})

	for _, r := range c.rafts {
		if err := r.Shutdown().Error(); err != nil {
			t.Fatalf("probe %s: shutdown failed: %v", scenario, err)
		}
	}

	live := map[*Raft]*InmemTransport{}
	holder := probeRestart(t, scenario, leader, c.stores[leaderIdx], restore, live)
	c.rafts[leaderIdx] = holder
	holderLeader := false
	deadline := time.Now().Add(wait)
	for time.Now().Before(deadline) {
		if holder.State() == Leader {
			holderLeader = true
			break
		}
		time.Sleep(2 * time.Millisecond)
	}
	holderVoters := probeVoters(holder.configurations.latest)

	payload := fmt.Sprintf("discard-commit-%s-%d", scenario, time.Now().UnixNano())
	acknowledged := false
	applyError := ""
	var payloadIndex uint64
	if future := holder.Apply([]byte(payload), 1500*time.Millisecond); future.Error() == nil {
		acknowledged = true
		payloadIndex = future.Index()
	} else {
		applyError = future.Error().Error()
	}
	holderTerm := holder.getCurrentTerm()
	if err := holder.Shutdown().Error(); err != nil {
		t.Fatalf("probe %s: holder shutdown failed: %v", scenario, err)
	}
	delete(live, holder)

	// Bring a majority of the committed configuration back with the flag off.
	var rejoiners []*Raft
	for i, victim := range victims {
		rejoined := probeRestart(t, scenario, victim, c.stores[victimIdx[i]], false, live)
		c.rafts[victimIdx[i]] = rejoined
		rejoiners = append(rejoiners, rejoined)
	}
	newLeaderElected := false
	newLeaderTerm := uint64(0)
	deadline = time.Now().Add(wait)
	for time.Now().Before(deadline) {
		for _, r := range rejoiners {
			if r.State() == Leader {
				newLeaderElected = true
				newLeaderTerm = r.getCurrentTerm()
			}
		}
		if newLeaderElected {
			break
		}
		time.Sleep(2 * time.Millisecond)
	}
	time.Sleep(200 * time.Millisecond)

	copies := 0
	for _, r := range rejoiners {
		if present, _ := probePayload(r.logs, payload); present {
			copies++
		}
	}

	// Let the returning majority elect once more, so its leadership is in a strictly higher
	// term than the stale holder's leadership and the holder's extra entries must conflict.
	var firstLeader *Raft
	for _, r := range rejoiners {
		if r.State() == Leader {
			firstLeader = r
		}
	}
	secondElection := rejoiners
	if firstLeader != nil {
		if err := firstLeader.Shutdown().Error(); err != nil {
			t.Fatalf("probe %s: first returning leader shutdown failed: %v", scenario, err)
		}
		delete(live, firstLeader)
		secondElection = nil
		for _, r := range rejoiners {
			if r != firstLeader {
				secondElection = append(secondElection, r)
			}
		}
	}
	higherLeaderElected := false
	higherLeaderTerm := uint64(0)
	deadline = time.Now().Add(wait)
	for time.Now().Before(deadline) {
		for _, r := range secondElection {
			if r.State() == Leader {
				higherLeaderElected = true
				higherLeaderTerm = r.getCurrentTerm()
			}
		}
		if higherLeaderElected {
			break
		}
		time.Sleep(2 * time.Millisecond)
	}
	time.Sleep(200 * time.Millisecond)

	// Bring the original holder back as well and let the new leadership replicate over it.
	holderAgain := probeRestart(t, scenario, leader, c.stores[leaderIdx], false, live)
	c.rafts[leaderIdx] = holderAgain
	time.Sleep(wait)
	onHolder, holderIndex := probePayload(holderAgain.logs, payload)
	_ = holderIndex
	if onHolder {
		copies++
	}
	holderLastIndex, _ := holderAgain.getLastLog()

	probeEmit(t, map[string]interface{}{
		"event":                       "entry_discard",
		"scenario":                    scenario,
		"restore_committed_logs":      restore,
		"reconstructed_config_voters": holderVoters,
		"stale_leader":                holderLeader,
		"acknowledged":                acknowledged,
		"apply_error":                 applyError,
		"payload_index":               int(payloadIndex),
		"holder_term":                 int(holderTerm),
		"new_leader_elected":          newLeaderElected,
		"new_leader_term":             int(newLeaderTerm),
		"higher_leader_elected":       higherLeaderElected,
		"higher_leader_term":          int(higherLeaderTerm),
		"copies_after_rejoin":         copies,
		"payload_on_holder_after":     onHolder,
		"holder_last_index_after":     int(holderLastIndex),
		"durable_on_majority":         copies >= 3,
		"discarded":                   acknowledged && copies == 0,
		"wait_millis":                 int(wait / time.Millisecond),
	})

	c.Close()
}

// probeRunVoteGateCase delivers a real vote request from a live nonvoter that holds the
// same log as the responder to a restarted instance that knows no leader, and reports
// whether the responder granted it.
func probeRunVoteGateCase(t *testing.T, restore bool, wait time.Duration) {
	t.Helper()
	scenario := "vote_gate_after_restart"

	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.RestoreCommittedLogs = restore
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})

	leader := c.Leader()
	leaderIdx := -1
	var others []*Raft
	var otherIdx []int
	for i, r := range c.rafts {
		if r == leader {
			leaderIdx = i
			continue
		}
		others = append(others, r)
		otherIdx = append(otherIdx, i)
	}
	if leaderIdx < 0 || len(others) != 2 {
		t.Fatalf("probe %s: unexpected cluster shape", scenario)
	}
	nonvoter, responder := others[0], others[1]

	// Make one peer a nonvoter so it keeps receiving entries without holding a vote.
	if err := leader.DemoteVoter(nonvoter.localID, 0, 0).Error(); err != nil {
		t.Fatalf("probe %s: DemoteVoter failed: %v", scenario, err)
	}
	var future Future
	for i := 0; i < 20; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: apply failed: %v", scenario, err)
	}

	configEntry, configEntryCount := probeConfigEntries(t, responder.logs, responder.trans)
	logConfig := probeDecodeConfig(t, configEntry)
	metas, err := responder.snapshots.List()
	if err != nil {
		t.Fatalf("probe %s: listing snapshots failed: %v", scenario, err)
	}

	if err := responder.Shutdown().Error(); err != nil {
		t.Fatalf("probe %s: responder shutdown failed: %v", scenario, err)
	}

	probeEmit(t, map[string]interface{}{
		"event":                  "vote_inputs",
		"scenario":               scenario,
		"restore_committed_logs": restore,
		"log_config_index":       int(configEntry.Index),
		"log_config_count":       configEntryCount,
		"log_config_voters":      probeVoters(logConfig),
		"log_config_servers":     probeServersJSON(logConfig),
		"snapshot_count":         len(metas),
		"candidate_is_member":    inConfiguration(logConfig, nonvoter.localID),
		"candidate_has_vote":     hasVote(logConfig, nonvoter.localID),
		"leader_was_running":     leader.State() == Leader,
		"observation_millis":     int(wait / time.Millisecond),
	})

	live := map[*Raft]*InmemTransport{}
	restarted := probeRestart(t, scenario, responder, c.stores[otherIdx[1]], restore, live)
	c.rafts[otherIdx[1]] = restarted
	inner, ok := restarted.trans.(*InmemTransport)
	if !ok {
		t.Fatalf("probe %s: unexpected responder transport type", scenario)
	}
	for _, peer := range []*Raft{leader, nonvoter} {
		if peerTrans, ok := peer.trans.(*InmemTransport); ok {
			inner.Connect(peerTrans.LocalAddr(), peerTrans)
			peerTrans.Connect(restarted.trans.LocalAddr(), inner)
		}
	}

	// Stop the leader so the restarted instance knows no leader at all.
	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("probe %s: leader shutdown failed: %v", scenario, err)
	}
	time.Sleep(wait)

	responderVoters := probeVoters(restarted.configurations.latest)
	termBefore := restarted.getCurrentTerm()
	lastIdx, lastTerm := nonvoter.getLastEntry()
	claimedTerm := nonvoter.getCurrentTerm() + 1
	req := &RequestVoteRequest{
		RPCHeader:    nonvoter.getRPCHeader(),
		Term:         claimedTerm,
		Candidate:    nonvoter.trans.EncodePeer(nonvoter.localID, nonvoter.localAddr),
		LastLogIndex: lastIdx,
		LastLogTerm:  lastTerm,
	}
	resp := &RequestVoteResponse{}
	trans, ok := nonvoter.trans.(*InmemTransport)
	if !ok {
		t.Fatalf("probe %s: unexpected candidate transport type", scenario)
	}
	loggedTermBefore, _ := c.stores[otherIdx[1]].GetUint64(keyLastVoteTerm)
	loggedCandBefore, _ := c.stores[otherIdx[1]].Get(keyLastVoteCand)
	rpcErr := trans.RequestVote(restarted.localID, restarted.localAddr, req, resp)
	loggedTermAfter, _ := c.stores[otherIdx[1]].GetUint64(keyLastVoteTerm)
	loggedCandAfter, _ := c.stores[otherIdx[1]].Get(keyLastVoteCand)
	errText := ""
	if rpcErr != nil {
		errText = rpcErr.Error()
	}

	probeEmit(t, map[string]interface{}{
		"event":                        "vote_grant",
		"scenario":                     scenario,
		"restore_committed_logs":       restore,
		"responder_config_voters":      responderVoters,
		"responder_log_config_voters":  probeVoters(logConfig),
		"responder_term_before":        int(termBefore),
		"responder_term_after":         int(restarted.getCurrentTerm()),
		"candidate_is_member":          inConfiguration(logConfig, nonvoter.localID),
		"candidate_has_vote":           hasVote(logConfig, nonvoter.localID),
		"candidate_last_index":         int(lastIdx),
		"candidate_last_term":          int(lastTerm),
		"candidate_term":               int(nonvoter.getCurrentTerm()),
		"rpc_error":                    errText,
		"granted":                      resp.Granted,
		"response_term":                int(resp.Term),
		"candidate_claimed_term":       int(claimedTerm),
		"logged_vote_term_before":      int(loggedTermBefore),
		"logged_vote_candidate_before": string(loggedCandBefore),
		"logged_vote_term_after":       int(loggedTermAfter),
		"logged_vote_candidate_after":  string(loggedCandAfter),
		"observation_millis":           int(wait / time.Millisecond),
	})

	c.Close()
}

// probeRunFollowerRepairCase restarts one follower of a cluster whose leader stays live,
// records the reconstruction while the leader keeps replicating, and then appends a new
// configuration entry to see whether it repairs the reconstruction.
func probeRunFollowerRepairCase(t *testing.T, restore bool, wait time.Duration) {
	t.Helper()
	scenario := "follower_in_live_cluster"

	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.RestoreCommittedLogs = restore
	// A longer lease keeps the live leader in place while one follower restarts.
	conf.HeartbeatTimeout = 300 * time.Millisecond
	conf.ElectionTimeout = 300 * time.Millisecond
	conf.LeaderLeaseTimeout = 300 * time.Millisecond
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})

	leader := c.Leader()
	leaderIdx := -1
	var victims []*Raft
	var victimIdx []int
	for i, r := range c.rafts {
		if r == leader {
			leaderIdx = i
			continue
		}
		victims = append(victims, r)
		victimIdx = append(victimIdx, i)
	}
	if leaderIdx < 0 || len(victims) != 2 {
		t.Fatalf("probe %s: unexpected cluster shape", scenario)
	}
	removed, follower := victims[0], victims[1]

	var future Future
	for i := 0; i < 100; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: apply failed: %v", scenario, err)
	}
	if err := leader.RemoveServer(removed.localID, 0, 0).Error(); err != nil {
		t.Fatalf("probe %s: RemoveServer failed: %v", scenario, err)
	}
	for i := 0; i < 10; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-after-remove-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: post-remove apply failed: %v", scenario, err)
	}

	configEntry, configEntryCount := probeConfigEntries(t, follower.logs, follower.trans)
	logConfig := probeDecodeConfig(t, configEntry)
	store, ok := follower.logs.(CommitTrackingLogStore)
	if !ok {
		t.Fatalf("probe %s: log store does not track commits", scenario)
	}
	stagedCommitIndex, err := store.GetCommitIndex()
	if err != nil {
		t.Fatalf("probe %s: GetCommitIndex: %v", scenario, err)
	}
	metas, err := follower.snapshots.List()
	if err != nil {
		t.Fatalf("probe %s: listing snapshots failed: %v", scenario, err)
	}

	// Stop only this follower; the leader keeps running and replicating to it.
	if err := follower.Shutdown().Error(); err != nil {
		t.Fatalf("probe %s: follower shutdown failed: %v", scenario, err)
	}

	probeEmit(t, map[string]interface{}{
		"event":                  "follower_inputs",
		"scenario":               scenario,
		"restore_committed_logs": restore,
		"log_config_index":       int(configEntry.Index),
		"log_config_count":       configEntryCount,
		"log_config_voters":      probeVoters(logConfig),
		"log_config_servers":     probeServersJSON(logConfig),
		"snapshot_count":         len(metas),
		"staged_commit_index":    int(stagedCommitIndex),
		"leader_was_running":     leader.State() == Leader,
	})

	live := map[*Raft]*InmemTransport{}
	restarted := probeRestart(t, scenario, follower, c.stores[victimIdx[1]], restore, live)
	c.rafts[victimIdx[1]] = restarted
	inner, ok := restarted.trans.(*InmemTransport)
	if !ok {
		t.Fatalf("probe %s: unexpected transport type", scenario)
	}
	if lt, ok := leader.trans.(LoopbackTransport); ok {
		inner.Connect(lt.LocalAddr(), lt)
		lt.Connect(restarted.trans.LocalAddr(), inner)
	}

	// Give the live leader time to replicate to the restarted follower before observing.
	time.Sleep(wait)
	lastLogIndex, _ := restarted.getLastLog()
	probeEmit(t, map[string]interface{}{
		"event":                   "follower_observation",
		"scenario":                scenario,
		"restore_committed_logs":  restore,
		"latest_config_index":     int(restarted.configurations.latestIndex),
		"latest_config_voters":    probeVoters(restarted.configurations.latest),
		"latest_config_servers":   probeServersJSON(restarted.configurations.latest),
		"log_config_index":        int(configEntry.Index),
		"log_config_voters":       probeVoters(logConfig),
		"follower_last_log_index": int(lastLogIndex),
		"follower_last_applied":   int(restarted.getLastApplied()),
		"leader_state":            leader.State().String(),
		"leader_latest_voters":    probeVoters(leader.configurations.latest),
		"leader_committed_index":  int(leader.configurations.committedIndex),
		"observation_millis":      int(wait / time.Millisecond),
	})

	// Wait for the leader to be leading again before the repair step, without failing the
	// run if it never does: the repair outcome is reported either way.
	repairDeadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(repairDeadline) && leader.State() != Leader {
		time.Sleep(2 * time.Millisecond)
	}
	repairError := ""
	if leader.State() != Leader {
		repairError = "leader not in leader state before the repair step"
	} else if err := leader.AddVoter(removed.localID, removed.localAddr, 0, 0).Error(); err != nil {
		repairError = err.Error()
	}
	newEntryIndex := int(leader.configurations.latestIndex)
	time.Sleep(wait)
	repairedIndex := int(restarted.configurations.latestIndex)
	repairedVoters := probeVoters(restarted.configurations.latest)
	probeEmit(t, map[string]interface{}{
		"event":                  "follower_repair",
		"scenario":               scenario,
		"restore_committed_logs": restore,
		"new_config_entry_index": newEntryIndex,
		"latest_config_index":    repairedIndex,
		"latest_config_voters":   repairedVoters,
		"repaired":               repairError == "" && repairedIndex == newEntryIndex && repairedVoters == 3,
		"repair_error":           repairError,
		"repair_millis":          int(wait / time.Millisecond),
	})

	c.Close()
}

// probeRunLostCommitCase builds a three-voter cluster, lets the surviving instance
// reconstruct a smaller configuration, acknowledges one commit on it alone, then brings
// the other two voters back and reports whether the acknowledged commit survived.
func probeRunLostCommitCase(t *testing.T, restore bool, wait time.Duration) {
	t.Helper()
	scenario := "lost_acknowledged_commit"

	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.RestoreCommittedLogs = restore
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})

	leader := c.Leader()
	leaderIdx := -1
	var victims []*Raft
	var victimIdx []int
	for i, r := range c.rafts {
		if r == leader {
			leaderIdx = i
			continue
		}
		victims = append(victims, r)
		victimIdx = append(victimIdx, i)
	}
	if leaderIdx < 0 || len(victims) != 2 {
		t.Fatalf("probe %s: unexpected cluster shape", scenario)
	}

	// Leave a single voter, snapshot that configuration, then make all three voters again.
	for _, victim := range victims {
		if err := leader.DemoteVoter(victim.localID, 0, 0).Error(); err != nil {
			t.Fatalf("probe %s: DemoteVoter failed: %v", scenario, err)
		}
	}
	var future Future
	for i := 0; i < 100; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: apply failed: %v", scenario, err)
	}
	if err := leader.Snapshot().Error(); err != nil {
		t.Fatalf("probe %s: snapshot failed: %v", scenario, err)
	}
	metas, err := leader.snapshots.List()
	if err != nil || len(metas) == 0 {
		t.Fatalf("probe %s: no snapshot meta: %v", scenario, err)
	}
	snapshotIndex := metas[0].Index
	snapshotConfigIndex := metas[0].ConfigurationIndex
	snapshotServers := probeServersJSON(metas[0].Configuration)

	for _, victim := range victims {
		if err := leader.AddVoter(victim.localID, victim.localAddr, 0, 0).Error(); err != nil {
			t.Fatalf("probe %s: AddVoter failed: %v", scenario, err)
		}
	}
	for i := 0; i < 5; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-after-promote-%d", scenario, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: post-promote apply failed: %v", scenario, err)
	}

	configEntry, configEntryCount := probeConfigEntries(t, leader.logs, leader.trans)
	logConfig := probeDecodeConfig(t, configEntry)
	store, ok := leader.logs.(CommitTrackingLogStore)
	if !ok {
		t.Fatalf("probe %s: log store does not track commits", scenario)
	}
	stagedCommitIndex, err := store.GetCommitIndex()
	if err != nil {
		t.Fatalf("probe %s: GetCommitIndex: %v", scenario, err)
	}

	probeEmit(t, map[string]interface{}{
		"event":                   "lost_inputs",
		"scenario":                scenario,
		"restore_committed_logs":  restore,
		"log_config_index":        int(configEntry.Index),
		"log_config_count":        configEntryCount,
		"log_config_servers":      probeServersJSON(logConfig),
		"log_config_voters":       probeVoters(logConfig),
		"snapshot_index":          int(snapshotIndex),
		"snapshot_config_index":   int(snapshotConfigIndex),
		"snapshot_config_voters":  probeVoters(metas[0].Configuration),
		"snapshot_config_servers": snapshotServers,
		"staged_commit_index":     int(stagedCommitIndex),
		"peers":                   3,
	})

	// Stop everybody, then bring the single voter back on its own.
	for _, r := range c.rafts {
		if err := r.Shutdown().Error(); err != nil {
			t.Fatalf("probe %s: shutdown failed: %v", scenario, err)
		}
	}

	live := map[*Raft]*InmemTransport{}
	survivor := probeRestart(t, scenario, leader, c.stores[leaderIdx], restore, live)
	c.rafts[leaderIdx] = survivor

	survivorLeader := false
	deadline := time.Now().Add(wait)
	for time.Now().Before(deadline) {
		if survivor.State() == Leader {
			survivorLeader = true
			break
		}
		time.Sleep(2 * time.Millisecond)
	}
	survivorVoters := probeVoters(survivor.configurations.latest)

	payload := fmt.Sprintf("lost-commit-%s-%d", scenario, time.Now().UnixNano())
	acknowledged := false
	applyError := ""
	var payloadIndex uint64
	if future := survivor.Apply([]byte(payload), 1500*time.Millisecond); future.Error() == nil {
		acknowledged = true
		payloadIndex = future.Index()
	} else {
		applyError = future.Error().Error()
	}
	survivorTerm := survivor.getCurrentTerm()

	// Take the holder away again, then bring the other two voters back with the flag off
	// so their own configuration comes from their logs.
	if err := survivor.Shutdown().Error(); err != nil {
		t.Fatalf("probe %s: survivor shutdown failed: %v", scenario, err)
	}
	delete(live, survivor)

	var rejoiners []*Raft
	for i, victim := range victims {
		rejoined := probeRestart(t, scenario, victim, c.stores[victimIdx[i]], false, live)
		c.rafts[victimIdx[i]] = rejoined
		rejoiners = append(rejoiners, rejoined)
	}

	newLeaderElected := false
	newLeaderTerm := uint64(0)
	deadline = time.Now().Add(wait)
	for time.Now().Before(deadline) {
		for _, r := range rejoiners {
			if r.State() == Leader {
				newLeaderElected = true
				newLeaderTerm = r.getCurrentTerm()
			}
		}
		if newLeaderElected {
			break
		}
		time.Sleep(2 * time.Millisecond)
	}
	time.Sleep(200 * time.Millisecond)

	onVictims := 0
	for _, r := range rejoiners {
		if present, _ := probePayload(r.logs, payload); present {
			onVictims++
		}
	}

	// Bring the original holder back as well and let the new leadership replicate over it.
	rejoinedHolder := probeRestart(t, scenario, leader, c.stores[leaderIdx], false, live)
	c.rafts[leaderIdx] = rejoinedHolder
	time.Sleep(600 * time.Millisecond)
	onHolder, holderIndex := probePayload(rejoinedHolder.logs, payload)

	durable := onVictims
	if onHolder {
		durable++
	}
	probeEmit(t, map[string]interface{}{
		"event":                          "entry_survival",
		"scenario":                       scenario,
		"restore_committed_logs":         restore,
		"reconstructed_config_voters":    survivorVoters,
		"stale_leader":                   survivorLeader,
		"acknowledged":                   acknowledged,
		"apply_error":                    applyError,
		"payload_index":                  int(payloadIndex),
		"payload_on_holder_after_rejoin": onHolder,
		"payload_holder_index_after":     int(holderIndex),
		"payload_on_victims":             onVictims,
		"durable_on_majority":            durable >= 2,
		"durable_copies":                 durable,
		"stale_leader_term":              int(survivorTerm),
		"new_leader_elected":             newLeaderElected,
		"new_leader_term":                int(newLeaderTerm),
		"wait_millis":                    int(wait / time.Millisecond),
	})

	c.Close()
}

// probeRunCase builds a real in-memory cluster, persists a decision context (a committed
// configuration entry), then restarts the surviving voter with a fresh transport and reports
// what that instance reconstructed and whether it could regain leadership.
func probeRunCase(t *testing.T, pc probeCase) {
	t.Helper()

	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.RestoreCommittedLogs = pc.restore
	opts := &MakeClusterOpts{
		Peers:              pc.peers,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)

	leader := c.Leader()

	// Scenario D setup: demote the non-leader to a nonvoter first, so the snapshot taken
	// below records a configuration with a single voter.
	if pc.demotePeer {
		victim := probeNonLeader(c, leader)
		if victim == nil {
			t.Fatalf("probe %s: no non-leader peer to demote", pc.name)
		}
		if err := leader.DemoteVoter(victim.localID, 0, 0).Error(); err != nil {
			t.Fatalf("probe %s: DemoteVoter failed: %v", pc.name, err)
		}
	}

	var future Future
	for i := 0; i < 100; i++ {
		future = leader.Apply([]byte(fmt.Sprintf("probe-%s-%d", pc.name, i)), 0)
	}
	if err := future.Error(); err != nil {
		t.Fatalf("probe %s: apply failed: %v", pc.name, err)
	}

	snapshotIndex := uint64(0)
	snapshotConfigIndex := uint64(0)
	snapshotServers := "[]"
	if pc.snapshot {
		if err := leader.Snapshot().Error(); err != nil {
			t.Fatalf("probe %s: snapshot failed: %v", pc.name, err)
		}
		metas, err := leader.snapshots.List()
		if err != nil || len(metas) == 0 {
			t.Fatalf("probe %s: no snapshot meta: %v", pc.name, err)
		}
		snapshotIndex = metas[0].Index
		snapshotConfigIndex = metas[0].ConfigurationIndex
		snapshotServers = probeServersJSON(metas[0].Configuration)
	}

	if pc.removePeer {
		var victim *Raft
		for _, r := range c.rafts {
			if r != leader {
				victim = r
			}
		}
		if victim == nil {
			t.Fatalf("probe %s: no non-leader peer to remove", pc.name)
		}
		if err := leader.RemoveServer(victim.localID, 0, 0).Error(); err != nil {
			t.Fatalf("probe %s: RemoveServer failed: %v", pc.name, err)
		}
		// Dispatch more work so the commit-tracking store is staged at or beyond the
		// committed configuration entry.
		for i := 0; i < pc.postRemoveApplies; i++ {
			future = leader.Apply([]byte(fmt.Sprintf("probe-%s-after-remove-%d", pc.name, i)), 0)
		}
		if pc.postRemoveApplies > 0 {
			if err := future.Error(); err != nil {
				t.Fatalf("probe %s: post-remove apply failed: %v", pc.name, err)
			}
		} else {
			// Wait for the removal itself to commit without dispatching further log
			// entries, so the tracked commit index stays below the configuration entry.
			if err := leader.VerifyLeader().Error(); err != nil {
				t.Fatalf("probe %s: leader verification after the removal failed: %v", pc.name, err)
			}
		}
	}

	// Scenario D change: promote the demoted peer back to a voter, so the committed
	// configuration needs both voters while the snapshot still records one voter.
	if pc.demotePeer {
		victim := probeNonLeader(c, leader)
		if victim == nil {
			t.Fatalf("probe %s: no non-leader peer to promote", pc.name)
		}
		if err := leader.AddVoter(victim.localID, victim.localAddr, 0, 0).Error(); err != nil {
			t.Fatalf("probe %s: AddVoter failed: %v", pc.name, err)
		}
		for i := 0; i < pc.postRemoveApplies; i++ {
			future = leader.Apply([]byte(fmt.Sprintf("probe-%s-after-promote-%d", pc.name, i)), 0)
		}
		if pc.postRemoveApplies > 0 {
			if err := future.Error(); err != nil {
				t.Fatalf("probe %s: post-promote apply failed: %v", pc.name, err)
			}
		}
	}

	// Durable inputs of the surviving instance, read before the restart.
	survivor := leader
	logs := survivor.logs
	stable := c.stores[0]
	snaps := survivor.snapshots
	fsm := survivor.fsm
	cfg := survivor.config()

	configEntry, configEntryCount := probeConfigEntries(t, logs, survivor.trans)
	logConfig := probeDecodeConfig(t, configEntry)
	lastLogIndex, _ := logs.LastIndex()
	firstLogIndex, _ := logs.FirstIndex()
	store, ok := logs.(CommitTrackingLogStore)
	if !ok {
		t.Fatalf("probe %s: log store does not track commits", pc.name)
	}
	stagedCommitIndex, err := store.GetCommitIndex()
	if err != nil {
		t.Fatalf("probe %s: GetCommitIndex: %v", pc.name, err)
	}

	probeEmit(t, map[string]interface{}{
		"event":                   "restart_inputs",
		"scenario":                pc.name,
		"restore_committed_logs":  pc.restore,
		"log_config_index":        int(configEntry.Index),
		"log_config_count":        configEntryCount,
		"log_config_servers":      probeServersJSON(logConfig),
		"log_config_voters":       probeVoters(logConfig),
		"first_log_index":         int(firstLogIndex),
		"last_log_index":          int(lastLogIndex),
		"staged_commit_index":     int(stagedCommitIndex),
		"snapshot_index":          int(snapshotIndex),
		"snapshot_config_index":   int(snapshotConfigIndex),
		"snapshot_config_servers": snapshotServers,
		"peers":                   pc.peers,
		"removed_peer":            pc.removePeer,
		"wait_millis":             int(pc.wait / time.Millisecond),
	})

	// Stop every instance and keep the stores, so the restart sees the same durable state.
	for _, r := range c.rafts {
		if err := r.Shutdown().Error(); err != nil {
			t.Fatalf("probe %s: shutdown failed: %v", pc.name, err)
		}
	}

	addr, inner := NewInmemTransport(survivor.trans.LocalAddr())
	counting := &probeCountingTransport{InmemTransport: inner}
	// Restore connectivity with any instance that is still running, in both directions.
	for _, r := range c.rafts {
		if r == survivor {
			continue
		}
		peer, ok := r.trans.(LoopbackTransport)
		if !ok || peer.LocalAddr() == "" {
			continue
		}
		counting.Connect(peer.LocalAddr(), peer)
		// An in-memory transport only accepts its own concrete type as a peer.
		peer.Connect(addr, inner)
	}
	restarted, err := NewRaft(&cfg, fsm, logs, stable, snaps, counting)
	if err != nil {
		t.Fatalf("probe %s: restart failed: %v", pc.name, err)
	}
	if addr == "" {
		t.Fatalf("probe %s: restart transport has no address", pc.name)
	}
	for i, r := range c.rafts {
		if r == survivor {
			c.rafts[i] = restarted
		}
	}

	publicConfig := Configuration{}
	if f := restarted.GetConfiguration(); f.Error() == nil {
		publicConfig = f.Configuration()
	}

	probeEmit(t, map[string]interface{}{
		"event":                          "restart_observation",
		"scenario":                       pc.name,
		"restore_committed_logs":         pc.restore,
		"latest_config_index":            int(restarted.configurations.latestIndex),
		"committed_config_index":         int(restarted.configurations.committedIndex),
		"latest_config_voters":           probeVoters(restarted.configurations.latest),
		"latest_config_servers":          probeServersJSON(restarted.configurations.latest),
		"public_config_index":            int(restarted.configurations.committedIndex),
		"public_config_voters":           probeVoters(publicConfig),
		"public_config_servers":          probeServersJSON(publicConfig),
		"log_config_index":               int(configEntry.Index),
		"log_config_servers":             probeServersJSON(logConfig),
		"snapshot_config_index":          int(snapshotConfigIndex),
		"snapshot_config_servers":        snapshotServers,
		"last_applied":                   int(restarted.getLastApplied()),
		"staged_commit_index":            int(stagedCommitIndex),
		"last_log_index":                 int(lastLogIndex),
		"config_entry_in_applied_prefix": int(restarted.getLastApplied()) >= int(configEntry.Index),
	})

	candidateObservations := 0
	leaderObservations := 0
	observed := make(chan Observation, 4096)
	observer := NewObserver(observed, false, func(o *Observation) bool {
		if _, ok := o.Data.(RaftState); !ok {
			return false
		}
		return o.Raft == restarted
	})
	restarted.RegisterObserver(observer)

	becameLeader := false
	deadline := time.Now().Add(pc.wait)
	for time.Now().Before(deadline) {
		if restarted.State() == Leader {
			becameLeader = true
			break
		}
		time.Sleep(2 * time.Millisecond)
	}
	for {
		select {
		case o := <-observed:
			if state, ok := o.Data.(RaftState); ok {
				switch state {
				case Candidate:
					candidateObservations++
				case Leader:
					leaderObservations++
				}
			}
			continue
		default:
		}
		break
	}

	// Report where the configuration entry sits relative to the applied prefix the
	// restart installed, with both operands emitted for inspection.
	configIndex := int(configEntry.Index)
	applied := int(restarted.getLastApplied())

	// Optional decision duty: stop the other instance and try to commit one entry, so the
	// support the completed decision actually rested on is observable.
	applyOK := false
	applyErr := ""
	applyMillis := 0
	if pc.stopPeerForApply {
		if victim := probeNonLeader(c, restarted); victim != nil {
			if err := victim.Shutdown().Error(); err != nil {
				t.Fatalf("probe %s: shutting down the other instance failed: %v", pc.name, err)
			}
		}
		start := time.Now()
		if err := restarted.Apply([]byte("probe-"+pc.name+"-commit"), 1000*time.Millisecond).Error(); err == nil {
			applyOK = true
		} else {
			applyErr = err.Error()
		}
		applyMillis = int(time.Since(start) / time.Millisecond)
	}

	probeEmit(t, map[string]interface{}{
		"event":                          "node_progress",
		"scenario":                       pc.name,
		"restore_committed_logs":         pc.restore,
		"became_leader":                  becameLeader,
		"candidate_observations":         candidateObservations,
		"leader_observations":            leaderObservations,
		"state_after_wait":               restarted.State().String(),
		"wait_millis":                    int(pc.wait / time.Millisecond),
		"pre_vote_requests":              int(counting.preVotes.Load()),
		"vote_requests":                  int(counting.votes.Load()),
		"election_requests":              int(counting.preVotes.Load() + counting.votes.Load()),
		"latest_config_index":            int(restarted.configurations.latestIndex),
		"latest_config_voters":           probeVoters(restarted.configurations.latest),
		"log_config_index":               configIndex,
		"log_config_voters":              probeVoters(logConfig),
		"last_applied":                   applied,
		"config_entry_in_applied_prefix": applied >= configIndex,
		"apply_ok":                       applyOK,
		"apply_error":                    applyErr,
		"apply_millis":                   applyMillis,
	})

	c.Close()
}

func TestAssuranceRestoreCommittedLogsContext(t *testing.T) {
	wait := 3 * time.Second

	// Scenario A: a committed configuration entry exists in the log and no snapshot exists.
	probeRunCase(t, probeCase{name: "no_snapshot", peers: 1, restore: false, wait: wait})
	probeRunCase(t, probeCase{name: "no_snapshot", peers: 1, restore: true, wait: wait})

	// Scenario B: a snapshot is taken first, then a configuration change commits after that
	// snapshot and before the restart.
	probeRunCase(t, probeCase{name: "config_after_snapshot", peers: 2, restore: false, snapshot: true, removePeer: true, postRemoveApplies: 10, wait: wait})
	probeRunCase(t, probeCase{name: "config_after_snapshot", peers: 2, restore: true, snapshot: true, removePeer: true, postRemoveApplies: 10, wait: wait})

	// Scenario C: same snapshot-then-remove shape with the flag enabled, but no work is
	// dispatched after the removal, so the committed configuration entry stays above the
	// commit index the restart replays. This separates the skipped configuration entry
	// from the flag itself.
	probeRunCase(t, probeCase{name: "config_above_replayed_prefix", peers: 2, restore: true, snapshot: true, removePeer: true, postRemoveApplies: 0, wait: wait})

	// Scenario D: the snapshot records a single-voter configuration because the second
	// peer was demoted before it, and the committed configuration afterwards has two
	// voters again. The restarted instance is the surviving voter.
	probeRunCase(t, probeCase{name: "voter_promoted_after_snapshot", peers: 2, restore: true, snapshot: true, demotePeer: true, postRemoveApplies: 10, stopPeerForApply: true, wait: wait})
	probeRunCase(t, probeCase{name: "voter_promoted_after_snapshot", peers: 2, restore: false, snapshot: true, demotePeer: true, postRemoveApplies: 10, stopPeerForApply: true, wait: wait})

	// Scenario E: three-voter committed configuration, acknowledged commit taken on a
	// reconstructed smaller configuration, then the other two voters brought back.
	probeRunLostCommitCase(t, true, wait)
	probeRunLostCommitCase(t, false, wait)

	// Scenario F: a follower of a live cluster is restarted while its leader keeps
	// replicating, and a later configuration entry is appended by that leader.
	probeRunFollowerRepairCase(t, true, 400*time.Millisecond)
	probeRunFollowerRepairCase(t, false, 400*time.Millisecond)

	// Scenario G: a real vote request from a live nonvoter that holds the same log as the
	// restarted responder, which knows no leader.
	probeRunVoteGateCase(t, true, 200*time.Millisecond)
	probeRunVoteGateCase(t, false, 200*time.Millisecond)

	// Scenario H: five-voter committed configuration, acknowledged commit taken on a
	// reconstructed single-voter configuration, then a majority of the committed
	// configuration brought back without the holder.
	probeRunDiscardCase(t, true, 1000*time.Millisecond)
	probeRunDiscardCase(t, false, 1000*time.Millisecond)

	// Scenario I: a peer whose reconstruction still grants it a vote campaigns on its own
	// and is answered by a peer that also reconstructs a configuration.
	probeRunStaleCampaignCase(t, true, 1500*time.Millisecond)
	probeRunStaleCampaignCase(t, false, 1500*time.Millisecond)

	// Scenario J: a client membership change issued to a node leading on a reconstructed
	// configuration, then the demoted peers brought back.
	probeRunClientChangeCase(t, true, 400*time.Millisecond)
	probeRunClientChangeCase(t, false, 400*time.Millisecond)

	// Scenario K: the peers of the committed configuration are partitioned from the
	// restarted leader and both sides run.
	probeRunSplitConfigCase(t, true, 800*time.Millisecond)
	probeRunSplitConfigCase(t, false, 800*time.Millisecond)
}
