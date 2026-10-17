package raft

import (
	"errors"
	"fmt"
	"io"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// auditAtomicTrackingStore follows CommitTrackingLogStore's contract: a staged
// index becomes visible only if the following StoreLog/StoreLogs call succeeds.
type auditAtomicTrackingStore struct {
	*InmemStore
	mu        sync.Mutex
	staged    uint64
	hasStaged bool
	persisted atomic.Uint64
}

type failingCommitReadStore struct {
	*auditAtomicTrackingStore
	err error
}

func (s *failingCommitReadStore) GetCommitIndex() (uint64, error) {
	return 0, s.err
}

func newAuditAtomicTrackingStore() *auditAtomicTrackingStore {
	return &auditAtomicTrackingStore{InmemStore: NewInmemStore()}
}

func (s *auditAtomicTrackingStore) StageCommitIndex(index uint64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.staged = index
	s.hasStaged = true
	return nil
}

func (s *auditAtomicTrackingStore) StoreLog(entry *Log) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.InmemStore.StoreLog(entry); err != nil {
		return err
	}
	s.persistStaged()
	return nil
}

func (s *auditAtomicTrackingStore) StoreLogs(entries []*Log) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.InmemStore.StoreLogs(entries); err != nil {
		return err
	}
	s.persistStaged()
	return nil
}

func (s *auditAtomicTrackingStore) GetCommitIndex() (uint64, error) {
	return s.persisted.Load(), nil
}

func (s *auditAtomicTrackingStore) persistStaged() {
	if s.hasStaged {
		s.persisted.Store(s.staged)
		s.hasStaged = false
	}
}

type auditRestoreFSM struct{}

func (*auditRestoreFSM) Apply(*Log) interface{} { return nil }

func (*auditRestoreFSM) Snapshot() (FSMSnapshot, error) {
	return nil, fmt.Errorf("not used")
}

func (*auditRestoreFSM) Restore(r io.ReadCloser) error {
	_, err := io.Copy(io.Discard, r)
	return err
}

type blockingAuditFSM struct {
	started chan struct{}
	release chan struct{}
	applied atomic.Int64
}

func (f *blockingAuditFSM) Apply(*Log) interface{} {
	select {
	case f.started <- struct{}{}:
	default:
	}
	<-f.release
	return f.applied.Add(1)
}

func (*blockingAuditFSM) Snapshot() (FSMSnapshot, error) {
	return nil, fmt.Errorf("not used")
}

func (*blockingAuditFSM) Restore(r io.ReadCloser) error {
	_, err := io.Copy(io.Discard, r)
	return err
}

type countingAuditFSM struct {
	applied atomic.Int64
}

func (f *countingAuditFSM) Apply(*Log) interface{} {
	return f.applied.Add(1)
}

func (*countingAuditFSM) Snapshot() (FSMSnapshot, error) {
	return nil, fmt.Errorf("not used")
}

func (*countingAuditFSM) Restore(r io.ReadCloser) error {
	_, err := io.Copy(io.Discard, r)
	return err
}

// RestoreCommittedLogs must not discard the persisted configuration while
// replaying the committed suffix. A normal restart scans configuration entries
// before serving, and enabling committed-log recovery must preserve that
// behavior.
func TestAuditRestoreCommittedLogsRestoresConfiguration(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 100 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})
	defer c.Close()

	leader := c.Leader()
	if err := leader.Apply([]byte("one"), time.Second).Error(); err != nil {
		t.Fatalf("apply: %v", err)
	}
	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}

	_, trans := NewInmemTransport(leader.localAddr)
	cfg := leader.config()
	restarted, err := NewRaft(&cfg, leader.fsm, leader.logs, leader.stable, leader.snapshots, trans)
	if err != nil {
		t.Fatalf("restart: %v", err)
	}
	c.rafts[0] = restarted

	configurationFuture := restarted.GetConfiguration()
	if err := configurationFuture.Error(); err != nil {
		t.Fatalf("get configuration after recovery: %v", err)
	}
	got := configurationFuture.Configuration().Servers
	if len(got) != 1 || got[0].ID != leader.localID {
		t.Fatalf("configuration after recovery = %+v, want local server %q", got, leader.localID)
	}
}

// processLogs batches entries according to MaxAppendEntries. It runs during
// NewRaft before runFSM starts, so it must not enqueue more batches than the
// fsmMutateCh buffer can hold. Default MaxAppendEntries is 64, so 8,193
// FSM-producing entries require 129 batches.
func TestAuditRestoreCommittedLogsDoesNotDeadlockBeforeRunFSM(t *testing.T) {
	const entries = 8194 // 8,193 committed entries require 129 batches at max64.

	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.SnapshotThreshold = 1 << 20

	logs := newAuditAtomicTrackingStore()
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("")
	conf.LocalID = ServerID(fmt.Sprintf("server-%s", addr))

	configuration := Configuration{
		Servers: []Server{{
			Suffrage: Voter,
			ID:       conf.LocalID,
			Address:  addr,
		}},
	}
	if err := BootstrapCluster(conf, logs, stable, snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	for index := uint64(2); index <= entries; index++ {
		// Stage the preceding prefix with the final log-store call, matching
		// CommitTrackingLogStore's contract that staging will be persisted
		// atomically with a following StoreLogs call.
		if index == entries {
			if err := logs.StageCommitIndex(entries - 1); err != nil {
				t.Fatalf("stage commit index: %v", err)
			}
		}
		if err := logs.StoreLog(&Log{
			Index: index,
			Term:  1,
			Type:  LogCommand,
			Data:  []byte("entry"),
		}); err != nil {
			t.Fatalf("store log %d: %v", index, err)
		}
	}

	done := make(chan struct{})
	go func() {
		r, err := NewRaft(conf, &MockFSM{}, logs, stable, snaps, trans)
		if err == nil {
			_ = r.Shutdown().Error()
		}
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatalf("NewRaft deadlocked while restoring %d committed entries", entries-1)
	}
}

// A snapshot may be newer than the last persisted commit index because taking a
// snapshot does not append a log entry. Recovery must not roll the in-memory
// commit index behind the already restored snapshot state.
func TestAuditRestoreCommittedLogsDoesNotRegressCommitBehindSnapshot(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 100 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              1,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})
	defer c.Close()

	leader := c.Leader()
	if err := leader.Apply([]byte("one"), time.Second).Error(); err != nil {
		t.Fatalf("apply: %v", err)
	}
	if err := leader.Snapshot().Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	if err := leader.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}

	_, trans := NewInmemTransport(leader.localAddr)
	cfg := leader.config()
	restarted, err := NewRaft(&cfg, leader.fsm, leader.logs, leader.stable, leader.snapshots, trans)
	if err != nil {
		t.Fatalf("restart: %v", err)
	}
	c.rafts[0] = restarted

	applied := restarted.AppliedIndex()
	committed := restarted.CommitIndex()
	if committed < applied {
		t.Fatalf("commit index regressed behind restored state: commit=%d applied=%d", committed, applied)
	}
}

// A configuration change committed after a snapshot must not be hidden by the
// configuration stored in that older snapshot.
func TestAuditRestoreCommittedLogsAppliesConfigurationAfterSnapshot(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true

	logs := newAuditAtomicTrackingStore()
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("")
	conf.LocalID = ServerID(fmt.Sprintf("server-%s", addr))

	oldConfig := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       conf.LocalID,
		Address:  addr,
	}}}
	newConfig := Configuration{Servers: append(
		append([]Server(nil), oldConfig.Servers...),
		Server{Suffrage: Voter, ID: "new-server", Address: "new-address"},
	)}

	if err := BootstrapCluster(conf, logs, stable, snaps, trans, oldConfig); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	sink, err := snaps.Create(SnapshotVersionMax, 1, 1, oldConfig, 1, trans)
	if err != nil {
		t.Fatalf("create snapshot: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Fatalf("close snapshot: %v", err)
	}

	if err := logs.StageCommitIndex(1); err != nil {
		t.Fatalf("stage commit 1: %v", err)
	}
	if err := logs.StoreLog(&Log{
		Index: 2,
		Term:  1,
		Type:  LogConfiguration,
		Data:  EncodeConfiguration(newConfig),
	}); err != nil {
		t.Fatalf("store configuration: %v", err)
	}
	if err := logs.StageCommitIndex(2); err != nil {
		t.Fatalf("stage commit 2: %v", err)
	}
	if err := logs.StoreLog(&Log{Index: 3, Term: 1, Type: LogNoop}); err != nil {
		t.Fatalf("store noop: %v", err)
	}

	r, err := NewRaft(conf, &auditRestoreFSM{}, logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("restart: %v", err)
	}
	defer r.Shutdown()

	future := r.GetConfiguration()
	if err := future.Error(); err != nil {
		t.Fatalf("get configuration: %v", err)
	}
	got := future.Configuration()
	if len(got.Servers) != len(newConfig.Servers) {
		t.Fatalf("configuration after recovery = %+v, want %+v", got, newConfig)
	}
}

// Restarting every member together is a normal recovery operation. Each member
// must recover the same committed voter set before participating in elections.
func TestAuditRestartAllNodesRecoversMembership(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 100 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})
	defer c.Close()

	leader := c.Leader()
	if err := leader.Apply([]byte("one"), time.Second).Error(); err != nil {
		t.Fatalf("apply: %v", err)
	}
	c.WaitForReplication(1)

	oldRafts := append([]*Raft(nil), c.rafts...)
	futures := make([]Future, len(oldRafts))
	for i, r := range oldRafts {
		futures[i] = r.Shutdown()
	}
	for i, future := range futures {
		if err := future.Error(); err != nil {
			t.Fatalf("shutdown node %d: %v", i, err)
		}
	}

	transports := make([]*InmemTransport, len(oldRafts))
	restarted := make([]*Raft, len(oldRafts))
	for i, old := range oldRafts {
		_, transports[i] = NewInmemTransport(old.localAddr)
		cfg := old.config()
		var err error
		restarted[i], err = NewRaft(&cfg, old.fsm, old.logs, old.stable, old.snapshots, transports[i])
		if err != nil {
			t.Fatalf("restart node %d: %v", i, err)
		}
	}
	for i, transport := range transports {
		for j, peer := range transports {
			if i != j {
				transport.Connect(peer.LocalAddr(), peer)
			}
		}
	}
	c.rafts = restarted

	var missingMembership []int
	for i, r := range restarted {
		future := r.GetConfiguration()
		if err := future.Error(); err != nil {
			t.Fatalf("get configuration for node %d: %v", i, err)
		}
		if got := len(future.Configuration().Servers); got != len(oldRafts) {
			missingMembership = append(missingMembership, got)
		}
	}

	// A correctly recovered three-voter cluster should elect within a few
	// randomized heartbeat intervals.
	deadline := time.Now().Add(3 * conf.HeartbeatTimeout)
	for time.Now().Before(deadline) {
		for _, r := range restarted {
			if r.State() == Leader {
				if len(missingMembership) > 0 {
					t.Fatalf("nodes recovered server counts %v, want 3 each", missingMembership)
				}
				return
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("restarted three-voter cluster has no leader; recovered server counts: %v", missingMembership)
}

// Commit indexes are monotonic. A follower that has durably recorded commit 3
// must not overwrite it with a newly restarted leader's earlier value 0.
func TestAuditAppendEntriesDoesNotRegressPersistedCommitIndex(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.skipStartup = true

	logs := newAuditAtomicTrackingStore()
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("")
	conf.LocalID = ServerID(fmt.Sprintf("server-%s", addr))

	configuration := Configuration{Servers: []Server{
		{
			Suffrage: Voter,
			ID:       conf.LocalID,
			Address:  addr,
		},
		{
			Suffrage: Voter,
			ID:       "new-leader",
			Address:  "new-address",
		},
	}}
	if err := BootstrapCluster(conf, logs, stable, snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	sink, err := snaps.Create(SnapshotVersionMax, 1, 1, configuration, 1, trans)
	if err != nil {
		t.Fatalf("create snapshot: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Fatalf("close snapshot: %v", err)
	}

	for index := uint64(2); index <= 5; index++ {
		if index == 4 {
			if err := logs.StageCommitIndex(3); err != nil {
				t.Fatalf("stage commit: %v", err)
			}
		}
		if err := logs.StoreLog(&Log{
			Index: index,
			Term:  1,
			Type:  LogCommand,
			Data:  []byte("entry"),
		}); err != nil {
			t.Fatalf("store log %d: %v", index, err)
		}
	}

	r, err := NewRaft(conf, &auditRestoreFSM{}, logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("restart: %v", err)
	}
	defer r.Shutdown()

	before, err := logs.GetCommitIndex()
	if err != nil {
		t.Fatalf("get commit before append: %v", err)
	}
	if before != 3 {
		t.Fatalf("commit before append = %d, want 3", before)
	}

	req := &AppendEntriesRequest{
		RPCHeader: RPCHeader{
			ProtocolVersion: ProtocolVersionMax,
			ID:              []byte("new-leader"),
			Addr:            trans.EncodePeer("new-leader", "new-address"),
		},
		Term:              2,
		PrevLogEntry:      5,
		PrevLogTerm:       1,
		Entries:           []*Log{{Index: 6, Term: 2, Type: LogNoop}},
		LeaderCommitIndex: 0,
	}
	respCh := make(chan RPCResponse, 1)
	r.appendEntries(RPC{Command: req, RespChan: respCh}, req)
	if response := <-respCh; response.Error != nil {
		t.Fatalf("append entries: %v", response.Error)
	}

	after, err := logs.GetCommitIndex()
	if err != nil {
		t.Fatalf("get commit after append: %v", err)
	}
	if after < before {
		t.Fatalf("persisted commit regressed from %d to %d", before, after)
	}
}

// Config.RestoreCommittedLogs says committed logs are replayed before NewRaft
// completes. Replay must therefore not merely be queued to an asynchronous FSM.
func TestAuditNewRaftWaitsForCommittedReplay(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true

	logs := newAuditAtomicTrackingStore()
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("")
	conf.LocalID = ServerID(fmt.Sprintf("server-%s", addr))

	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       conf.LocalID,
		Address:  addr,
	}}}
	if err := BootstrapCluster(conf, logs, stable, snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	sink, err := snaps.Create(SnapshotVersionMax, 1, 1, configuration, 1, trans)
	if err != nil {
		t.Fatalf("create snapshot: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Fatalf("close snapshot: %v", err)
	}

	for index := uint64(2); index <= 5; index++ {
		if index == 4 {
			if err := logs.StageCommitIndex(3); err != nil {
				t.Fatalf("stage commit: %v", err)
			}
		}
		if err := logs.StoreLog(&Log{
			Index: index,
			Term:  1,
			Type:  LogCommand,
			Data:  []byte("entry"),
		}); err != nil {
			t.Fatalf("store log %d: %v", index, err)
		}
	}

	fsm := &blockingAuditFSM{
		started: make(chan struct{}, 1),
		release: make(chan struct{}),
	}
	r, err := NewRaft(conf, fsm, logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("restart: %v", err)
	}

	// NewRaft has returned. A completed replay must include commands at 2 and 3.
	if got := fsm.applied.Load(); got != 2 {
		close(fsm.release)
		_ = r.Shutdown().Error()
		t.Fatalf("NewRaft returned after applying %d committed commands, want 2", got)
	}
	close(fsm.release)
	_ = r.Shutdown().Error()
}

// If AppendEntries regresses the durable commit index, a crash and restart must
// not skip committed commands when rebuilding the FSM.
func TestAuditRegressedCommitIndexSkipsCommittedReplay(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.skipStartup = true
	conf.HeartbeatTimeout = 10 * time.Second
	conf.ElectionTimeout = 10 * time.Second
	conf.LeaderLeaseTimeout = 5 * time.Second

	logs := newAuditAtomicTrackingStore()
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("")
	conf.LocalID = ServerID(fmt.Sprintf("server-%s", addr))

	configuration := Configuration{Servers: []Server{
		{
			Suffrage: Voter,
			ID:       conf.LocalID,
			Address:  addr,
		},
		{
			Suffrage: Voter,
			ID:       "new-leader",
			Address:  "new-address",
		},
	}}
	if err := BootstrapCluster(conf, logs, stable, snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	sink, err := snaps.Create(SnapshotVersionMax, 1, 1, configuration, 1, trans)
	if err != nil {
		t.Fatalf("create snapshot: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Fatalf("close snapshot: %v", err)
	}

	for index := uint64(2); index <= 5; index++ {
		if index == 4 {
			if err := logs.StageCommitIndex(3); err != nil {
				t.Fatalf("stage commit: %v", err)
			}
		}
		if err := logs.StoreLog(&Log{
			Index: index,
			Term:  1,
			Type:  LogCommand,
			Data:  []byte("entry"),
		}); err != nil {
			t.Fatalf("store log %d: %v", index, err)
		}
	}

	first, err := NewRaft(conf, &auditRestoreFSM{}, logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("first start: %v", err)
	}
	req := &AppendEntriesRequest{
		RPCHeader: RPCHeader{
			ProtocolVersion: ProtocolVersionMax,
			ID:              []byte("new-leader"),
			Addr:            trans.EncodePeer("new-leader", "new-address"),
		},
		Term:              2,
		PrevLogEntry:      5,
		PrevLogTerm:       1,
		Entries:           []*Log{{Index: 6, Term: 2, Type: LogNoop}},
		LeaderCommitIndex: 0,
	}
	respCh := make(chan RPCResponse, 1)
	first.appendEntries(RPC{Command: req, RespChan: respCh}, req)
	if response := <-respCh; response.Error != nil {
		t.Fatalf("append entries: %v", response.Error)
	}
	if err := first.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}

	_, trans2 := NewInmemTransport(addr)
	restartConf := *conf
	restartConf.skipStartup = false
	fsm := &countingAuditFSM{}
	restarted, err := NewRaft(&restartConf, fsm, logs, stable, snaps, trans2)
	if err != nil {
		t.Fatalf("restart after crash: %v", err)
	}
	defer restarted.Shutdown()

	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) && fsm.applied.Load() < 2 {
		time.Sleep(time.Millisecond)
	}
	if got := fsm.applied.Load(); got != 2 {
		t.Fatalf("recovered FSM applied %d committed commands, want 2", got)
	}
}

// CommitTrackingLogStore.GetCommitIndex MUST never return an index above the
// last log entry, even when a higher value has merely been staged.
func TestAuditInmemCommitTrackingStoreBoundsStagedIndex(t *testing.T) {
	logs := NewInmemCommitTrackingStore()
	if err := logs.StoreLog(&Log{Index: 1, Term: 1, Type: LogNoop}); err != nil {
		t.Fatalf("store log: %v", err)
	}
	if err := logs.StageCommitIndex(2); err != nil {
		t.Fatalf("stage commit: %v", err)
	}

	commitIndex, err := logs.GetCommitIndex()
	if err != nil {
		t.Fatalf("get commit: %v", err)
	}
	lastIndex, err := logs.LastIndex()
	if err != nil {
		t.Fatalf("get last index: %v", err)
	}
	if commitIndex > lastIndex {
		t.Fatalf("GetCommitIndex returned staged index %d above last log index %d", commitIndex, lastIndex)
	}
}

func TestAuditProtocol2To3VoterCatchesUp(t *testing.T) {
	oldConf := inmemConfig(t)
	oldConf.ProtocolVersion = 2
	oldConf.HeartbeatTimeout = 50 * time.Millisecond
	oldConf.ElectionTimeout = 50 * time.Millisecond
	oldConf.LeaderLeaseTimeout = 50 * time.Millisecond
	c := MakeCluster(2, t, oldConf)
	defer c.Close()

	newConf := inmemConfig(t)
	newConf.ProtocolVersion = 3
	newConf.HeartbeatTimeout = 50 * time.Millisecond
	newConf.ElectionTimeout = 50 * time.Millisecond
	newConf.LeaderLeaseTimeout = 50 * time.Millisecond
	c1 := MakeClusterNoBootstrap(1, t, newConf)

	c.Merge(c1)
	c.FullyConnect()
	added := c1.rafts[0]

	future := c.Leader().AddVoter(added.localID, added.localAddr, 0, time.Second)
	if err := future.Error(); err != nil {
		t.Fatalf("add voter: %v", err)
	}
	c.EnsureSame(t)

	deadline := time.Now().Add(2 * time.Second)
	var states []string
	for time.Now().Before(deadline) {
		states = states[:0]
		converged := true
		for i, node := range c.rafts {
			last, err := node.logs.LastIndex()
			if err != nil {
				t.Fatalf("last index for node %d: %v", i, err)
			}
			servers := node.GetConfiguration().Configuration().Servers
			states = append(states, fmt.Sprintf("node%d:last=%d,servers=%d", i, last, len(servers)))
			if len(servers) != 3 {
				converged = false
			}
		}
		if converged {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("new protocol-3 voter did not catch up: %v", states)
}

// EnsureSamePeers must re-read the expected configuration while waiting. The
// first node can legitimately be one configuration behind when polling starts.
func TestAuditEnsureSamePeersRefreshesBaseline(t *testing.T) {
	one := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       "one",
		Address:  "one",
	}}}
	two := Configuration{Servers: append(
		append([]Server(nil), one.Servers...),
		Server{Suffrage: Voter, ID: "two", Address: "two"},
	)}

	first := &Raft{}
	second := &Raft{}
	first.setLatestConfiguration(one, 1)
	second.setLatestConfiguration(two, 2)

	c := &cluster{
		rafts:           []*Raft{first, second},
		conf:            &Config{CommitTimeout: 5 * time.Millisecond},
		longstopTimeout: 100 * time.Millisecond,
		observationCh:   make(chan Observation, 1),
		failedCh:        make(chan struct{}),
	}
	go func() {
		// Let EnsureSamePeers capture the initial one-peer value, then make the
		// entire cluster converge to the new two-peer configuration.
		time.Sleep(10 * time.Millisecond)
		first.setLatestConfiguration(two, 2)
		second.setLatestConfiguration(two, 2)
	}()

	c.EnsureSamePeers(t)
}

// A committed voter removal after a snapshot must survive restart. Recovering
// the old snapshot configuration and skipping the committed configuration entry
// would incorrectly resurrect the removed voter.
func TestAuditRestartDoesNotResurrectRemovedVoter(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 100 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:              3,
		Bootstrap:          true,
		Conf:               conf,
		CommitTrackingLogs: true,
	})
	defer c.Close()

	leader := c.Leader()
	if err := leader.Apply([]byte("before-snapshot"), time.Second).Error(); err != nil {
		t.Fatalf("apply before snapshot: %v", err)
	}
	c.WaitForReplication(1)
	for i, node := range c.rafts {
		if err := node.Snapshot().Error(); err != nil {
			t.Fatalf("snapshot node %d: %v", i, err)
		}
	}

	var removed, kept *Raft
	for _, node := range c.rafts {
		if node != leader {
			if removed == nil {
				removed = node
			} else {
				kept = node
			}
		}
	}
	if removed == nil || kept == nil {
		t.Fatal("could not identify followers")
	}
	if err := leader.RemoveServer(removed.localID, 0, time.Second).Error(); err != nil {
		t.Fatalf("remove voter: %v", err)
	}
	if err := leader.Apply([]byte("after-removal"), time.Second).Error(); err != nil {
		t.Fatalf("apply after removal: %v", err)
	}

	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) && kept.AppliedIndex() < leader.AppliedIndex() {
		time.Sleep(time.Millisecond)
	}
	if kept.AppliedIndex() < leader.AppliedIndex() {
		t.Fatalf("kept follower applied %d, leader applied %d", kept.AppliedIndex(), leader.AppliedIndex())
	}

	toRestart := []*Raft{leader, kept}
	futures := make([]Future, len(toRestart))
	for i, node := range toRestart {
		futures[i] = node.Shutdown()
	}
	for i, future := range futures {
		if err := future.Error(); err != nil {
			t.Fatalf("shutdown node %d: %v", i, err)
		}
	}

	for i, old := range toRestart {
		_, trans := NewInmemTransport(old.localAddr)
		cfg := old.config()
		cfg.skipStartup = true
		restarted, err := NewRaft(&cfg, old.fsm, old.logs, old.stable, old.snapshots, trans)
		if err != nil {
			t.Fatalf("restart node %d: %v", i, err)
		}
		defer restarted.Shutdown()

		got := restarted.GetConfiguration().Configuration().Servers
		for _, server := range got {
			if server.ID == removed.localID {
				t.Fatalf("node %d resurrected removed voter %q: %+v", i, removed.localID, got)
			}
		}
		if len(got) != 2 {
			t.Fatalf("node %d recovered %d servers, want 2: %+v", i, len(got), got)
		}
	}
}

// RestoreCommittedLogs is an exported Raft field, but the main goroutine reads
// it without synchronization while appending. This test is meaningful under
// -race: concurrent public-field mutation must not race the commit-staging path.
func TestAuditRestoreCommittedLogsFieldMutationRace(t *testing.T) {
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
	stop := make(chan struct{})
	writerDone := make(chan struct{})
	go func() {
		defer close(writerDone)
		for {
			select {
			case <-stop:
				return
			default:
				leader.RestoreCommittedLogs = !leader.RestoreCommittedLogs
			}
		}
	}()

	for i := 0; i < 100; i++ {
		if err := leader.Apply([]byte("entry"), time.Second).Error(); err != nil {
			close(stop)
			<-writerDone
			t.Fatalf("apply: %v", err)
		}
	}
	close(stop)
	<-writerDone
}

func TestAuditRestoreCommittedLogsPropagatesCommitReadError(t *testing.T) {
	readErr := errors.New("commit index read failed")
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true

	logs := &failingCommitReadStore{
		auditAtomicTrackingStore: newAuditAtomicTrackingStore(),
		err:                      readErr,
	}
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("")
	conf.LocalID = ServerID(fmt.Sprintf("server-%s", addr))

	_, err := NewRaft(conf, &auditRestoreFSM{}, logs, stable, snaps, trans)
	if !errors.Is(err, readErr) {
		t.Fatalf("NewRaft error = %v, want %v", err, readErr)
	}
}

// Package-level GetConfiguration uses NewRaft with skipStartup, so it also has
// no FSM consumer during committed-log recovery.
func TestAuditGetConfigurationDoesNotDeadlockOnCommittedReplay(t *testing.T) {
	const entries = 8194 // 8,193 committed FSM entries require 129 batches.

	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.SnapshotThreshold = 1 << 20

	logs := newAuditAtomicTrackingStore()
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("")
	conf.LocalID = ServerID(fmt.Sprintf("server-%s", addr))
	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       conf.LocalID,
		Address:  addr,
	}}}
	if err := BootstrapCluster(conf, logs, stable, snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	for index := uint64(2); index <= entries; index++ {
		if index == entries {
			if err := logs.StageCommitIndex(entries - 1); err != nil {
				t.Fatalf("stage commit index: %v", err)
			}
		}
		if err := logs.StoreLog(&Log{
			Index: index,
			Term:  1,
			Type:  LogCommand,
			Data:  []byte("entry"),
		}); err != nil {
			t.Fatalf("store log %d: %v", index, err)
		}
	}

	done := make(chan struct{})
	go func() {
		_, _ = GetConfiguration(conf, &MockFSM{}, logs, stable, snaps, trans)
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatalf("GetConfiguration deadlocked while restoring %d committed entries", entries-1)
	}
}

func TestAuditGetConfigurationRecoversCommittedConfiguration(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true

	logs := newAuditAtomicTrackingStore()
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("")
	conf.LocalID = ServerID(fmt.Sprintf("server-%s", addr))
	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       conf.LocalID,
		Address:  addr,
	}}}
	if err := BootstrapCluster(conf, logs, stable, snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}

	// Commit the bootstrap configuration. The following persisted log makes the
	// commitment of index 1 atomic with a write according to the store contract.
	if err := logs.StageCommitIndex(1); err != nil {
		t.Fatalf("stage commit index: %v", err)
	}
	if err := logs.StoreLog(&Log{Index: 2, Term: 1, Type: LogNoop}); err != nil {
		t.Fatalf("store noop: %v", err)
	}

	got, err := GetConfiguration(conf, &auditRestoreFSM{}, logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("GetConfiguration: %v", err)
	}
	if len(got.Servers) != 1 || got.Servers[0].ID != conf.LocalID {
		t.Fatalf("GetConfiguration recovered %+v, want local server %q", got, conf.LocalID)
	}
}

// LogCache is documented as a wrapper around any LogStore and preserves
// optional interfaces such as MonotonicLogStore. It should likewise preserve
// CommitTrackingLogStore when committed-log recovery is enabled.
func TestAuditLogCachePreservesCommitTracking(t *testing.T) {
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.skipStartup = true

	store := newAuditAtomicTrackingStore()
	cached, err := NewLogCache(16, store)
	if err != nil {
		t.Fatalf("new log cache: %v", err)
	}
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("")
	conf.LocalID = ServerID(fmt.Sprintf("server-%s", addr))
	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       conf.LocalID,
		Address:  addr,
	}}}
	if err := BootstrapCluster(conf, store, stable, snaps, trans, configuration); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}

	if _, err := NewRaft(conf, &auditRestoreFSM{}, cached, stable, snaps, trans); err != nil {
		t.Fatalf("NewRaft with cached commit-tracking store: %v", err)
	}
}
