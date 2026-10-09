package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
)

type assuranceRecStore struct {
	*InmemStore
	failNext bool
	failed   bool
}

func (s *assuranceRecStore) StoreLog(log *Log) error {
	if s.failNext {
		s.failNext = false
		s.failed = true
		return fmt.Errorf("assurance: simulated StoreLog failure")
	}
	return s.InmemStore.StoreLog(log)
}

type assuranceRecFSM struct{}

func (assuranceRecFSM) Apply(*Log) interface{}         { return nil }
func (assuranceRecFSM) Snapshot() (FSMSnapshot, error) { return assuranceRecSnapshot{}, nil }
func (assuranceRecFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceRecSnapshot struct{}

func (assuranceRecSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (assuranceRecSnapshot) Release()                        {}

func assuranceEmit(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceBootstrapRecoverControl is a diagnostic control for the confirmed
// bootstrap premise: it checks whether the documented RecoverCluster path can
// still reset a store left by a failed bootstrap.
func TestAssuranceBootstrapRecoverControl(t *testing.T) {
	node := "n1"
	store := &assuranceRecStore{InmemStore: NewInmemStore()}
	snaps := NewInmemSnapshotStore()
	_, trans := NewInmemTransport(NewInmemAddr())
	conf := DefaultConfig()
	conf.LocalID = ServerID(node)
	conf.ProtocolVersion = 3
	cfg := Configuration{Servers: []Server{{ID: ServerID(node), Address: trans.LocalAddr(), Suffrage: Voter}}}

	// Reproduce the partial bootstrap: the term write succeeds, the log write fails.
	store.failNext = true
	firstErr := BootstrapCluster(conf, store, store, snaps, trans, cfg)
	existing, _ := HasExistingState(store, store, snaps)

	// Control: the documented recovery path on the same store.
	recoverErr := RecoverCluster(conf, assuranceRecFSM{}, store, store, snaps, trans, cfg)
	logIndex, _ := store.LastIndex()
	snapsAfter, _ := snaps.List()
	recoverSucceeded := recoverErr == nil

	assuranceEmit(map[string]interface{}{
		"event": "bootstrap_attempt", "node": node,
		"first_error": firstErr != nil, "store_log_failed": store.failed,
	})
	assuranceEmit(map[string]interface{}{
		"event": "recover_control", "node": node,
		"existing_state": existing, "recover_error": fmt.Sprint(recoverErr),
		"recover_succeeded": recoverSucceeded, "log_index_after": logIndex,
		"snapshots_after": len(snapsAfter),
	})
}
