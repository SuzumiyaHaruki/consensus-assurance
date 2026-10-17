package raft

import (
	"errors"
	"fmt"
	"strings"
	"sync/atomic"
	"testing"
)

type secondLastIndexErrorStore struct {
	*auditAtomicTrackingStore
	calls atomic.Int32
	err   error
}

func (s *secondLastIndexErrorStore) LastIndex() (uint64, error) {
	if s.calls.Add(1) == 2 {
		return 0, s.err
	}
	return s.auditAtomicTrackingStore.LastIndex()
}

func TestAuditRestoreCommittedLogsPropagatesLastIndexError(t *testing.T) {
	lastIndexErr := errors.New("second last-index read failed")
	conf := inmemConfig(t)
	conf.RestoreCommittedLogs = true

	logs := &secondLastIndexErrorStore{
		auditAtomicTrackingStore: newAuditAtomicTrackingStore(),
		err:                      lastIndexErr,
	}
	stable := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("")
	conf.LocalID = ServerID(fmt.Sprintf("server-%s", addr))

	_, err := NewRaft(conf, &auditRestoreFSM{}, logs, stable, snaps, trans)
	if err == nil || !strings.Contains(err.Error(), lastIndexErr.Error()) {
		t.Fatalf("NewRaft error = %v, want wrapped %v", err, lastIndexErr)
	}
	if got := logs.calls.Load(); got < 2 {
		t.Fatalf("LastIndex calls = %d, want recovery-path call", got)
	}
}
