package raft

import (
	"encoding/json"
	"fmt"
	"testing"
)

// assuranceBootstrapStore fails a single StoreLog call so the bootstrap
// sequence can stop after the current term has been written.
type assuranceBootstrapStore struct {
	*InmemStore
	failNextStoreLog bool
	storeLogFailed   bool
}

func (s *assuranceBootstrapStore) StoreLog(log *Log) error {
	if s.failNextStoreLog {
		s.failNextStoreLog = false
		s.storeLogFailed = true
		return fmt.Errorf("assurance: simulated StoreLog failure")
	}
	return s.InmemStore.StoreLog(log)
}

func assuranceEmit(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func TestAssuranceBootstrapPartialStateBlocksRetry(t *testing.T) {
	node := "n1"
	store := &assuranceBootstrapStore{InmemStore: NewInmemStore()}
	snaps := NewInmemSnapshotStore()
	_, trans := NewInmemTransport(NewInmemAddr())

	conf := DefaultConfig()
	conf.LocalID = ServerID(node)
	conf.ProtocolVersion = 3
	configuration := Configuration{Servers: []Server{{ID: ServerID(node), Address: trans.LocalAddr(), Suffrage: Voter}}}
	ptr := conf

	clean, err := HasExistingState(store, store, snaps)
	if err != nil {
		t.Fatalf("HasExistingState before: %v", err)
	}

	// First bootstrap attempt: the term write succeeds, the log store fails.
	store.failNextStoreLog = true
	firstErr := BootstrapCluster(ptr, store, store, snaps, trans, configuration)
	logIndexAfterFirst, _ := store.LastIndex()

	existingAfter, existingErr := HasExistingState(store, store, snaps)
	if existingErr != nil {
		t.Fatalf("HasExistingState after: %v", existingErr)
	}

	// Retry: the store is now healthy, so a bootstrappable server should seed.
	secondErr := BootstrapCluster(ptr, store, store, snaps, trans, configuration)
	logIndexAfterRetry, _ := store.LastIndex()
	retryAllowed := secondErr == nil && logIndexAfterRetry > 0

	assuranceEmit(map[string]interface{}{
		"event": "bootstrap_attempt", "node": node,
		"clean_before": !clean, "first_error": firstErr != nil,
		"store_log_failed": store.storeLogFailed, "log_index_after_first": logIndexAfterFirst,
	})
	assuranceEmit(map[string]interface{}{
		"event": "bootstrap_outcome", "node": node,
		"existing_state": existingAfter, "retry_allowed": retryAllowed,
		"second_error": fmt.Sprint(secondErr), "log_index_after_retry": logIndexAfterRetry,
	})
}
