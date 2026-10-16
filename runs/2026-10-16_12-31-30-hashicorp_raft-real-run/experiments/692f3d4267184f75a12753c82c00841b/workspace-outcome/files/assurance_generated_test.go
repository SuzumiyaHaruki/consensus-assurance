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
}
