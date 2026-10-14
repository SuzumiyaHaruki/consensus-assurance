package raft

import (
	"encoding/json"
	"fmt"
	"runtime"
	"sort"
	"strings"
	"testing"
	"time"
)

// TestAssuranceRestoreCommittedLogsConfigurationRecovery
//
// Sourced question: when Config.RestoreCommittedLogs is enabled, does a node that
// restarts on top of its persisted stores still recover the membership configuration
// that its own log already contains?
//
// api.go starts the startup configuration scan at max(snapshotIndex, lastApplied)+1.
// restoreFromCommittedLogs() sets lastApplied to the commit index read from the log
// store before that scan runs, so every configuration entry at an index <= that
// commit index is skipped even though it is present in the node's log.
//
// The harness builds real (bootstrap -> election -> client applies -> shutdown)
// single-voter prefixes on top of a commit-tracking log store, then restarts the node
// with the same stores and a fresh in-memory FSM, once with RestoreCommittedLogs on and
// once with it off, and reports the operands of the recovery.

type assuranceEvent map[string]interface{}

func assuranceEmit(ev assuranceEvent) {
	b, err := json.Marshal(ev)
	if err != nil {
		fmt.Println(`CA_EVENT {"event":"assurance.marshal_error"}`)
		return
	}
	fmt.Println("CA_EVENT " + string(b))
}

type assuranceStores struct {
	addr   ServerAddress
	local  ServerID
	conf   *Config
	logs   *InmemCommitTrackingStore
	stable *InmemStore
	snaps  *InmemSnapshotStore
}

func assuranceWaitElected(t *testing.T, r *Raft, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if r.State() == Leader {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	return r.State() == Leader
}

// assuranceBuildPrefix runs the pre-restart life of one node and returns the stores it
// leaves behind. applyAfterSnapshot entries are applied after the optional snapshot, and
// the optional configuration change (AddNonvoter of a peer that never connects) is made
// after that snapshot as well, so the node has a committed configuration entry above its
// newest snapshot.
func assuranceBuildPrefix(t *testing.T, withSnapshot bool, caseName string) *assuranceStores {
	t.Helper()

	addr, trans := NewInmemTransport("")
	local := ServerID("server-" + string(addr))
	conf := inmemConfig(t)
	conf.LocalID = local
	// The prefix must run with the feature enabled, otherwise no commit index is ever
	// staged into the log store and the restart has nothing to read.
	conf.RestoreCommittedLogs = true
	conf.TrailingLogs = 16

	stores := &assuranceStores{
		addr:   addr,
		local:  local,
		conf:   conf,
		logs:   NewInmemCommitTrackingStore(),
		stable: NewInmemStore(),
		snaps:  NewInmemSnapshotStore(),
	}
	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       local,
		Address:  addr,
	}}}
	if err := BootstrapCluster(conf, stores.logs, stores.stable, stores.snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap failed: %v", err)
	}

	r, err := NewRaft(conf, &MockFSM{}, stores.logs, stores.stable, stores.snaps, trans)
	if err != nil {
		t.Fatalf("prefix NewRaft failed: %v", err)
	}
	if !assuranceWaitElected(t, r, 3*time.Second) {
		t.Fatalf("prefix node never became leader")
	}

	for i := 0; i < 4; i++ {
		if err := r.Apply([]byte(fmt.Sprintf("pre-%d", i)), 0).Error(); err != nil {
			t.Fatalf("prefix apply failed: %v", err)
		}
	}

	if withSnapshot {
		if err := r.Snapshot().Error(); err != nil {
			t.Fatalf("prefix snapshot failed: %v", err)
		}
		// A committed configuration entry strictly above the snapshot index.
		f := r.AddNonvoter(ServerID("assurance-peer-2"), ServerAddress("assurance-peer-2-addr"), 0, 2*time.Second)
		if err := f.Error(); err != nil {
			t.Fatalf("prefix AddNonvoter failed: %v", err)
		}
		for i := 0; i < 2; i++ {
			if err := r.Apply([]byte(fmt.Sprintf("post-%d", i)), 0).Error(); err != nil {
				t.Fatalf("prefix post apply failed: %v", err)
			}
		}
	}

	// Record the persisted state before shutdown.
	stagedCommit, err := stores.logs.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex failed: %v", err)
	}
	lastIndex, err := stores.logs.LastIndex()
	if err != nil {
		t.Fatalf("LastIndex failed: %v", err)
	}
	configs, err := assuranceLogConfigEntries(stores.logs, lastIndex)
	if err != nil {
		t.Fatalf("log scan failed: %v", err)
	}
	snapIndex, snapTerm := r.getLastSnapshot()
	assuranceEmit(assuranceEvent{
		"event":                 "assurance.prefix",
		"case":                  caseName,
		"snapshot_present":      withSnapshot,
		"snapshot_index":        snapIndex,
		"snapshot_term":         snapTerm,
		"log_last_index":        lastIndex,
		"staged_commit_index":   stagedCommit,
		"config_entries":        configs.summary,
		"last_config_index":     configs.lastIndex,
		"last_config_voters":    configs.lastVoters,
		"last_config_nonvoters": configs.lastNonvoters,
		"recording_label_count": 0,
	})

	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("prefix shutdown failed: %v", err)
	}
	return stores
}

type assuranceConfigScan struct {
	summary       string
	lastIndex     uint64
	lastVoters    int
	lastNonvoters int
	lastIDs       []string
}

func assuranceLogConfigEntries(logs *InmemCommitTrackingStore, lastIndex uint64) (assuranceConfigScan, error) {
	out := assuranceConfigScan{summary: ""}
	for idx := uint64(1); idx <= lastIndex; idx++ {
		var entry Log
		if err := logs.GetLog(idx, &entry); err != nil {
			return out, err
		}
		switch entry.Type {
		case LogConfiguration:
			conf := DecodeConfiguration(entry.Data)
			voters, nonvoters := assuranceSuffrageCounts(conf)
			out.summary += fmt.Sprintf("LogConfiguration@%d(servers=%d,voters=%d)", idx, len(conf.Servers), voters)
			out.lastIndex = idx
			out.lastVoters = voters
			out.lastNonvoters = nonvoters
			out.lastIDs = assuranceSortedIDs(conf)
		case LogAddPeerDeprecated, LogRemovePeerDeprecated:
			out.summary += fmt.Sprintf("DeprecatedPeers@%d", idx)
			out.lastIndex = idx
		}
	}
	return out, nil
}

func assuranceSuffrageCounts(conf Configuration) (voters, nonvoters int) {
	for _, s := range conf.Servers {
		if s.Suffrage == Voter {
			voters++
		} else {
			nonvoters++
		}
	}
	return voters, nonvoters
}

func assuranceConfigIDs(conf Configuration) string {
	out := ""
	for i, s := range conf.Servers {
		if i > 0 {
			out += ","
		}
		out += string(s.ID)
	}
	return out
}

// assuranceSortedIDs returns a comparable, order independent list of server IDs.
func assuranceSortedIDs(conf Configuration) []string {
	out := make([]string, 0, len(conf.Servers))
	for _, s := range conf.Servers {
		out = append(out, string(s.ID))
	}
	sort.Strings(out)
	return out
}

// assuranceConfigurations asks the node's main thread for its current view of the
// tracked configurations, mirroring the pattern used by takeSnapshot.
func assuranceConfigurations(r *Raft) configurations {
	fut := &configurationsFuture{}
	fut.ShutdownCh = r.shutdownCh
	fut.init()
	select {
	case r.configurationsCh <- fut:
	case <-r.shutdownCh:
		return configurations{}
	}
	if err := fut.Error(); err != nil {
		return configurations{}
	}
	return fut.configurations
}

// assuranceRunCase restarts the node on top of the stored prefix and reports what the
// recovered node does with its configuration.
func assuranceRunCase(t *testing.T, caseName string, withSnapshot, restoreCommittedLogs bool) {
	t.Helper()

	stores := assuranceBuildPrefix(t, withSnapshot, caseName)
	stagedCommit, err := stores.logs.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex failed: %v", err)
	}
	lastIndex, err := stores.logs.LastIndex()
	if err != nil {
		t.Fatalf("LastIndex failed: %v", err)
	}
	logConfigs, err := assuranceLogConfigEntries(stores.logs, lastIndex)
	if err != nil {
		t.Fatalf("log scan failed: %v", err)
	}

	// The fresh transport keeps the node's address (and therefore its ID) stable.
	_, trans := NewInmemTransport(stores.addr)
	conf := *stores.conf
	conf.RestoreCommittedLogs = restoreCommittedLogs

	assuranceEmit(assuranceEvent{
		"event":                   "assurance.restart." + caseName,
		"case":                    caseName,
		"restore_committed_logs":  restoreCommittedLogs,
		"snapshot_present":        withSnapshot,
		"log_last_index":          lastIndex,
		"staged_commit_index":     stagedCommit,
		"log_last_config_index":   logConfigs.lastIndex,
		"log_last_config_voters":  logConfigs.lastVoters,
		"log_last_config_servers": logConfigs.lastVoters + logConfigs.lastNonvoters,
	})

	r, err := NewRaft(&conf, &MockFSM{}, stores.logs, stores.stable, stores.snaps, trans)
	if err != nil {
		assuranceEmit(assuranceEvent{
			"event":                  "assurance.outcome." + caseName,
			"case":                   caseName,
			"restore_committed_logs": restoreCommittedLogs,
			"snapshot_present":       withSnapshot,
			"new_raft_error":         err.Error(),
		})
		return
	}

	// Observation window: 1.5s is 30 election/heartbeat timeouts of this in-memory
	// configuration (HeartbeatTimeout = ElectionTimeout = 50ms).
	deadline := time.Now().Add(1500 * time.Millisecond)
	leaderObserved := false
	polls := 0
	for time.Now().Before(deadline) {
		polls++
		if r.State() == Leader {
			leaderObserved = true
			break
		}
		time.Sleep(5 * time.Millisecond)
	}

	snapIndex, _ := r.getLastSnapshot()
	lastApplied := r.AppliedIndex()
	leaderAddr, leaderID := r.LeaderWithID()

	// Ask the main thread for the configuration the node is actually tracking.
	confs := assuranceConfigurations(r)
	latestVoters, latestNonvoters := assuranceSuffrageCounts(confs.latest)
	committedVoters, committedNonvoters := assuranceSuffrageCounts(confs.committed)
	latestIDs := assuranceSortedIDs(confs.latest)
	logIDs := logConfigs.lastIDs
	sameMembership := len(latestIDs) == len(logIDs)
	if sameMembership {
		for i := range latestIDs {
			if latestIDs[i] != logIDs[i] {
				sameMembership = false
				break
			}
		}
	}

	assuranceEmit(assuranceEvent{
		"event":                      "assurance.outcome." + caseName,
		"case":                       caseName,
		"restore_committed_logs":     restoreCommittedLogs,
		"snapshot_present":           withSnapshot,
		"leader_observed":            leaderObserved,
		"final_state":                r.State().String(),
		"polls":                      polls,
		"observation_ms":             1500,
		"leader_id":                  string(leaderID),
		"leader_addr":                string(leaderAddr),
		"latest_config_index":        confs.latestIndex,
		"committed_config_index":     confs.committedIndex,
		"latest_config_voters":       latestVoters,
		"latest_config_nonvoters":    latestNonvoters,
		"latest_config_ids":          assuranceConfigIDs(confs.latest),
		"committed_config_voters":    committedVoters,
		"committed_config_ids":       assuranceConfigIDs(confs.committed),
		"snapshot_index":             snapIndex,
		"last_applied":               lastApplied,
		"commit_index":               r.CommitIndex(),
		"last_index":                 r.LastIndex(),
		"committed_config_nonvoters": committedNonvoters,
	})

	// Does the recovered configuration equal the newest configuration entry in the
	// node's own log? Both operands are reported above; this flag is the comparison.
	matches := logConfigs.lastIndex != 0 &&
		sameMembership &&
		latestVoters == logConfigs.lastVoters &&
		latestNonvoters == logConfigs.lastNonvoters
	assuranceEmit(assuranceEvent{
		"event":                          "assurance.config_recovery." + caseName,
		"case":                           caseName,
		"restore_committed_logs":         restoreCommittedLogs,
		"snapshot_present":               withSnapshot,
		"log_last_config_index":          logConfigs.lastIndex,
		"log_last_config_voters":         logConfigs.lastVoters,
		"log_last_config_nonvoters":      logConfigs.lastNonvoters,
		"log_last_config_ids":            strings.Join(logConfigs.lastIDs, ","),
		"latest_config_index":            confs.latestIndex,
		"latest_config_voters":           latestVoters,
		"latest_config_nonvoters":        latestNonvoters,
		"latest_config_ids":              strings.Join(latestIDs, ","),
		"config_matches_last_log_config": matches,
	})

	_ = r.Shutdown().Error()
}

func TestAssuranceRestoreCommittedLogsConfigurationRecovery(t *testing.T) {
	assuranceRunCase(t, "no_snapshot_restore_on", false, true)
	assuranceRunCase(t, "no_snapshot_restore_off", false, false)
	assuranceRunCase(t, "snapshot_then_config_restore_on", true, true)
	assuranceRunCase(t, "snapshot_then_config_restore_off", true, false)
}

// TestAssuranceRestoreCommittedLogsReplayCompletion
//
// Sourced question: does the startup replay performed by restoreFromCommittedLogs
// always complete? processLogs hands batches to the FSM through a buffered channel
// whose only consumer (runFSM) is started at the end of NewRaft, and the send has no
// timeout: it waits for buffer space or shutdown. So a replay that needs more batches
// than the channel can hold blocks inside NewRaft, before the consumer exists.
//
// The harness builds prefixes whose committed log is far above their (absent)
// snapshot, restarts them with and without RestoreCommittedLogs, and reports whether
// NewRaft returned and what the blocked goroutine was doing.

func assuranceBuildReplayPrefix(t *testing.T, caseName string, entries, maxAppendEntries int) *assuranceStores {
	t.Helper()

	addr, trans := NewInmemTransport("")
	local := ServerID("server-" + string(addr))
	conf := inmemConfig(t)
	conf.LocalID = local
	conf.RestoreCommittedLogs = true
	// Keep the whole committed log above the snapshot: no automatic snapshot is taken,
	// so a restart replays every committed entry from index 1.
	conf.SnapshotThreshold = 1 << 30
	conf.SnapshotInterval = time.Hour
	conf.MaxAppendEntries = maxAppendEntries

	stores := &assuranceStores{
		addr:   addr,
		local:  local,
		conf:   conf,
		logs:   NewInmemCommitTrackingStore(),
		stable: NewInmemStore(),
		snaps:  NewInmemSnapshotStore(),
	}
	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       local,
		Address:  addr,
	}}}
	if err := BootstrapCluster(conf, stores.logs, stores.stable, stores.snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap failed: %v", err)
	}
	r, err := NewRaft(conf, &MockFSM{}, stores.logs, stores.stable, stores.snaps, trans)
	if err != nil {
		t.Fatalf("prefix NewRaft failed: %v", err)
	}
	if !assuranceWaitElected(t, r, 3*time.Second) {
		t.Fatalf("prefix node never became leader")
	}
	for i := 0; i < entries; i++ {
		if err := r.Apply([]byte("x"), 0).Error(); err != nil {
			t.Fatalf("prefix apply %d failed: %v", i, err)
		}
	}
	staged, err := stores.logs.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex failed: %v", err)
	}
	lastIndex, err := stores.logs.LastIndex()
	if err != nil {
		t.Fatalf("LastIndex failed: %v", err)
	}
	snapIndex, _ := r.getLastSnapshot()
	assuranceEmit(assuranceEvent{
		"event":               "assurance.replay_prefix",
		"case":                caseName,
		"commands_applied":    entries,
		"log_last_index":      lastIndex,
		"staged_commit_index": staged,
		"snapshot_index":      snapIndex,
		"max_append_entries":  conf.MaxAppendEntries,
		"replay_entries":      staged - snapIndex,
		"replay_batches":      (staged - snapIndex + uint64(conf.MaxAppendEntries) - 1) / uint64(conf.MaxAppendEntries),
	})
	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("prefix shutdown failed: %v", err)
	}
	return stores
}

// assuranceStackExcerpt returns the goroutine block that mentions marker.
func assuranceStackExcerpt(text string, marker string) (string, int) {
	count := strings.Count(text, marker)
	if count == 0 {
		return "", 0
	}
	idx := strings.Index(text, marker)
	start := idx - 200
	if start < 0 {
		start = 0
	}
	end := idx + 300
	if end > len(text) {
		end = len(text)
	}
	excerpt := strings.ReplaceAll(text[start:end], "\n", " | ")
	return excerpt, count
}

type assuranceReplayResult struct {
	raft     *Raft
	err      error
	elapsed  int64
	returned bool
}

func assuranceRunReplayCase(t *testing.T, caseName string, restoreCommittedLogs bool, entries, maxAppendEntries int) {
	t.Helper()

	stores := assuranceBuildReplayPrefix(t, caseName, entries, maxAppendEntries)
	staged, err := stores.logs.GetCommitIndex()
	if err != nil {
		t.Fatalf("GetCommitIndex failed: %v", err)
	}
	lastIndex, err := stores.logs.LastIndex()
	if err != nil {
		t.Fatalf("LastIndex failed: %v", err)
	}
	_, trans := NewInmemTransport(stores.addr)
	conf := *stores.conf
	conf.RestoreCommittedLogs = restoreCommittedLogs

	assuranceEmit(assuranceEvent{
		"event":                  "assurance.replay_restart." + caseName,
		"case":                   caseName,
		"restore_committed_logs": restoreCommittedLogs,
		"staged_commit_index":    staged,
		"log_last_index":         lastIndex,
		"max_append_entries":     conf.MaxAppendEntries,
		"replay_entries":         staged,
	})

	const waitMS = 8000
	ch := make(chan assuranceReplayResult, 1)
	go func() {
		start := time.Now()
		r, err := NewRaft(&conf, &MockFSM{}, stores.logs, stores.stable, stores.snaps, trans)
		ch <- assuranceReplayResult{raft: r, err: err, elapsed: time.Since(start).Milliseconds(), returned: true}
	}()

	var res assuranceReplayResult
	select {
	case res = <-ch:
	case <-time.After(waitMS * time.Millisecond):
	}

	outcome := assuranceEvent{
		"event":                  "assurance.replay_outcome." + caseName,
		"case":                   caseName,
		"restore_committed_logs": restoreCommittedLogs,
		"new_raft_returned":      res.returned,
		"wait_ms":                waitMS,
	}
	if res.returned {
		outcome["elapsed_ms"] = res.elapsed
	}
	if res.err != nil {
		outcome["new_raft_error"] = res.err.Error()
	}
	if !res.returned {
		buf := make([]byte, 1<<20)
		n := runtime.Stack(buf, true)
		excerpt, count := assuranceStackExcerpt(string(buf[:n]), "restoreFromCommittedLogs")
		outcome["stack_mentions"] = count
		outcome["blocked_excerpt"] = excerpt
	}
	assuranceEmit(outcome)

	if res.returned && res.raft != nil {
		leaderObserved := assuranceWaitElected(t, res.raft, time.Second)
		assuranceEmit(assuranceEvent{
			"event":                  "assurance.replay_leadership." + caseName,
			"case":                   caseName,
			"restore_committed_logs": restoreCommittedLogs,
			"leader_observed":        leaderObserved,
			"final_state":            res.raft.State().String(),
			"last_applied":           res.raft.AppliedIndex(),
			"commit_index":           res.raft.CommitIndex(),
		})
		_ = res.raft.Shutdown().Error()
	}
}

func TestAssuranceRestoreCommittedLogsReplayCompletion(t *testing.T) {
	const entries = 9000
	assuranceRunReplayCase(t, "large_replay_restore_on", true, entries, 64)
	assuranceRunReplayCase(t, "large_replay_restore_off", false, entries, 64)
}

// TestAssuranceRestoreCommittedLogsReplayBound
//
// Sourced question: does the completion of the startup replay track the product of the
// batch size and the channel capacity, rather than the amount of log alone? The replay
// delivers batches of at most config.MaxAppendEntries into a channel of capacity 128, so
// the number of batches is ceil(replay/MaxAppendEntries) and the bound sits at
// 128*MaxAppendEntries entries. This runs the same flag-on restart with a smaller legal
// MaxAppendEntries, once below that bound and once above it.
func TestAssuranceRestoreCommittedLogsReplayBound(t *testing.T) {
	const maxAppendEntries = 16 // bound: 128 * 16 = 2048 replayed entries
	assuranceRunReplayCase(t, "bound16_below_replay_on", true, 1500, maxAppendEntries)
	assuranceRunReplayCase(t, "bound16_above_replay_on", true, 3000, maxAppendEntries)
}

// assuranceTupleCount counts the entries in (from, to] that processLogs turns into commit
// tuples for the default protocol version: commands, barriers and configuration entries.
// No-op entries (and deprecated peer entries, and configuration entries below protocol 3)
// produce no tuple and therefore consume no batch space.
func assuranceTupleCount(logs *InmemCommitTrackingStore, from, to uint64) int {
	count := 0
	for idx := from + 1; idx <= to; idx++ {
		var entry Log
		if err := logs.GetLog(idx, &entry); err != nil {
			return count
		}
		switch entry.Type {
		case LogCommand, LogBarrier, LogConfiguration:
			count++
		}
	}
	return count
}

// assuranceBuildReplayPrefixToTarget builds a prefix whose persisted commit index is the
// given target, so a restart's replay batch count can be placed exactly on a boundary.
func assuranceBuildReplayPrefixToTarget(t *testing.T, caseName string, target uint64, maxAppendEntries int) *assuranceStores {
	t.Helper()

	addr, trans := NewInmemTransport("")
	local := ServerID("server-" + string(addr))
	conf := inmemConfig(t)
	conf.LocalID = local
	conf.RestoreCommittedLogs = true
	conf.SnapshotThreshold = 1 << 30
	conf.SnapshotInterval = time.Hour
	conf.MaxAppendEntries = maxAppendEntries

	stores := &assuranceStores{
		addr:   addr,
		local:  local,
		conf:   conf,
		logs:   NewInmemCommitTrackingStore(),
		stable: NewInmemStore(),
		snaps:  NewInmemSnapshotStore(),
	}
	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       local,
		Address:  addr,
	}}}
	if err := BootstrapCluster(conf, stores.logs, stores.stable, stores.snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap failed: %v", err)
	}
	r, err := NewRaft(conf, &MockFSM{}, stores.logs, stores.stable, stores.snaps, trans)
	if err != nil {
		t.Fatalf("prefix NewRaft failed: %v", err)
	}
	if !assuranceWaitElected(t, r, 3*time.Second) {
		t.Fatalf("prefix node never became leader")
	}

	applied := 0
	staged, _ := stores.logs.GetCommitIndex()
	for staged < target && applied < int(target)+64 {
		if err := r.Apply([]byte("x"), 0).Error(); err != nil {
			t.Fatalf("prefix apply %d failed: %v", applied, err)
		}
		applied++
		staged, _ = stores.logs.GetCommitIndex()
	}
	lastIndex, err := stores.logs.LastIndex()
	if err != nil {
		t.Fatalf("LastIndex failed: %v", err)
	}
	snapIndex, _ := r.getLastSnapshot()
	assuranceEmit(assuranceEvent{
		"event":               "assurance.boundary.prefix." + caseName,
		"case":                caseName,
		"commands_applied":    applied,
		"target_replay":       target,
		"log_last_index":      lastIndex,
		"staged_commit_index": staged,
		"snapshot_index":      snapIndex,
		"max_append_entries":  maxAppendEntries,
		"replay_entries":      staged - snapIndex,
		"replay_batches":      (staged - snapIndex + uint64(maxAppendEntries) - 1) / uint64(maxAppendEntries),
		"delivered_tuples":    assuranceTupleCount(stores.logs, snapIndex, staged),
		"delivered_batches":   (assuranceTupleCount(stores.logs, snapIndex, staged) + maxAppendEntries - 1) / maxAppendEntries,
	})
	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("prefix shutdown failed: %v", err)
	}
	return stores
}

// TestAssuranceRestoreCommittedLogsReplayBoundary places the flag-on replay on the two sides
// of the 128-batch channel capacity at MaxAppendEntries 16. The batch count follows the entries
// that processLogs turns into commit tuples (commands, configuration entries, barriers), not
// every log entry, so the two targets were chosen from an observed run of the same harness:
// a replay ending at index 2049 returned and one ending at 2050 is expected to block.
func TestAssuranceRestoreCommittedLogsReplayBoundary(t *testing.T) {
	// Each entry pairs a batch size with the two staged commit indices that straddle the
	// channel's capacity at that size: 128 batches times MaxAppendEntries, plus the single
	// no-op in the replayed range, which produces no commit tuple.
	cases := []struct {
		maxAppendEntries uint64
		target           uint64
	}{
		{16, 2049}, {16, 2050},
		{64, 8193}, {64, 8194},
	}
	for _, c := range cases {
		maxAppendEntries := int(c.maxAppendEntries)
		target := c.target
		caseName := fmt.Sprintf("boundary_%d_batch%d", target, maxAppendEntries)
		stores := assuranceBuildReplayPrefixToTarget(t, caseName, target, maxAppendEntries)
		staged, _ := stores.logs.GetCommitIndex()
		_, trans := NewInmemTransport(stores.addr)
		conf := *stores.conf
		conf.RestoreCommittedLogs = true

		assuranceEmit(assuranceEvent{
			"event":                  "assurance.boundary.restart." + caseName,
			"case":                   caseName,
			"restore_committed_logs": true,
			"max_append_entries":     maxAppendEntries,
			"replay_entries":         staged,
			"replay_batches":         (staged + uint64(maxAppendEntries) - 1) / uint64(maxAppendEntries),
			"delivered_tuples":       assuranceTupleCount(stores.logs, 0, staged),
			"delivered_batches":      (assuranceTupleCount(stores.logs, 0, staged) + maxAppendEntries - 1) / maxAppendEntries,
		})

		ch := make(chan assuranceReplayResult, 1)
		go func() {
			start := time.Now()
			r, err := NewRaft(&conf, &MockFSM{}, stores.logs, stores.stable, stores.snaps, trans)
			ch <- assuranceReplayResult{raft: r, err: err, elapsed: time.Since(start).Milliseconds(), returned: true}
		}()
		const waitMS = 8000
		var res assuranceReplayResult
		select {
		case res = <-ch:
		case <-time.After(waitMS * time.Millisecond):
		}
		outcome := assuranceEvent{
			"event":                  "assurance.boundary.outcome." + caseName,
			"case":                   caseName,
			"restore_committed_logs": true,
			"max_append_entries":     maxAppendEntries,
			"new_raft_returned":      res.returned,
			"wait_ms":                waitMS,
		}
		if res.returned {
			outcome["elapsed_ms"] = res.elapsed
		} else {
			buf := make([]byte, 1<<20)
			n := runtime.Stack(buf, true)
			excerpt, mentions := assuranceStackExcerpt(string(buf[:n]), "restoreFromCommittedLogs")
			outcome["stack_mentions"] = mentions
			outcome["blocked_excerpt"] = excerpt
		}
		assuranceEmit(outcome)
		if res.returned && res.raft != nil {
			_ = res.raft.Shutdown().Error()
		}
	}
}

// TestAssuranceRestoreCommittedLogsDefaultConfiguration
//
// Sourced question: does the replay bound depend on tuning SnapshotThreshold or
// MaxAppendEntries, or is it reachable with the library's own defaults? This harness
// builds single-voter prefixes with DefaultConfig untouched except for the replay flag
// and short node timeouts (SnapshotThreshold 8192, MaxAppendEntries 64, SnapshotInterval
// 120s), applies commands until the committed range above the newest snapshot passes the
// bound, and restarts the node with the replay on and off.
func assuranceRunDefaultConfigCase(t *testing.T, caseName string, restoreCommittedLogs bool, commands int) {
	t.Helper()

	addr, trans := NewInmemTransport("")
	local := ServerID("server-" + string(addr))
	conf := inmemConfig(t)
	conf.LocalID = local
	conf.RestoreCommittedLogs = true

	stores := &assuranceStores{
		addr:   addr,
		local:  local,
		conf:   conf,
		logs:   NewInmemCommitTrackingStore(),
		stable: NewInmemStore(),
		snaps:  NewInmemSnapshotStore(),
	}
	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       local,
		Address:  addr,
	}}}
	if err := BootstrapCluster(conf, stores.logs, stores.stable, stores.snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap failed: %v", err)
	}
	r, err := NewRaft(conf, &MockFSM{}, stores.logs, stores.stable, stores.snaps, trans)
	if err != nil {
		t.Fatalf("prefix NewRaft failed: %v", err)
	}
	if !assuranceWaitElected(t, r, 3*time.Second) {
		t.Fatalf("prefix node never became leader")
	}
	for i := 0; i < commands; i++ {
		if err := r.Apply([]byte("x"), 0).Error(); err != nil {
			t.Fatalf("prefix apply %d failed: %v", i, err)
		}
	}
	staged, _ := stores.logs.GetCommitIndex()
	lastIndex, _ := stores.logs.LastIndex()
	snapIndex, _ := r.getLastSnapshot()
	snapList, _ := stores.snaps.List()
	bound := uint64(128 * conf.MaxAppendEntries)
	delta := staged - snapIndex
	assuranceEmit(assuranceEvent{
		"event":                    "assurance.defaultcfg.prefix." + caseName,
		"case":                     caseName,
		"commands_applied":         commands,
		"log_last_index":           lastIndex,
		"staged_commit_index":      staged,
		"snapshot_index":           snapIndex,
		"snapshots_listed":         len(snapList),
		"max_append_entries":       conf.MaxAppendEntries,
		"snapshot_threshold":       conf.SnapshotThreshold,
		"snapshot_interval_s":      conf.SnapshotInterval.Seconds(),
		"committed_above_snapshot": delta,
		"bound_entries":            bound,
		"delta_exceeds_bound":      delta > bound,
	})
	if err := r.Shutdown().Error(); err != nil {
		t.Fatalf("prefix shutdown failed: %v", err)
	}

	_, trans2 := NewInmemTransport(stores.addr)
	conf2 := *stores.conf
	conf2.RestoreCommittedLogs = restoreCommittedLogs
	assuranceEmit(assuranceEvent{
		"event":                  "assurance.defaultcfg.restart." + caseName,
		"case":                   caseName,
		"restore_committed_logs": restoreCommittedLogs,
		"max_append_entries":     conf2.MaxAppendEntries,
		"snapshot_threshold":     conf2.SnapshotThreshold,
		"replay_entries":         delta,
		"replay_batches":         (delta + uint64(conf2.MaxAppendEntries) - 1) / uint64(conf2.MaxAppendEntries),
		"delta_exceeds_bound":    delta > bound,
	})

	ch := make(chan assuranceReplayResult, 1)
	go func() {
		start := time.Now()
		r2, err := NewRaft(&conf2, &MockFSM{}, stores.logs, stores.stable, stores.snaps, trans2)
		ch <- assuranceReplayResult{raft: r2, err: err, elapsed: time.Since(start).Milliseconds(), returned: true}
	}()
	const waitMS = 8000
	var res assuranceReplayResult
	select {
	case res = <-ch:
	case <-time.After(waitMS * time.Millisecond):
	}
	outcome := assuranceEvent{
		"event":                  "assurance.defaultcfg.outcome." + caseName,
		"case":                   caseName,
		"restore_committed_logs": restoreCommittedLogs,
		"max_append_entries":     conf2.MaxAppendEntries,
		"snapshot_threshold":     conf2.SnapshotThreshold,
		"replay_entries":         delta,
		"delta_exceeds_bound":    delta > bound,
		"new_raft_returned":      res.returned,
		"wait_ms":                waitMS,
	}
	if res.returned {
		outcome["elapsed_ms"] = res.elapsed
	} else {
		buf := make([]byte, 1<<20)
		n := runtime.Stack(buf, true)
		excerpt, mentions := assuranceStackExcerpt(string(buf[:n]), "restoreFromCommittedLogs")
		outcome["stack_mentions"] = mentions
		outcome["blocked_excerpt"] = excerpt
	}
	assuranceEmit(outcome)
	if res.returned && res.raft != nil {
		_ = res.raft.Shutdown().Error()
	}
}

func TestAssuranceRestoreCommittedLogsDefaultConfiguration(t *testing.T) {
	const commands = 12000
	assuranceRunDefaultConfigCase(t, "default_config_replay_on", true, commands)
	assuranceRunDefaultConfigCase(t, "default_config_replay_off", false, commands)
}
