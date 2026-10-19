package raft

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"runtime"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

type auditNoopFSM struct{}

func (auditNoopFSM) Apply(*Log) interface{}         { return nil }
func (auditNoopFSM) Restore(io.ReadCloser) error    { return nil }
func (auditNoopFSM) Snapshot() (FSMSnapshot, error) { return nil, errors.New("not supported") }

// atomicCommitStore follows the CommitTrackingLogStore contract: a staged
// commit index is only made visible to GetCommitIndex after the following
// StoreLogs succeeds.
type atomicCommitStore struct {
	store  *InmemCommitTrackingStore
	staged atomic.Uint64
}

var _ CommitTrackingLogStore = (*atomicCommitStore)(nil)

func newAtomicCommitStore() *atomicCommitStore {
	return &atomicCommitStore{store: NewInmemCommitTrackingStore()}
}

func (s *atomicCommitStore) FirstIndex() (uint64, error) { return s.store.FirstIndex() }
func (s *atomicCommitStore) LastIndex() (uint64, error)  { return s.store.LastIndex() }
func (s *atomicCommitStore) GetLog(i uint64, l *Log) error {
	return s.store.GetLog(i, l)
}
func (s *atomicCommitStore) StoreLog(l *Log) error { return s.StoreLogs([]*Log{l}) }
func (s *atomicCommitStore) StoreLogs(logs []*Log) error {
	if err := s.store.StoreLogs(logs); err != nil {
		return err
	}
	return s.store.StageCommitIndex(s.staged.Load())
}
func (s *atomicCommitStore) DeleteRange(min, max uint64) error {
	return s.store.DeleteRange(min, max)
}
func (s *atomicCommitStore) StageCommitIndex(i uint64) error { s.staged.Store(i); return nil }
func (s *atomicCommitStore) GetCommitIndex() (uint64, error) { return s.store.GetCommitIndex() }

// A membership change committed after the latest snapshot must be reflected in
// the restarted node's configuration. The snapshot carries only the old
// membership; the configuration log entry after it is committed and present in
// the log.
func TestAuditRestoreCommittedLogsSnapshotStaleMembership(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 3
	conf.RestoreCommittedLogs = true

	id1 := ServerID("node1")
	id2 := ServerID("node2")
	addr1 := ServerAddress("node1")
	addr2 := ServerAddress("node2")
	conf.LocalID = id1

	logs := newAtomicCommitStore()
	stable := NewInmemStore()
	snapshots := NewInmemSnapshotStore()
	_, trans := NewInmemTransport(addr1)

	oldConf := Configuration{Servers: []Server{{Suffrage: Voter, ID: id1, Address: addr1}}}
	newConf := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: id1, Address: addr1},
		{Suffrage: Voter, ID: id2, Address: addr2},
	}}
	require.NoError(t, BootstrapCluster(conf, logs, stable, snapshots, trans, oldConf))
	require.NoError(t, logs.StoreLog(&Log{Index: 2, Term: 1, Type: LogCommand, Data: []byte("x")}))

	// Snapshot at index 2 with the old, one-node configuration.
	sink, err := snapshots.Create(SnapshotVersionMax, 2, 1, oldConf, 1, trans)
	require.NoError(t, err)
	_, err = sink.Write([]byte("snapshot"))
	require.NoError(t, err)
	require.NoError(t, sink.Close())

	// Commit a membership change after the snapshot.
	require.NoError(t, logs.StageCommitIndex(3))
	require.NoError(t, logs.StoreLog(&Log{
		Index: 3, Term: 1, Type: LogConfiguration, Data: EncodeConfiguration(newConf),
	}))

	r, err := NewRaft(conf, auditNoopFSM{}, logs, stable, snapshots, trans)
	require.NoError(t, err)
	defer r.Shutdown()

	got := r.GetConfiguration().Configuration()
	t.Logf("configuration after restart: %+v (lastApplied=%d, commitIndex=%d)", got, r.getLastApplied(), r.getCommitIndex())
	assert.Equal(t, newConf, got,
		"committed configuration entry after the snapshot must be reflected after restart")
}

// Regression/audit test: when RestoreCommittedLogs is enabled and the
// persisted commit index covers a membership (configuration) log entry, a
// restart must still reconstruct the current configuration from the log.
//
// The persisted state below is exactly what BootstrapCluster produces for a
// single-node cluster plus the persisted commit index that the commit-tracking
// log store is supposed to keep atomic with StoreLogs. Entry 1 is committed.
func TestAuditRestoreCommittedLogsKeepsConfiguration(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 3
	conf.RestoreCommittedLogs = true

	id := ServerID("node1")
	addr := ServerAddress("node1")
	conf.LocalID = id

	logs := NewInmemCommitTrackingStore()
	stable := NewInmemStore()
	snapshots := NewInmemSnapshotStore()
	_, trans := NewInmemTransport(addr)

	want := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       id,
		Address:  addr,
	}}}
	require.NoError(t, BootstrapCluster(conf, logs, stable, snapshots, trans, want))

	// Entry 1 is the committed bootstrap configuration.
	require.NoError(t, logs.StageCommitIndex(1))

	r, err := NewRaft(conf, &MockFSM{}, logs, stable, snapshots, trans)
	require.NoError(t, err)
	defer r.Shutdown()

	// The node applied the committed configuration entry.
	require.Equal(t, uint64(1), r.getLastApplied())
	require.Equal(t, uint64(1), r.getCommitIndex())

	f := r.GetConfiguration()
	require.NoError(t, f.Error())
	got := f.Configuration()
	t.Logf("recovered configuration: %+v", got)
	assert.Equal(t, want, got, "configuration must be recovered from committed log entry 1")
	t.Logf("hasVote(after restart) = %v", hasVote(got, id))
	assert.True(t, hasVote(got, id), "restarted voter must still be a voter")
}

// Control: with the feature disabled, the same committed configuration entry
// is recovered by the normal startup scan.
func TestAuditRestoreCommittedLogsDisabledKeepsConfiguration(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 3
	conf.RestoreCommittedLogs = false

	id := ServerID("node1")
	addr := ServerAddress("node1")
	conf.LocalID = id

	logs := NewInmemCommitTrackingStore()
	stable := NewInmemStore()
	snapshots := NewInmemSnapshotStore()
	_, trans := NewInmemTransport(addr)
	want := Configuration{Servers: []Server{{Suffrage: Voter, ID: id, Address: addr}}}
	require.NoError(t, BootstrapCluster(conf, logs, stable, snapshots, trans, want))
	require.NoError(t, logs.StageCommitIndex(1))

	r, err := NewRaft(conf, &MockFSM{}, logs, stable, snapshots, trans)
	require.NoError(t, err)
	defer r.Shutdown()

	assert.Equal(t, want, r.GetConfiguration().Configuration())
}

// Same membership loss with a store that honors the interface contract: the
// staged commit index 1 becomes durable atomically with storing entry 2, so
// this is a state a conforming commit-tracking store can produce.
func TestAuditRestoreCommittedLogsConformingStore(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 3
	conf.RestoreCommittedLogs = true

	id := ServerID("node1")
	addr := ServerAddress("node1")
	conf.LocalID = id

	logs := newAtomicCommitStore()
	stable := NewInmemStore()
	snapshots := NewInmemSnapshotStore()
	_, trans := NewInmemTransport(addr)
	want := Configuration{Servers: []Server{{Suffrage: Voter, ID: id, Address: addr}}}
	require.NoError(t, BootstrapCluster(conf, logs, stable, snapshots, trans, want))

	// The production leader path stages the current commit index before
	// StoreLogs; model that with a valid new entry at index 2.
	require.NoError(t, logs.StageCommitIndex(1))
	require.NoError(t, logs.StoreLog(&Log{Index: 2, Term: 1, Type: LogNoop}))
	ci, err := logs.GetCommitIndex()
	require.NoError(t, err)
	require.Equal(t, uint64(1), ci)

	r, err := NewRaft(conf, &MockFSM{}, logs, stable, snapshots, trans)
	require.NoError(t, err)
	defer r.Shutdown()

	got := r.GetConfiguration().Configuration()
	t.Logf("configuration after restart: %+v (lastApplied=%d, commitIndex=%d)", got, r.getLastApplied(), r.getCommitIndex())
	assert.Equal(t, want, got, "configuration must survive restart with a conforming commit-tracking store")
}

// The package-level GetConfiguration helper uses NewRaft with skipStartup, so
// it inherits the same configuration-scan skip.
func TestAuditGetConfigurationRestoreCommittedLogs(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 3
	conf.RestoreCommittedLogs = true

	id := ServerID("node1")
	addr := ServerAddress("node1")
	conf.LocalID = id

	logs := newAtomicCommitStore()
	stable := NewInmemStore()
	snapshots := NewInmemSnapshotStore()
	_, trans := NewInmemTransport(addr)
	want := Configuration{Servers: []Server{{Suffrage: Voter, ID: id, Address: addr}}}
	require.NoError(t, BootstrapCluster(conf, logs, stable, snapshots, trans, want))
	require.NoError(t, logs.StageCommitIndex(1))
	require.NoError(t, logs.StoreLog(&Log{Index: 2, Term: 1, Type: LogNoop}))

	got, err := GetConfiguration(conf, &MockFSM{}, logs, stable, snapshots, trans)
	require.NoError(t, err)
	t.Logf("GetConfiguration returned: %+v", got)
	assert.Equal(t, want, got, "GetConfiguration must recover the committed membership")
}

// Control for the underlying replay claim: after a snapshot plus further
// committed commands, a restart with a fresh FSM should apply the post-snapshot
// commands as well as restoring the snapshot.
func TestAuditRestoreCommittedLogsReplaysPostSnapshotCommands(t *testing.T) {
	conf := inmemConfig(t)
	conf.TrailingLogs = 10
	conf.RestoreCommittedLogs = true
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})
	defer c.Close()

	leader := c.Leader()
	for i := 0; i < 100; i++ {
		require.NoError(t, leader.Apply([]byte(fmt.Sprintf("pre-%d", i)), 0).Error())
	}
	require.NoError(t, leader.Snapshot().Error())
	for i := 0; i < 50; i++ {
		require.NoError(t, leader.Apply([]byte(fmt.Sprintf("post-%d", i)), 0).Error())
	}
	require.NoError(t, leader.Shutdown().Error())

	_, trans := NewInmemTransport(leader.localAddr)
	cfg := leader.config()
	fsm := &MockFSM{}
	r, err := NewRaft(&cfg, fsm, leader.logs, leader.stable, leader.snapshots, trans)
	require.NoError(t, err)
	c.rafts[0] = r

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) && len(fsm.Logs()) < 150 {
		time.Sleep(5 * time.Millisecond)
	}
	t.Logf("FSM has %d commands after restart (lastApplied=%d, commitIndex=%d)",
		len(fsm.Logs()), r.getLastApplied(), r.getCommitIndex())
	assert.Len(t, fsm.Logs(), 150, "snapshot plus post-snapshot committed commands must all be replayed")
}

// Commit-index persistence is only staged on the append paths. Check whether a
// commit that advances without a new append leaves the store behind.
func TestAuditCommitIndexPersistenceOnHeartbeatOnlyCommit(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})
	defer c.Close()

	leader := c.Leader()
	for i := 0; i < 10; i++ {
		require.NoError(t, leader.Apply([]byte(fmt.Sprintf("cmd-%d", i)), 0).Error())
	}
	time.Sleep(200 * time.Millisecond)

	store, ok := leader.logs.(CommitTrackingLogStore)
	require.True(t, ok)
	persisted, err := store.GetCommitIndex()
	require.NoError(t, err)
	t.Logf("in-memory commitIndex=%d, persisted commitIndex=%d, lastLog=%d",
		leader.getCommitIndex(), persisted, leader.getLastIndex())
	assert.Equal(t, leader.getCommitIndex(), persisted,
		"persisted commit index should match the committed index for RestoreCommittedLogs")
}

// Document the optional-interface behavior: LogCache wraps an arbitrary
// LogStore but does not forward CommitTrackingLogStore, so RestoreCommittedLogs
// rejects the wrapper even when its underlying store supports the interface.
func TestAuditLogCacheDoesNotPreserveCommitTracking(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 3
	conf.RestoreCommittedLogs = true

	id := ServerID("node1")
	addr := ServerAddress("node1")
	conf.LocalID = id

	base := newAtomicCommitStore()
	cache, err := NewLogCache(16, base)
	require.NoError(t, err)
	stable := NewInmemStore()
	snapshots := NewInmemSnapshotStore()
	_, trans := NewInmemTransport(addr)
	cfg := Configuration{Servers: []Server{{Suffrage: Voter, ID: id, Address: addr}}}
	require.NoError(t, BootstrapCluster(conf, cache, stable, snapshots, trans, cfg))
	require.NoError(t, base.StageCommitIndex(1))
	require.NoError(t, cache.StoreLog(&Log{Index: 2, Term: 1, Type: LogNoop}))

	_, err = NewRaft(conf, &MockFSM{}, cache, stable, snapshots, trans)
	t.Logf("NewRaft through LogCache returned: %v", err)
	require.ErrorIs(t, err, ErrIncompatibleLogStore)
}

// A snapshot index is necessarily committed. If the persisted commit index
// lags behind it, the restart path should not expose a commit index lower than
// the applied/snapshot index.
func TestAuditCommitIndexBelowSnapshotAfterRestart(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 3
	conf.RestoreCommittedLogs = true

	id := ServerID("node1")
	addr := ServerAddress("node1")
	conf.LocalID = id

	logs := newAtomicCommitStore()
	stable := NewInmemStore()
	snapshots := NewInmemSnapshotStore()
	_, trans := NewInmemTransport(addr)
	cfg := Configuration{Servers: []Server{{Suffrage: Voter, ID: id, Address: addr}}}
	require.NoError(t, BootstrapCluster(conf, logs, stable, snapshots, trans, cfg))
	require.NoError(t, logs.StoreLog(&Log{Index: 2, Term: 1, Type: LogCommand, Data: []byte("x")}))

	sink, err := snapshots.Create(SnapshotVersionMax, 2, 1, cfg, 1, trans)
	require.NoError(t, err)
	_, err = sink.Write([]byte("snapshot"))
	require.NoError(t, err)
	require.NoError(t, sink.Close())

	// Persist a stale commit index (1) together with a later entry (3).
	require.NoError(t, logs.StageCommitIndex(1))
	require.NoError(t, logs.StoreLog(&Log{Index: 3, Term: 1, Type: LogNoop}))

	r, err := NewRaft(conf, auditNoopFSM{}, logs, stable, snapshots, trans)
	require.NoError(t, err)
	defer r.Shutdown()
	t.Logf("after restart: commitIndex=%d, lastApplied=%d", r.getCommitIndex(), r.getLastApplied())
	assert.GreaterOrEqual(t, r.getCommitIndex(), r.getLastApplied(),
		"a snapshot index is committed, so CommitIndex should not be below AppliedIndex")
}

// A committed two-voter configuration must not be replaced by an older
// one-voter snapshot configuration on restart. If it is, the restarted node can
// elect itself without the second, committed voter.
func TestAuditStaleSnapshotConfigElectsWithoutCommittedVoter(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 3
	conf.RestoreCommittedLogs = true

	idA := ServerID("nodeA")
	addrA := ServerAddress("nodeA")
	idB := ServerID("nodeB")
	addrB := ServerAddress("nodeB")
	conf.LocalID = idA

	logs := newAtomicCommitStore()
	stable := NewInmemStore()
	snapshots := NewInmemSnapshotStore()
	_, trans := NewInmemTransport(addrA)
	oldConf := Configuration{Servers: []Server{{Suffrage: Voter, ID: idA, Address: addrA}}}
	newConf := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: idA, Address: addrA},
		{Suffrage: Voter, ID: idB, Address: addrB},
	}}
	require.NoError(t, BootstrapCluster(conf, logs, stable, snapshots, trans, oldConf))

	// Snapshot only contains the pre-add configuration.
	sink, err := snapshots.Create(SnapshotVersionMax, 1, 1, oldConf, 1, trans)
	require.NoError(t, err)
	_, err = sink.Write([]byte("snapshot"))
	require.NoError(t, err)
	require.NoError(t, sink.Close())

	// The log and commit index contain the committed two-voter configuration.
	require.NoError(t, logs.StageCommitIndex(2))
	require.NoError(t, logs.StoreLog(&Log{
		Index: 2, Term: 1, Type: LogConfiguration, Data: EncodeConfiguration(newConf),
	}))

	r, err := NewRaft(conf, auditNoopFSM{}, logs, stable, snapshots, trans)
	require.NoError(t, err)
	defer r.Shutdown()

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) && r.getState() != Leader {
		time.Sleep(10 * time.Millisecond)
	}
	got := r.GetConfiguration().Configuration()
	t.Logf("state=%v config=%+v commitIndex=%d lastApplied=%d",
		r.getState(), got, r.getCommitIndex(), r.getLastApplied())
	assert.NotEqual(t, Leader, r.getState(),
		"a node with committed config {nodeA,nodeB} must not elect with only the stale {nodeA} view")
}

// Stronger consequence: with a stale {A} view and a current {A,B,C} view,
// A can elect alone while B and C elect in a separate partition, allowing both
// sides to commit different entries at the same index.
func TestAuditStaleConfigAllowsConflictingCommits(t *testing.T) {
	confA := inmemConfig(t)
	confA.ProtocolVersion = 3
	confA.RestoreCommittedLogs = true
	confB := inmemConfig(t)
	confB.ProtocolVersion = 3
	confB.RestoreCommittedLogs = false
	confC := inmemConfig(t)
	confC.ProtocolVersion = 3
	confC.RestoreCommittedLogs = false

	idA, idB, idC := ServerID("csA"), ServerID("csB"), ServerID("csC")
	addrA, addrB, addrC := ServerAddress("csA"), ServerAddress("csB"), ServerAddress("csC")
	confA.LocalID, confB.LocalID, confC.LocalID = idA, idB, idC

	oldConf := Configuration{Servers: []Server{{Suffrage: Voter, ID: idA, Address: addrA}}}
	newConf := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: idA, Address: addrA},
		{Suffrage: Voter, ID: idB, Address: addrB},
		{Suffrage: Voter, ID: idC, Address: addrC},
	}}
	makeLogs := func(conf *Config) (LogStore, StableStore, SnapshotStore, *InmemTransport) {
		logs := newAtomicCommitStore()
		stable := NewInmemStore()
		snaps := NewInmemSnapshotStore()
		_, trans := NewInmemTransport(ServerAddress(conf.LocalID))
		require.NoError(t, BootstrapCluster(conf, logs, stable, snaps, trans, oldConf))
		require.NoError(t, logs.StageCommitIndex(2))
		require.NoError(t, logs.StoreLog(&Log{
			Index: 2, Term: 1, Type: LogConfiguration, Data: EncodeConfiguration(newConf),
		}))
		return logs, stable, snaps, trans
	}

	// A has the stale snapshot view; B and C load the current log config.
	logsA, stableA, snapsA, transA := makeLogs(confA)
	sink, err := snapsA.Create(SnapshotVersionMax, 1, 1, oldConf, 1, transA)
	require.NoError(t, err)
	_, err = sink.Write([]byte("snapshot"))
	require.NoError(t, err)
	require.NoError(t, sink.Close())
	// Persist commit index 2 atomically with the configuration entry.
	alogs := newAtomicCommitStore()
	require.NoError(t, alogs.StoreLogs([]*Log{
		{Index: 1, Term: 1, Type: LogConfiguration, Data: EncodeConfiguration(oldConf)},
		{Index: 2, Term: 1, Type: LogConfiguration, Data: EncodeConfiguration(newConf)},
	}))
	require.NoError(t, alogs.StageCommitIndex(2))
	// Re-store the committed configuration entry so index 2 is the persisted
	// commit index and the last log entry.
	require.NoError(t, alogs.StoreLog(&Log{
		Index: 2, Term: 1, Type: LogConfiguration, Data: EncodeConfiguration(newConf),
	}))
	_ = logsA

	logsB, stableB, snapsB, transB := makeLogs(confB)
	logsC, stableC, snapsC, transC := makeLogs(confC)
	transB.Connect(addrC, transC)
	transC.Connect(addrB, transB)

	rA, err := NewRaft(confA, auditNoopFSM{}, alogs, stableA, snapsA, transA)
	require.NoError(t, err)
	rB, err := NewRaft(confB, auditNoopFSM{}, logsB, stableB, snapsB, transB)
	require.NoError(t, err)
	rC, err := NewRaft(confC, auditNoopFSM{}, logsC, stableC, snapsC, transC)
	require.NoError(t, err)
	defer rA.Shutdown()
	defer rB.Shutdown()
	defer rC.Shutdown()

	waitLeader := func(r *Raft) bool {
		deadline := time.Now().Add(2 * time.Second)
		for time.Now().Before(deadline) {
			if r.getState() == Leader {
				return true
			}
			time.Sleep(10 * time.Millisecond)
		}
		return false
	}
	require.True(t, waitLeader(rA), "stale A should elect alone")
	var leaderBC *Raft
	for _, r := range []*Raft{rB, rC} {
		if waitLeader(r) {
			leaderBC = r
			break
		}
	}
	require.NotNil(t, leaderBC, "B/C should elect with the current 3-voter configuration")

	require.NoError(t, rA.Apply([]byte("from-stale-partition"), 0).Error())
	require.NoError(t, leaderBC.Apply([]byte("from-current-partition"), 0).Error())

	var entryA, entryBC Log
	require.NoError(t, alogs.GetLog(4, &entryA))
	require.NoError(t, leaderBC.logs.GetLog(4, &entryBC))
	t.Logf("A: term=%d data=%q commit=%d; BC: term=%d data=%q commit=%d",
		entryA.Term, entryA.Data, rA.getCommitIndex(),
		entryBC.Term, entryBC.Data, leaderBC.getCommitIndex())
	assert.Equal(t, entryA.Term, entryBC.Term)
	assert.True(t, bytes.Equal(entryA.Data, entryBC.Data),
		"both partitions committed different entries at the same index/term")
}

// End-to-end cluster version of the same safety scenario: A snapshots as a
// single-voter cluster, then learns a committed {A,B,C} configuration. After A
// restarts partitioned, its stale snapshot configuration lets it elect alone
// while B/C elect under the current configuration.
func TestAuditRealClusterStaleConfigConflict(t *testing.T) {
	confA := inmemConfig(t)
	confA.RestoreCommittedLogs = true
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               confA,
		CommitTrackingLogs: true,
	})
	defer c.Close()
	require.NoError(t, waitForLeader(c))
	a := c.Leader()

	for i := 0; i < 5; i++ {
		require.NoError(t, a.Apply([]byte(fmt.Sprintf("pre-%d", i)), 0).Error())
	}
	require.NoError(t, a.Snapshot().Error())

	confB := inmemConfig(t)
	confC := inmemConfig(t)
	cB := MakeClusterNoBootstrap(1, t, confB)
	cC := MakeClusterNoBootstrap(1, t, confC)
	c.Merge(cB)
	c.Merge(cC)
	c.FullyConnect()
	for _, n := range []*cluster{cB, cC} {
		r := n.rafts[0]
		require.NoError(t, a.AddVoter(r.localID, r.localAddr, 0, 0).Error())
	}
	for i := 0; i < 5; i++ {
		require.NoError(t, a.Apply([]byte(fmt.Sprintf("post-%d", i)), 0).Error())
	}

	// Stop A, leaving B/C to form the current-configuration quorum.
	require.NoError(t, a.Shutdown().Error())
	deadline := time.Now().Add(3 * time.Second)
	var bcLeader *Raft
	for time.Now().Before(deadline) && bcLeader == nil {
		for _, r := range c.rafts[1:] {
			if r.getState() == Leader {
				bcLeader = r
				break
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	require.NotNil(t, bcLeader, "B/C should elect under the current configuration")

	// Restart A with its old snapshot and no transport connection to B/C.
	_, transA := NewInmemTransport(a.localAddr)
	cfgA := a.config()
	rA, err := NewRaft(&cfgA, &MockFSM{}, a.logs, a.stable, a.snapshots, transA)
	require.NoError(t, err)
	c.rafts[0] = rA
	c.trans[0] = transA

	deadline = time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) && rA.getState() != Leader {
		time.Sleep(10 * time.Millisecond)
	}
	require.Equal(t, Leader, rA.getState(), "stale A should elect under its snapshot configuration")

	require.NoError(t, rA.Apply([]byte("real-stale"), 0).Error())
	require.NoError(t, bcLeader.Apply([]byte("real-current"), 0).Error())

	lastA, err := a.logs.LastIndex()
	require.NoError(t, err)
	lastBC, err := bcLeader.logs.LastIndex()
	require.NoError(t, err)
	idx := min(lastA, lastBC)
	var entryA, entryBC Log
	require.NoError(t, a.logs.GetLog(idx, &entryA))
	require.NoError(t, bcLeader.logs.GetLog(idx, &entryBC))
	t.Logf("index=%d A(term=%d,data=%q,commit=%d) BC(term=%d,data=%q,commit=%d)",
		idx, entryA.Term, entryA.Data, rA.getCommitIndex(),
		entryBC.Term, entryBC.Data, bcLeader.getCommitIndex())
	assert.True(t, bytes.Equal(entryA.Data, entryBC.Data) && entryA.Term == entryBC.Term,
		"committed log prefixes diverged after the stale restart")
}

// End-to-end version of the startup deadlock: a real one-node cluster commits
// more than 128*MaxAppendEntries entries without a snapshot, then NewRaft is
// unable to complete on restart because restore replay fills fsmMutateCh before
// runFSM starts.
func TestAuditRealClusterLargeLogRestartHangs(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.SnapshotThreshold = 1 << 30
	conf.SnapshotInterval = time.Hour
	conf.TrailingLogs = 1 << 20
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})
	defer c.Close()

	leader := c.Leader()
	const commands = 9000
	var last Future
	for i := 0; i < commands; i++ {
		last = leader.Apply([]byte(fmt.Sprintf("bulk-%d", i)), 0)
	}
	require.NoError(t, last.Error())
	require.NoError(t, leader.Shutdown().Error())

	_, trans := NewInmemTransport(leader.localAddr)
	cfg := leader.config()
	done := make(chan error, 1)
	go func() {
		r, err := NewRaft(&cfg, &MockFSM{}, leader.logs, leader.stable, leader.snapshots, trans)
		if r != nil {
			_ = r.Shutdown()
		}
		done <- err
	}()
	select {
	case err := <-done:
		require.NoError(t, err)
		t.Fatal("NewRaft unexpectedly completed instead of blocking on restore replay")
	case <-time.After(3 * time.Second):
		t.Log("NewRaft blocked during restart of a real cluster with 9000 committed entries")
	}
}

// Same defect end to end: a single-node cluster with no snapshot, restarted
// with RestoreCommittedLogs, loses its configuration and never campaigns
// again, even though its log and persisted commit index are intact.
func TestAuditRestoreCommittedLogsSingleNodeRestart(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})
	defer c.Close()

	leader := c.Leader()
	for i := 0; i < 5; i++ {
		f := leader.Apply([]byte(fmt.Sprintf("cmd-%d", i)), 0)
		require.NoError(t, f.Error())
	}

	beforeF := leader.GetConfiguration()
	require.NoError(t, beforeF.Error())
	before := beforeF.Configuration()
	require.Len(t, before.Servers, 1)

	require.NoError(t, leader.Shutdown().Error())

	_, trans := NewInmemTransport(leader.localAddr)
	cfg := leader.config()
	r, err := NewRaft(&cfg, &MockFSM{}, leader.logs, leader.stable, leader.snapshots, trans)
	require.NoError(t, err)
	c.rafts[0] = r

	after := r.GetConfiguration().Configuration()
	t.Logf("config before restart: %+v; after restart: %+v (lastApplied=%d, commitIndex=%d)",
		before, after, r.getLastApplied(), r.getCommitIndex())
	assert.Len(t, after.Servers, 1, "membership must survive restart")

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) && r.getState() != Leader {
		time.Sleep(10 * time.Millisecond)
	}
	assert.Equal(t, Leader, r.getState(),
		"restarted single-node cluster must be able to elect its only voter")
}

// Restarting every voter with RestoreCommittedLogs enabled and no snapshot
// leaves every node without a configuration, so no node campaigns.
func TestAuditRestoreCommittedLogsAllVotersRestart(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})
	defer c.Close()

	leader := c.Leader()
	for i := 0; i < 5; i++ {
		require.NoError(t, leader.Apply([]byte(fmt.Sprintf("cmd-%d", i)), 0).Error())
	}

	type nodeState struct {
		addr   ServerAddress
		logs   LogStore
		stable StableStore
		snaps  SnapshotStore
		cfg    Config
	}
	states := make([]nodeState, len(c.rafts))
	for i, r := range c.rafts {
		states[i] = nodeState{
			addr:   r.localAddr,
			logs:   r.logs,
			stable: r.stable,
			snaps:  r.snapshots,
			cfg:    r.config(),
		}
		require.NoError(t, r.Shutdown().Error())
	}

	trans := make([]*InmemTransport, len(states))
	for i := range states {
		_, trans[i] = NewInmemTransport(states[i].addr)
	}
	for i := range trans {
		for j := range trans {
			if i != j {
				trans[i].Connect(states[j].addr, trans[j])
			}
		}
	}

	for i := range states {
		s := states[i]
		r, err := NewRaft(&s.cfg, &MockFSM{}, s.logs, s.stable, s.snaps, trans[i])
		require.NoError(t, err)
		c.rafts[i] = r
		c.trans[i] = trans[i]
	}

	time.Sleep(1500 * time.Millisecond)
	nLeaders := 0
	for _, r := range c.rafts {
		if r.getState() == Leader {
			nLeaders++
		}
	}
	for i, r := range c.rafts {
		t.Logf("node %d: state=%v config=%+v", i, r.getState(), r.GetConfiguration().Configuration())
	}
	assert.Equal(t, 1, nLeaders, "a restarted 3-voter cluster must elect a leader")
}

// The restore path applies committed entries by sending batches to
// r.fsmMutateCh from NewRaft, but runFSM (the only consumer) is started only
// after NewRaft returns. The channel has capacity 128, so restoring more than
// 128*MaxAppendEntries committed entries blocks forever.
func TestAuditRestoreCommittedLogsLargeLogStartup(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 3
	conf.RestoreCommittedLogs = true
	conf.MaxAppendEntries = 64
	conf.TrailingLogs = 10240

	id := ServerID("node1")
	addr := ServerAddress("node1")
	conf.LocalID = id

	logs := newAtomicCommitStore()
	stable := NewInmemStore()
	snapshots := NewInmemSnapshotStore()
	_, trans := NewInmemTransport(addr)

	cfg := Configuration{Servers: []Server{{Suffrage: Voter, ID: id, Address: addr}}}
	require.NoError(t, BootstrapCluster(conf, logs, stable, snapshots, trans, cfg))

	const committed = 9000
	batch := make([]*Log, 0, committed)
	for i := uint64(2); i <= committed; i++ {
		batch = append(batch, &Log{Index: i, Term: 1, Type: LogCommand, Data: []byte("x")})
	}
	require.NoError(t, logs.StoreLogs(batch))
	require.NoError(t, logs.StageCommitIndex(committed+1))
	require.NoError(t, logs.StoreLog(&Log{Index: committed + 1, Term: 1, Type: LogCommand, Data: []byte("x")}))

	done := make(chan error, 1)
	go func() {
		r, err := NewRaft(conf, &MockFSM{}, logs, stable, snapshots, trans)
		if r != nil {
			_ = r.Shutdown()
		}
		done <- err
	}()

	select {
	case err := <-done:
		require.NoError(t, err)
		t.Log("NewRaft completed (no deadlock)")
	case <-time.After(3 * time.Second):
		buf := make([]byte, 1<<20)
		n := runtime.Stack(buf, true)
		t.Logf("goroutine stacks:\n%s", buf[:n])
		t.Fatalf("NewRaft did not return within 3s while restoring %d committed entries "+
			"(fsmMutateCh capacity=%d, MaxAppendEntries=%d)",
			committed+1, cap(make(chan interface{}, 128)), conf.MaxAppendEntries)
	}
}

// Control for the deadlock test: 8000 committed entries fit in the 128-slot
// fsmMutateCh at MaxAppendEntries=64 (125 batches), so NewRaft completes.
func TestAuditRestoreCommittedLogsBelowChannelCapacity(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 3
	conf.RestoreCommittedLogs = true
	conf.MaxAppendEntries = 64
	conf.TrailingLogs = 10240

	id := ServerID("node1")
	addr := ServerAddress("node1")
	conf.LocalID = id

	logs := newAtomicCommitStore()
	stable := NewInmemStore()
	snapshots := NewInmemSnapshotStore()
	_, trans := NewInmemTransport(addr)
	cfg := Configuration{Servers: []Server{{Suffrage: Voter, ID: id, Address: addr}}}
	require.NoError(t, BootstrapCluster(conf, logs, stable, snapshots, trans, cfg))

	const committed = 8000
	batch := make([]*Log, 0, committed)
	for i := uint64(2); i <= committed; i++ {
		batch = append(batch, &Log{Index: i, Term: 1, Type: LogCommand, Data: []byte("x")})
	}
	require.NoError(t, logs.StoreLogs(batch))
	require.NoError(t, logs.StageCommitIndex(committed+1))
	require.NoError(t, logs.StoreLog(&Log{Index: committed + 1, Term: 1, Type: LogCommand, Data: []byte("x")}))

	done := make(chan error, 1)
	go func() {
		r, err := NewRaft(conf, &MockFSM{}, logs, stable, snapshots, trans)
		if r != nil {
			_ = r.Shutdown()
		}
		done <- err
	}()

	select {
	case err := <-done:
		require.NoError(t, err)
	case <-time.After(5 * time.Second):
		t.Fatalf("NewRaft did not return within 5s for %d committed entries", committed+1)
	}
}
