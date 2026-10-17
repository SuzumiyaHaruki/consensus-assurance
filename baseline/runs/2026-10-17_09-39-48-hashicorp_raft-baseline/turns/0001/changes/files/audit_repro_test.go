package raft

import (
	"fmt"
	"io"
	"testing"
	"time"
)

type auditRestoreFSM struct{}

func (*auditRestoreFSM) Apply(*Log) interface{} { return nil }

func (*auditRestoreFSM) Snapshot() (FSMSnapshot, error) {
	return nil, fmt.Errorf("not used")
}

func (*auditRestoreFSM) Restore(r io.ReadCloser) error {
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
// fsmMutateCh buffer can hold.
func TestAuditRestoreCommittedLogsDoesNotDeadlockBeforeRunFSM(t *testing.T) {
	const entries = 131 // More than fsmMutateCh's fixed 128-entry capacity.

	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true
	conf.MaxAppendEntries = 1
	conf.SnapshotThreshold = 1 << 20

	logs := NewInmemCommitTrackingStore()
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

	logs := NewInmemCommitTrackingStore()
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
