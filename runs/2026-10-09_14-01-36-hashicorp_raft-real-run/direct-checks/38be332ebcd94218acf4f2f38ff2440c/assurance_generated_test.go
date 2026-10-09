package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"testing"
	"time"
)

// assuranceRestoreStore fails SnapshotStore.Create once so a user restore
// aborts its inflight futures and then fails before replacing the FSM.
type assuranceRestoreStore struct {
	*InmemSnapshotStore
	failCreate bool
}

func (s *assuranceRestoreStore) Create(version SnapshotVersion, index, term uint64, configuration Configuration,
	configurationIndex uint64, trans Transport) (SnapshotSink, error) {
	if s.failCreate {
		return nil, fmt.Errorf("assurance: simulated snapshot create failure")
	}
	return s.InmemSnapshotStore.Create(version, index, term, configuration, configurationIndex, trans)
}

type assuranceFSM struct{}

func (assuranceFSM) Apply(*Log) interface{}         { return nil }
func (assuranceFSM) Snapshot() (FSMSnapshot, error) { return assuranceSnapshot{}, nil }
func (assuranceFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceSnapshot struct{}

func (assuranceSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (assuranceSnapshot) Release()                        {}

func assuranceEmit(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func TestAssuranceRestoreAbortBeforeFailedRestore(t *testing.T) {
	node := "n1"
	store := NewInmemStore()
	conf := DefaultConfig()
	conf.LocalID = ServerID(node)
	conf.ProtocolVersion = 3
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 100 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.SnapshotThreshold = 100000
	conf.skipStartup = true

	_, trans := NewInmemTransport(NewInmemAddr())
	snaps := &assuranceRestoreStore{InmemSnapshotStore: NewInmemSnapshotStore(), failCreate: true}
	r, err := NewRaft(conf, assuranceFSM{}, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}

	// Leader with a single-voter configuration so a dispatched entry reaches a quorum.
	cfg := Configuration{Servers: []Server{{ID: ServerID(node), Address: trans.LocalAddr(), Suffrage: Voter}}}
	r.setLatestConfiguration(cfg, 1)
	r.setCommittedConfiguration(cfg, 1)
	r.setCurrentTerm(2)
	r.setState(Leader)
	r.setupLeaderState()

	// Dispatch a real client entry; without a running leaderLoop it stays inflight.
	fut := &logFuture{log: Log{Type: LogCommand, Data: []byte("assurance-value")}}
	fut.init()
	r.dispatchLogs([]*logFuture{fut})
	idx := fut.Index()
	committedBefore := r.getCommitIndex()

	// User-triggered restore whose snapshot creation fails after the inflight abort.
	meta := &SnapshotMeta{
		Version:            1,
		ID:                 "assurance-restore",
		Index:              idx,
		Term:               2,
		Size:               3,
		Configuration:      cfg,
		ConfigurationIndex: 1,
	}
	restoreErr := r.restoreUserSnapshot(meta, strings.NewReader("abc"))
	futureErr := fut.Error()

	var stored Log
	getErr := store.GetLog(idx, &stored)
	committedAfter := r.getCommitIndex()
	commitmentIndex := r.leaderState.commitment.getCommitIndex()
	entryPresent := getErr == nil && stored.Index == idx
	// The commitment object owns the commit decision before the leader loop
	// consumes it onto raftState.commitIndex.
	committed := commitmentIndex >= idx || committedAfter >= idx
	// The documented meaning of ErrAbortedByRestore is that the write's effects
	// are absent after the restore; that holds only if the entry can no longer
	// take effect on the FSM.
	effectsAbsent := !(entryPresent && committed)

	assuranceEmit(map[string]interface{}{
		"event": "abort_delivered", "node": node,
		"restore_failed": restoreErr != nil,
		"future_error":   fmt.Sprint(futureErr),
		"index":          idx,
	})
	assuranceEmit(map[string]interface{}{
		"event": "abort_outcome", "node": node,
		"effects_absent": effectsAbsent,
		"entry_present":  entryPresent,
		"committed":      committed,
		"committed_before": committedBefore,
		"committed_after":  committedAfter,
		"commitment_index": commitmentIndex,
		"future_error":     fmt.Sprint(futureErr),
		"restore_failed":   restoreErr != nil,
	})
}
