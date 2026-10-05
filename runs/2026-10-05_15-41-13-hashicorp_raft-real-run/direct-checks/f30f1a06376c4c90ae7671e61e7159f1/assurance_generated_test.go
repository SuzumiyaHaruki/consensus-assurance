package raft

import (
	"encoding/json"
	"errors"
	"fmt"
	"testing"
	"time"
)

// assuranceFailingLogStore wraps an InmemStore so that a bounded number of
// durable log writes can be made to fail without changing any target code.
type assuranceFailingLogStore struct {
	*InmemStore
	injectFailures int
	injected       int
}

func (s *assuranceFailingLogStore) StoreLogs(logs []*Log) error {
	if s.injectFailures > 0 {
		s.injectFailures--
		s.injected++
		return errors.New("assurance: injected log store failure")
	}
	return s.InmemStore.StoreLogs(logs)
}

func assuranceEmit(t *testing.T, event map[string]interface{}) {
	payload, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("assurance: cannot encode event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(payload))
}

func assuranceVoterCount(c Configuration) int {
	voters := 0
	for _, server := range c.Servers {
		if server.Suffrage == Voter {
			voters++
		}
	}
	return voters
}

// TestAssuranceConfigAppendStoreFailure drives one configuration change through
// a leader whose next durable log write fails, and observes whether the node's
// latest configuration still describes only the configuration that is actually
// present in the log.
func TestAssuranceConfigAppendStoreFailure(t *testing.T) {
	base := NewInmemStore()
	logs := &assuranceFailingLogStore{InmemStore: base}
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("")

	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       ServerID(addr),
		Address:  addr,
	}}}

	conf := DefaultConfig()
	conf.LocalID = ServerID(addr)
	conf.LogLevel = "ERROR"
	conf.HeartbeatTimeout = 50 * time.Millisecond
	conf.ElectionTimeout = 50 * time.Millisecond
	conf.LeaderLeaseTimeout = 50 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond

	if err := BootstrapCluster(conf, logs, base, snaps, trans, configuration); err != nil {
		t.Fatalf("assurance: bootstrap failed: %v", err)
	}

	r, err := NewRaft(conf, &MockFSM{}, logs, base, snaps, trans)
	if err != nil {
		t.Fatalf("assurance: NewRaft failed: %v", err)
	}
	defer r.Shutdown()

	// Wait for the single-voter cluster to elect itself and commit its no-op,
	// so that the configuration-change gate is open before the attempt.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if r.State() == Leader && r.CommitIndex() >= 2 {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if r.State() != Leader || r.CommitIndex() < 2 {
		t.Fatalf("assurance: cluster did not stabilise: state=%v commit=%d", r.State(), r.CommitIndex())
	}

	preVoters := assuranceVoterCount(r.configurations.latest)
	assuranceEmit(t, map[string]interface{}{
		"event":              "config_append_attempt",
		"attempt":            "config-append-1",
		"pre_voter_count":    preVoters,
		"pre_log_last_index": r.LastIndex(),
	})

	// Make the next durable log write - the configuration entry itself - fail.
	logs.injectFailures = 1
	peerAddr := ServerAddress(NewInmemAddr())
	peerID := ServerID(peerAddr)
	future := r.AddVoter(peerID, peerAddr, 0, 5*time.Second)
	appendErr := future.Error()

	// Let the main loop finish the configuration-append path.
	deadline = time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) && r.State() == Leader {
		time.Sleep(5 * time.Millisecond)
	}
	time.Sleep(200 * time.Millisecond)

	assuranceEmit(t, map[string]interface{}{
		"event":              "config_state_after_failure",
		"attempt":            "config-append-1",
		"phase":              "after_failed_append",
		"store_failed":       logs.injected > 0,
		"append_error":       fmt.Sprintf("%v", appendErr),
		"latest_voter_count": assuranceVoterCount(r.configurations.latest),
		"latest_index":       r.configurations.latestIndex,
		"committed_index":    r.configurations.committedIndex,
		"log_last_index":     r.LastIndex(),
	})
}
