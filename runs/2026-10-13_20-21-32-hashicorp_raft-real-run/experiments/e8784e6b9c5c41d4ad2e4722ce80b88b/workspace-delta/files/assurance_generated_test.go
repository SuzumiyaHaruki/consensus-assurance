package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

// restartAfterRecovery boots a single-node cluster, commits entries that
// include the bootstrap configuration entry, then restarts the node from the
// same on-disk state and reports the configuration the node holds in memory
// after NewRaft returns.
//
// No snapshot is ever taken, so restoreSnapshot cannot supply a configuration;
// the log is the only source of the configuration (LogStore is also the
// CommitTrackingLogStore whose persisted commit index drives
// restoreFromCommittedLogs).
func restartAfterRecovery(t *testing.T, restoreCommittedLogs bool) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = restoreCommittedLogs
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 1 << 40

	opts := &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)
	leader := c.Leader()

	for i := 0; i < 10; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("test%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}

	beforeLatestIndex := leader.configurations.latestIndex
	beforeCommittedIndex := leader.configurations.committedIndex
	beforeServers := len(leader.configurations.latest.Servers)
	snaps, err := leader.snapshots.List()
	if err != nil {
		t.Fatalf("list snapshots: %v", err)
	}

	mode := map[bool]string{true: "on", false: "off"}[restoreCommittedLogs]
	setup := map[string]interface{}{
		"event":                  "startup_before_restart",
		"mode":                   mode,
		"phase":                  "before_restart",
		"restore_committed_logs": restoreCommittedLogs,
		"snapshots":              len(snaps),
		"before_latest_index":    beforeLatestIndex,
		"before_committed_index": beforeCommittedIndex,
		"before_servers":         beforeServers,
		"peers":                  opts.Peers,
		"applied_entries":        10,
	}
	setupBytes, err := json.Marshal(setup)
	if err != nil {
		t.Fatalf("marshal setup: %v", err)
	}
	fmt.Println("CA_EVENT " + string(setupBytes))

	// Restart from the same logs/stable/snapshots stores.
	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown err: %v", err)
	}
	_, trans2 := NewInmemTransport(leader.trans.LocalAddr())
	cfg := leader.config()
	restarted, err := NewRaft(&cfg, leader.fsm, leader.logs, leader.stable, leader.snapshots, trans2)
	if err != nil {
		t.Fatalf("NewRaft err: %v", err)
	}
	c.rafts[0] = restarted
	defer c.Close()

	after := restarted.getLatestConfiguration()

	event := map[string]interface{}{
		"event":                  "restart_after_recovery",
		"phase":                  "after_restart",
		"mode":                   mode,
		"restore_committed_logs": restoreCommittedLogs,
		"snapshots":              len(snaps),
		"before_latest_index":    beforeLatestIndex,
		"before_committed_index": beforeCommittedIndex,
		"before_servers":         beforeServers,
		"after_latest_index":     restarted.configurations.latestIndex,
		"after_committed_index":  restarted.configurations.committedIndex,
		"after_servers":          len(after.Servers),
		"after_has_vote":         hasVote(after, restarted.localID),
		"after_quorum_size":      restarted.quorumSize(),
		"after_commit_index":     restarted.getCommitIndex(),
		"after_last_applied":     restarted.getLastApplied(),
		"after_last_log_index":   restarted.getLastIndex(),
	}
	b, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func TestAssuranceRestartConfigurationRecovery(t *testing.T) {
	restartAfterRecovery(t, true)
	restartAfterRecovery(t, false)
}

// restartAfterConfigChangeCommittedAfterSnapshot covers the registered gap: a
// committed LogConfiguration entry that is newer than the on-disk snapshot.
// A nonvoter is added so the change commits with a one-voter quorum, then the
// node is restarted from the same stores and the configuration it holds after
// NewRaft returns is compared with the configuration the log says is latest.
func restartAfterConfigChangeCommittedAfterSnapshot(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.SnapshotThreshold = 5
	conf.SnapshotInterval = 50 * time.Millisecond
	conf.TrailingLogs = 1 << 40

	opts := &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)
	leader := c.Leader()

	// Drive enough traffic for a snapshot to exist before the config change.
	deadline := time.Now().Add(20 * time.Second)
	var snaps []*SnapshotMeta
	for i := 0; time.Now().Before(deadline); i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("pre%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
		var err error
		snaps, err = leader.snapshots.List()
		if err != nil {
			t.Fatalf("list snapshots: %v", err)
		}
		if len(snaps) > 0 {
			break
		}
	}
	if len(snaps) == 0 {
		t.Fatal("no snapshot was taken before the configuration change")
	}

	// Commit a configuration change that is newer than the snapshot.
	cfgFuture := leader.AddNonvoter(ServerID("nonvoter-b"), ServerAddress("nonvoter-b"), 0, 5*time.Second)
	if err := cfgFuture.Error(); err != nil {
		t.Fatalf("AddNonvoter err: %v", err)
	}

	// Commit further entries so the persisted (staged) commit index advances
	// past the configuration entry's index; otherwise the entry would still sit
	// above the restored commit index and be re-scanned.
	for i := 0; i < 10; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("post%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}
	// Give the replication/commit path a moment to stage the newer index.
	time.Sleep(50 * time.Millisecond)

	expectedIndex := cfgFuture.Index()
	expectedServers := len(leader.configurations.latest.Servers)
	beforeLatestIndex := leader.configurations.latestIndex
	snapshotIndex := snaps[0].Index
	snapshotConfigIndex := snaps[0].ConfigurationIndex

	mode := "snapshot"
	setup := map[string]interface{}{
		"event":                  "startup_before_restart",
		"mode":                   mode,
		"phase":                  "before_restart",
		"restore_committed_logs": true,
		"snapshots":              len(snaps),
		"snapshot_index":         snapshotIndex,
		"snapshot_config_index":  snapshotConfigIndex,
		"expected_latest_index":  expectedIndex,
		"expected_servers":       expectedServers,
		"before_latest_index":    beforeLatestIndex,
	}
	setupBytes, err := json.Marshal(setup)
	if err != nil {
		t.Fatalf("marshal setup: %v", err)
	}
	fmt.Println("CA_EVENT " + string(setupBytes))

	// Restart from the same stores.
	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown err: %v", err)
	}
	_, trans2 := NewInmemTransport(leader.trans.LocalAddr())
	cfg := leader.config()
	restarted, err := NewRaft(&cfg, leader.fsm, leader.logs, leader.stable, leader.snapshots, trans2)
	if err != nil {
		t.Fatalf("NewRaft err: %v", err)
	}
	c.rafts[0] = restarted
	defer c.Close()

	after := restarted.getLatestConfiguration()
	matches := restarted.configurations.latestIndex == expectedIndex &&
		len(after.Servers) == expectedServers

	event := map[string]interface{}{
		"event":                  "restart_after_config_change",
		"mode":                   mode,
		"phase":                  "after_restart",
		"restore_committed_logs": true,
		"snapshots":              len(snaps),
		"snapshot_index":         snapshotIndex,
		"snapshot_config_index":  snapshotConfigIndex,
		"expected_latest_index":  expectedIndex,
		"expected_servers":       expectedServers,
		"before_latest_index":    beforeLatestIndex,
		"after_latest_index":     restarted.configurations.latestIndex,
		"after_servers":          len(after.Servers),
		"after_has_vote":         hasVote(after, restarted.localID),
		"after_commit_index":     restarted.getCommitIndex(),
		"after_last_applied":     restarted.getLastApplied(),
		"matches_committed_log":  matches,
	}
	eventBytes, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(eventBytes))
}

func TestAssuranceRestartConfigurationAfterSnapshot(t *testing.T) {
	restartAfterConfigChangeCommittedAfterSnapshot(t)
}

// restartWithBacklog boots a single node with RestoreCommittedLogs on, commits
// n entries without ever snapshotting, then restarts it and reports whether
// NewRaft returned within a bounded wait. The two sizes bracket the number of
// batches that processLogs pushes into the FSM queue before the FSM goroutine
// exists.
func restartWithBacklog(t *testing.T, n int, mode string) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 1 << 40

	opts := &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)
	leader := c.Leader()

	for i := 0; i < n; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("e%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}

	beforeCommit := leader.getCommitIndex()
	beforeLastLog, _ := leader.logs.LastIndex()
	snaps, err := leader.snapshots.List()
	if err != nil {
		t.Fatalf("list snapshots: %v", err)
	}

	setup := map[string]interface{}{
		"event":                  "startup_before_restart",
		"mode":                   mode,
		"phase":                  "before_restart",
		"restore_committed_logs": true,
		"snapshots":              len(snaps),
		"applied_entries":        n,
		"before_commit_index":    beforeCommit,
		"before_last_log_index":  beforeLastLog,
	}
	setupBytes, err := json.Marshal(setup)
	if err != nil {
		t.Fatalf("marshal setup: %v", err)
	}
	fmt.Println("CA_EVENT " + string(setupBytes))

	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown err: %v", err)
	}
	_, trans2 := NewInmemTransport(leader.trans.LocalAddr())
	cfg := leader.config()

	returned := false
	restartStart := time.Now()
	done := make(chan struct{})
	go func() {
		_, err := NewRaft(&cfg, leader.fsm, leader.logs, leader.stable, leader.snapshots, trans2)
		if err == nil {
			returned = true
		}
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(15 * time.Second):
	}
	restartMs := time.Since(restartStart).Milliseconds()

	resultEvent := "restart_backlog_below"
	if mode == "above_buffer" {
		resultEvent = "restart_backlog_above"
	}
	event := map[string]interface{}{
		"event":                  resultEvent,
		"mode":                   mode,
		"phase":                  "after_restart",
		"restore_committed_logs": true,
		"snapshots":              len(snaps),
		"applied_entries":        n,
		"before_commit_index":    beforeCommit,
		"before_last_log_index":  beforeLastLog,
		"newraft_returned":       returned,
		"restart_wait_ms":        restartMs,
	}
	eventBytes, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(eventBytes))

	for _, r := range c.rafts {
		_ = r.Shutdown()
	}
}

func TestAssuranceRestartWithBacklog(t *testing.T) {
	restartWithBacklog(t, 8000, "below_buffer")
	restartWithBacklog(t, 8400, "above_buffer")
}

// authorityAfterRestart restarts a single-node cluster from the same stores and
// then samples the node's state for a bounded interval, reporting whether the
// node ever acquires leadership. This is the bounded-liveness consequence of a
// configuration that was not rebuilt from the committed log.
func authorityAfterRestart(t *testing.T, restoreCommittedLogs bool, mode string) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = restoreCommittedLogs
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 1 << 40

	opts := &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	}
	c := MakeClusterCustom(t, opts)
	leader := c.Leader()

	for i := 0; i < 10; i++ {
		if err := leader.Apply([]byte(fmt.Sprintf("a%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}
	beforeLatest := leader.configurations.latestIndex
	snaps, err := leader.snapshots.List()
	if err != nil {
		t.Fatalf("list snapshots: %v", err)
	}

	setup := map[string]interface{}{
		"event":                  "startup_before_restart",
		"mode":                   mode,
		"phase":                  "before_restart",
		"restore_committed_logs": restoreCommittedLogs,
		"snapshots":              len(snaps),
		"before_latest_index":    beforeLatest,
	}
	setupBytes, err := json.Marshal(setup)
	if err != nil {
		t.Fatalf("marshal setup: %v", err)
	}
	fmt.Println("CA_EVENT " + string(setupBytes))

	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown err: %v", err)
	}
	_, trans2 := NewInmemTransport(leader.trans.LocalAddr())
	cfg := leader.config()
	restarted, err := NewRaft(&cfg, leader.fsm, leader.logs, leader.stable, leader.snapshots, trans2)
	if err != nil {
		t.Fatalf("NewRaft err: %v", err)
	}
	c.rafts[0] = restarted
	defer c.Close()

	const wait = 1500 * time.Millisecond
	becameLeader := false
	deadline := time.Now().Add(wait)
	var final RaftState
	for time.Now().Before(deadline) {
		final = restarted.getState()
		if final == Leader {
			becameLeader = true
			break
		}
		time.Sleep(10 * time.Millisecond)
	}

	event := map[string]interface{}{
		"event":                  "authority_after_restart",
		"mode":                   mode,
		"phase":                  "after_restart",
		"restore_committed_logs": restoreCommittedLogs,
		"snapshots":              len(snaps),
		"before_latest_index":    beforeLatest,
		"after_latest_index":     restarted.configurations.latestIndex,
		"became_leader":          becameLeader,
		"final_state":            final.String(),
		"sample_window_ms":       wait.Milliseconds(),
	}
	eventBytes, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(eventBytes))
}

func TestAssuranceAuthorityAfterRestart(t *testing.T) {
	authorityAfterRestart(t, true, "authority_on")
	authorityAfterRestart(t, false, "authority_off")
}

// multiVoterStaleConfigElection grows a three-voter cluster to four voters after
// the restarted node's snapshot was taken, restarts that node, and then
// partitions it together with a single other voter. If the node rebuilds the
// committed configuration it needs three votes and cannot win; if it falls back
// to the snapshot's three-voter configuration it needs only two and can become
// leader with support that is a minority of the committed configuration.
func multiVoterStaleConfigElection(t *testing.T, restoreCommittedLogs bool, mode string) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = restoreCommittedLogs
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 1 << 40

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})
	followers := c.Followers()
	partner := followers[0]
	// The restarted node is the leader: its commit index is staged on every
	// dispatch, so the persisted index advances past the configuration entry.
	target := c.Leader()

	// Take exactly one snapshot, while the configuration is still the
	// three-voter bootstrap configuration, and leave automatic snapshots off so
	// nothing newer can cover the later configuration change.
	for i := 0; i < 10; i++ {
		if err := c.Leader().Apply([]byte(fmt.Sprintf("pre%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}
	if err := target.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot err: %v", err)
	}
	snaps, err := target.snapshots.List()
	if err != nil {
		t.Fatalf("list snapshots: %v", err)
	}
	if len(snaps) == 0 {
		t.Fatal("target never took a snapshot")
	}

	// Grow the committed configuration to five voters, so that one side of the
	// later partition still holds a majority of the committed configuration
	// while the restarted node holds only its stale, smaller configuration.
	c1 := MakeClusterNoBootstrap(2, t, inmemConfig(t))
	c.Merge(c1)
	c.FullyConnect()
	for i := len(c.rafts) - 2; i < len(c.rafts); i++ {
		extra := c.rafts[i]
		if err := target.AddVoter(extra.localID, extra.localAddr, 0, 5*time.Second).Error(); err != nil {
			t.Fatalf("AddVoter err: %v", err)
		}
	}

	// Commit further entries so the persisted commit index passes the
	// configuration entry, and let the target catch up completely.
	for i := 0; i < 10; i++ {
		if err := target.Apply([]byte(fmt.Sprintf("post%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}
	time.Sleep(50 * time.Millisecond)

	expectedIndex := target.configurations.latestIndex
	expectedServers := len(target.configurations.latest.Servers)

	setup := map[string]interface{}{
		"event":                  "startup_before_restart",
		"mode":                   mode,
		"phase":                  "before_restart",
		"restore_committed_logs": restoreCommittedLogs,
		"snapshots":              len(snaps),
		"snapshot_index":         snaps[0].Index,
		"snapshot_config_index":  snaps[0].ConfigurationIndex,
		"expected_latest_index":  expectedIndex,
		"expected_servers":       expectedServers,
		"before_latest_index":    target.configurations.latestIndex,
	}
	setupBytes, err := json.Marshal(setup)
	if err != nil {
		t.Fatalf("marshal setup: %v", err)
	}
	fmt.Println("CA_EVENT " + string(setupBytes))

	// Restart the target from its own stores.
	targetIdx := -1
	for i, r := range c.rafts {
		if r == target {
			targetIdx = i
		}
	}
	if targetIdx < 0 {
		t.Fatal("target not found in cluster")
	}
	if err := target.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown err: %v", err)
	}
	// The majority side should elect a new leader while the target is down.
	newLeaderDeadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(newLeaderDeadline) {
		if len(c.GetInState(Leader)) > 0 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	_, trans2 := NewInmemTransport(target.trans.LocalAddr())
	cfg := target.config()
	restarted, err := NewRaft(&cfg, target.fsm, target.logs, target.stable, target.snapshots, trans2)
	if err != nil {
		t.Fatalf("NewRaft err: %v", err)
	}
	c.trans[targetIdx] = trans2
	c.rafts[targetIdx] = restarted
	c.FullyConnect()

	afterCfg := restarted.getLatestConfiguration()
	afterIndex := restarted.configurations.latestIndex
	afterServers := len(afterCfg.Servers)
	configMatches := afterIndex == expectedIndex && afterServers == expectedServers

	restartEvent := map[string]interface{}{
		"event":                  "imv_after_restart",
		"mode":                   mode,
		"phase":                  "after_restart",
		"snapshots":              len(snaps),
		"restore_committed_logs": restoreCommittedLogs,
		"expected_latest_index":  expectedIndex,
		"expected_servers":       expectedServers,
		"after_latest_index":     afterIndex,
		"after_servers":          afterServers,
		"config_matches":         configMatches,
	}
	restartBytes, err := json.Marshal(restartEvent)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(restartBytes))

	// Isolate the restarted node together with one other committed voter.
	far := []ServerAddress{}
	for _, r := range c.rafts {
		if r != restarted && r != partner {
			far = append(far, r.localAddr)
		}
	}
	c.Partition(far)

	reachableVotes := 2 // the restarted node and its single partner
	committedQuorum := expectedServers/2 + 1
	becameLeader := false
	electionDeadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(electionDeadline) {
		if restarted.getState() == Leader {
			becameLeader = true
			break
		}
		time.Sleep(10 * time.Millisecond)
	}

	// Did a leader on the majority side keep its authority meanwhile?
	otherLeader := false
	for _, r := range c.rafts {
		if r != restarted && r != partner && r.getState() == Leader {
			otherLeader = true
		}
	}

	electionEvent := map[string]interface{}{
		"event":                        "multivoter_partition_election",
		"mode":                         mode,
		"phase":                        "after_partition",
		"snapshots":                    len(snaps),
		"restore_committed_logs":       restoreCommittedLogs,
		"expected_servers":             expectedServers,
		"after_servers":                afterServers,
		"reachable_votes":              reachableVotes,
		"committed_quorum":             committedQuorum,
		"became_leader":                becameLeader,
		"leader_below_committed_quorum": becameLeader && reachableVotes < committedQuorum,
		"majority_side_leader":         otherLeader,
	}
	electionBytes, err := json.Marshal(electionEvent)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(electionBytes))

	c.Close()
}

func TestAssuranceMultiVoterStaleConfig(t *testing.T) {
	multiVoterStaleConfigElection(t, true, "mv_on")
	multiVoterStaleConfigElection(t, false, "mv_off")
}

// multiVoterImmediateIsolation is the schedule variation of the multi-voter
// scenario: the restarted node is cut off from everyone except one committed
// voter as soon as NewRaft returns, so it cannot first learn the majority-side
// leader. Its stale configuration needs two votes and the committed five-voter
// configuration needs three.
func multiVoterImmediateIsolation(t *testing.T, restoreCommittedLogs bool, mode string) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = restoreCommittedLogs
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 1 << 40

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})
	followers := c.Followers()
	partner := followers[0]
	target := c.Leader()

	for i := 0; i < 10; i++ {
		if err := target.Apply([]byte(fmt.Sprintf("pre%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}
	if err := target.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot err: %v", err)
	}
	snaps, err := target.snapshots.List()
	if err != nil {
		t.Fatalf("list snapshots: %v", err)
	}
	if len(snaps) == 0 {
		t.Fatal("target never took a snapshot")
	}

	c1 := MakeClusterNoBootstrap(2, t, inmemConfig(t))
	c.Merge(c1)
	c.FullyConnect()
	for i := len(c.rafts) - 2; i < len(c.rafts); i++ {
		extra := c.rafts[i]
		if err := target.AddVoter(extra.localID, extra.localAddr, 0, 5*time.Second).Error(); err != nil {
			t.Fatalf("AddVoter err: %v", err)
		}
	}
	for i := 0; i < 10; i++ {
		if err := target.Apply([]byte(fmt.Sprintf("post%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}
	time.Sleep(50 * time.Millisecond)

	expectedIndex := target.configurations.latestIndex
	expectedServers := len(target.configurations.latest.Servers)

	setup := map[string]interface{}{
		"event":                  "startup_before_restart",
		"mode":                   mode,
		"phase":                  "before_restart",
		"restore_committed_logs": restoreCommittedLogs,
		"snapshots":              len(snaps),
		"snapshot_index":         snaps[0].Index,
		"snapshot_config_index":  snaps[0].ConfigurationIndex,
		"expected_latest_index":  expectedIndex,
		"expected_servers":       expectedServers,
	}
	setupBytes, err := json.Marshal(setup)
	if err != nil {
		t.Fatalf("marshal setup: %v", err)
	}
	fmt.Println("CA_EVENT " + string(setupBytes))

	targetIdx := -1
	for i, r := range c.rafts {
		if r == target {
			targetIdx = i
		}
	}
	if targetIdx < 0 {
		t.Fatal("target not found")
	}
	targetAddr := target.localAddr
	if err := target.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown err: %v", err)
	}
	_, trans2 := NewInmemTransport(targetAddr)
	cfg := target.config()
	restarted, err := NewRaft(&cfg, target.fsm, target.logs, target.stable, target.snapshots, trans2)
	if err != nil {
		t.Fatalf("NewRaft err: %v", err)
	}
	c.trans[targetIdx] = trans2
	c.rafts[targetIdx] = restarted

	// Isolate the restarted node from everyone except one committed voter
	// before it can learn the majority-side leader.
	var partnerTrans LoopbackTransport
	for _, t := range c.trans {
		if t.LocalAddr() == partner.localAddr {
			partnerTrans = t
		}
	}
	if partnerTrans == nil {
		t.Fatal("partner transport not found")
	}
	far := []ServerAddress{}
	for _, r := range c.rafts {
		if r != restarted && r != partner {
			far = append(far, r.localAddr)
		}
	}
	c.Partition(far)
	trans2.Connect(partnerTrans.LocalAddr(), partnerTrans)
	partnerTrans.Connect(restarted.localAddr, trans2)

	afterCfg := restarted.getLatestConfiguration()
	restartEvent := map[string]interface{}{
		"event":                  "imv_after_restart",
		"mode":                   mode,
		"phase":                  "after_restart",
		"snapshots":              len(snaps),
		"restore_committed_logs": restoreCommittedLogs,
		"expected_latest_index":  expectedIndex,
		"expected_servers":       expectedServers,
		"after_latest_index":     restarted.configurations.latestIndex,
		"after_servers":          len(afterCfg.Servers),
		"config_matches": restarted.configurations.latestIndex == expectedIndex &&
			len(afterCfg.Servers) == expectedServers,
	}
	restartBytes, err := json.Marshal(restartEvent)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(restartBytes))

	reachableVotes := 2
	committedQuorum := expectedServers/2 + 1
	becameLeader := false
	electionDeadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(electionDeadline) {
		if restarted.getState() == Leader {
			becameLeader = true
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	otherLeader := false
	for _, r := range c.rafts {
		if r != restarted && r != partner && r.getState() == Leader {
			otherLeader = true
		}
	}

	electionEvent := map[string]interface{}{
		"event":                         "imv_partition_election",
		"mode":                          mode,
		"phase":                         "after_partition",
		"snapshots":                     len(snaps),
		"restore_committed_logs":        restoreCommittedLogs,
		"expected_servers":              expectedServers,
		"after_servers":                 len(afterCfg.Servers),
		"reachable_votes":               reachableVotes,
		"committed_quorum":              committedQuorum,
		"became_leader":                 becameLeader,
		"leader_below_committed_quorum": becameLeader && reachableVotes < committedQuorum,
		"majority_side_leader":          otherLeader,
		"restarted_term":                restarted.getCurrentTerm(),
		"partner_term":                  partner.getCurrentTerm(),
		"restarted_last_log":            restarted.getLastIndex(),
	}
	electionBytes, err := json.Marshal(electionEvent)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(electionBytes))
	c.Close()
}

func TestAssuranceMultiVoterImmediateIsolation(t *testing.T) {
	multiVoterImmediateIsolation(t, true, "mv2_on")
	multiVoterImmediateIsolation(t, false, "mv2_off")
}

// multiVoterDivergence follows the immediate-isolation scenario one step
// further: each side commits its own entry while partitioned, then the
// partition heals and the applied state of the two FSMs is compared at the
// index where the two sides wrote different values.
func multiVoterDivergence(t *testing.T, restoreCommittedLogs bool, mode string) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = restoreCommittedLogs
	conf.SnapshotThreshold = 1 << 40
	conf.SnapshotInterval = 10 * time.Minute
	conf.TrailingLogs = 1 << 40

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})
	followers := c.Followers()
	partner := followers[0]
	target := c.Leader()

	for i := 0; i < 10; i++ {
		if err := target.Apply([]byte(fmt.Sprintf("pre%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}
	if err := target.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot err: %v", err)
	}

	c1 := MakeClusterNoBootstrap(2, t, inmemConfig(t))
	c.Merge(c1)
	c.FullyConnect()
	for i := len(c.rafts) - 2; i < len(c.rafts); i++ {
		extra := c.rafts[i]
		if err := target.AddVoter(extra.localID, extra.localAddr, 0, 5*time.Second).Error(); err != nil {
			t.Fatalf("AddVoter err: %v", err)
		}
	}
	for i := 0; i < 5; i++ {
		if err := target.Apply([]byte(fmt.Sprintf("post%d", i)), 0).Error(); err != nil {
			t.Fatalf("apply err: %v", err)
		}
	}
	time.Sleep(50 * time.Millisecond)

	expectedServers := len(target.configurations.latest.Servers)
	snaps, err := target.snapshots.List()
	if err != nil {
		t.Fatalf("list snapshots: %v", err)
	}
	setup := map[string]interface{}{
		"event":                  "startup_before_restart",
		"mode":                   mode,
		"phase":                  "before_restart",
		"restore_committed_logs": restoreCommittedLogs,
		"snapshots":              len(snaps),
		"expected_servers":       expectedServers,
		"expected_latest_index":  target.configurations.latestIndex,
	}
	setupBytes, err := json.Marshal(setup)
	if err != nil {
		t.Fatalf("marshal setup: %v", err)
	}
	fmt.Println("CA_EVENT " + string(setupBytes))

	targetIdx := -1
	for i, r := range c.rafts {
		if r == target {
			targetIdx = i
		}
	}
	targetAddr := target.localAddr
	if err := target.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown err: %v", err)
	}
	_, trans2 := NewInmemTransport(targetAddr)
	cfg := target.config()
	restarted, err := NewRaft(&cfg, target.fsm, target.logs, target.stable, target.snapshots, trans2)
	if err != nil {
		t.Fatalf("NewRaft err: %v", err)
	}
	c.trans[targetIdx] = trans2
	c.rafts[targetIdx] = restarted
	c.fsms[targetIdx] = target.fsm

	var partnerTrans LoopbackTransport
	for _, tr := range c.trans {
		if tr.LocalAddr() == partner.localAddr {
			partnerTrans = tr
		}
	}
	if partnerTrans == nil {
		t.Fatal("partner transport not found")
	}
	far := []ServerAddress{}
	for _, r := range c.rafts {
		if r != restarted && r != partner {
			far = append(far, r.localAddr)
		}
	}
	c.Partition(far)
	trans2.Connect(partnerTrans.LocalAddr(), partnerTrans)
	partnerTrans.Connect(restarted.localAddr, trans2)

	// Let the isolated side elect under its stale configuration.
	minorityDeadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(minorityDeadline) && restarted.getState() != Leader {
		time.Sleep(10 * time.Millisecond)
	}
	minorityLeader := restarted.getState() == Leader

	// The majority side should keep (or elect) its own leader.
	var majority *Raft
	majorityDeadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(majorityDeadline) {
		for _, r := range c.rafts {
			if r != restarted && r != partner && r.getState() == Leader {
				majority = r
			}
		}
		if majority != nil {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}

	minorityApplyErr := "no-leader"
	majorityApplyErr := "no-leader"
	if minorityLeader {
		if err := restarted.Apply([]byte("minority-entry"), 2*time.Second).Error(); err != nil {
			minorityApplyErr = err.Error()
		} else {
			minorityApplyErr = ""
		}
	}
	if majority != nil {
		if err := majority.Apply([]byte("majority-entry"), 2*time.Second).Error(); err != nil {
			majorityApplyErr = err.Error()
		} else {
			majorityApplyErr = ""
		}
	}

	minorityIndex := restarted.getLastIndex()

	// Heal the partition and let the two sides exchange again.
	c.FullyConnect()
	time.Sleep(2 * time.Second)

	minorityFSM := getMockFSM(restarted.fsm)
	minorityFSM.Lock()
	minorityLogs := append([][]byte(nil), minorityFSM.logs...)
	minorityFSM.Unlock()

	var majorityLogs [][]byte
	majorityID := ""
	if majority != nil {
		majorityID = string(majority.localID)
		mFSM := getMockFSM(majority.fsm)
		mFSM.Lock()
		majorityLogs = append([][]byte(nil), mFSM.logs...)
		mFSM.Unlock()
	}

	minorityEntry := ""
	if minorityIndex > 0 && int(minorityIndex) <= len(minorityLogs) {
		minorityEntry = string(minorityLogs[minorityIndex-1])
	}
	majorityEntry := ""
	if minorityIndex > 0 && int(minorityIndex) <= len(majorityLogs) {
		majorityEntry = string(majorityLogs[minorityIndex-1])
	}
	divergence := majorityEntry != "" && minorityEntry != "" && minorityEntry != majorityEntry

	event := map[string]interface{}{
		"event":                  "mvdiv_after_heal",
		"mode":                   mode,
		"phase":                  "after_heal",
		"snapshots":              len(snaps),
		"restore_committed_logs": restoreCommittedLogs,
		"expected_servers":       expectedServers,
		"minority_leader":        minorityLeader,
		"minority_apply_ok":      minorityApplyErr == "",
		"majority_leader":        majority != nil,
		"majority_apply_ok":      majorityApplyErr == "",
		"conflict_index":         minorityIndex,
		"minority_entry":         minorityEntry,
		"majority_entry":         majorityEntry,
		"majority_id":            majorityID,
		"fsm_divergence":         divergence,
		"both_sides_acknowledged": minorityApplyErr == "" && majorityApplyErr == "",
		"minority_fsm_has_entry": containsBytes(minorityLogs, "minority-entry"),
		"minority_log_has_entry": logContains(t, restarted.logs, "minority-entry"),
		"majority_fsm_has_entry": majority != nil && containsBytes(majorityLogs, "majority-entry"),
		"majority_log_has_entry": majority != nil && logContains(t, majority.logs, "majority-entry"),
		"majority_applied_without_log": majority != nil && containsBytes(majorityLogs, "majority-entry") && !logContains(t, majority.logs, "majority-entry"),
		"applied_without_log":   containsBytes(minorityLogs, "minority-entry") && !logContains(t, restarted.logs, "minority-entry"),
		"minority_applied_len":   len(minorityLogs),
		"majority_applied_len":   len(majorityLogs),
	}
	eventBytes, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(eventBytes))
	c.Close()
}

func TestAssuranceMultiVoterDivergence(t *testing.T) {
	multiVoterDivergence(t, true, "div_on")
	multiVoterDivergence(t, false, "div_off")
}

// containsBytes reports whether any applied entry equals want.
func containsBytes(entries [][]byte, want string) bool {
	for _, e := range entries {
		if string(e) == want {
			return true
		}
	}
	return false
}

// logContains reports whether the log store still holds an entry whose data is
// want, scanning the retained range.
func logContains(t *testing.T, store LogStore, want string) bool {
	first, err := store.FirstIndex()
	if err != nil {
		return false
	}
	last, err := store.LastIndex()
	if err != nil {
		return false
	}
	for idx := first; idx <= last; idx++ {
		var l Log
		if err := store.GetLog(idx, &l); err != nil {
			continue
		}
		if string(l.Data) == want {
			return true
		}
	}
	return false
}
