package raft

import (
	"encoding/json"
	"errors"
	"fmt"
	"testing"
	"time"
)

type assuranceFailOnceStore struct {
	*InmemStore
	injectFailures int
	injected       int
}

func (s *assuranceFailOnceStore) StoreLogs(logs []*Log) error {
	if s.injectFailures > 0 {
		s.injectFailures--
		s.injected++
		return errors.New("assurance: injected log store failure")
	}
	return s.InmemStore.StoreLogs(logs)
}

func assuranceVoters(c Configuration) int {
	voters := 0
	for _, server := range c.Servers {
		if server.Suffrage == Voter {
			voters++
		}
	}
	return voters
}

func assuranceEmitPhantom(t *testing.T, event map[string]interface{}) {
	payload, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("assurance: cannot encode event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(payload))
}

func assuranceWaitFor(deadline time.Duration, condition func() bool) bool {
	limit := time.Now().Add(deadline)
	for time.Now().Before(limit) {
		if condition() {
			return true
		}
		time.Sleep(10 * time.Millisecond)
	}
	return condition()
}

// TestAssurancePhantomConfigurationCommit carries the configuration-durability
// defect to its consequence: a node that failed to store a configuration entry
// adopts the new voter set, campaigns under it, and returns to the leader state
// with the help of a fresh peer that has no configuration of its own. The check
// observes whether the committed configuration is backed by a configuration
// entry at the index the node reports.
func TestAssurancePhantomConfigurationCommit(t *testing.T) {
	storeA := NewInmemStore()
	logsA := &assuranceFailOnceStore{InmemStore: storeA}
	snapsA := NewInmemSnapshotStore()
	addrA, transA := NewInmemTransport("")

	storeB := NewInmemStore()
	snapsB := NewInmemSnapshotStore()
	addrB, transB := NewInmemTransport("")

	transA.Connect(addrB, transB)
	transB.Connect(addrA, transA)

	newConf := func(addr ServerAddress) *Config {
		conf := DefaultConfig()
		conf.LocalID = ServerID(addr)
		conf.LogLevel = "ERROR"
		conf.HeartbeatTimeout = 50 * time.Millisecond
		conf.ElectionTimeout = 150 * time.Millisecond
		conf.LeaderLeaseTimeout = 50 * time.Millisecond
		conf.CommitTimeout = 5 * time.Millisecond
		return conf
	}

	confA := newConf(addrA)
	confB := newConf(addrB)

	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       ServerID(addrA),
		Address:  addrA,
	}}}
	if err := BootstrapCluster(confA, logsA, storeA, snapsA, transA, configuration); err != nil {
		t.Fatalf("assurance: bootstrap failed: %v", err)
	}

	rA, err := NewRaft(confA, &MockFSM{}, logsA, storeA, snapsA, transA)
	if err != nil {
		t.Fatalf("assurance: node A failed: %v", err)
	}
	defer rA.Shutdown()

	// The joining peer starts with no configuration and an empty log.
	rB, err := NewRaft(confB, &MockFSM{}, storeB, storeB, snapsB, transB)
	if err != nil {
		t.Fatalf("assurance: node B failed: %v", err)
	}
	defer rB.Shutdown()

	// A commits its bootstrap configuration and its own no-op first.
	if !assuranceWaitFor(5*time.Second, func() bool { return rA.State() == Leader && rA.CommitIndex() >= 2 }) {
		t.Fatalf("assurance: node A did not stabilise: state=%v commit=%d", rA.State(), rA.CommitIndex())
	}

	// Fail exactly the configuration entry's durable write.
	logsA.injectFailures = 1
	future := rA.AddVoter(ServerID(addrB), addrB, 0, 5*time.Second)
	appendErr := future.Error()
	time.Sleep(200 * time.Millisecond)

	assuranceEmitPhantom(t, map[string]interface{}{
		"event":                        "phantom_config_adopted",
		"scenario":                     "phantom-1",
		"adopted_latest_voter_count":   assuranceVoters(rA.configurations.latest),
		"adopted_latest_config_index":  rA.configurations.latestIndex,
		"adopted_committed_config_index": rA.configurations.committedIndex,
		"adopted_log_last_index":       rA.LastIndex(),
		"injected_failures":            logsA.injected,
		"append_error":                 fmt.Sprintf("%v", appendErr),
	})

	// Let node A campaign under the adopted voter set and return to the leader
	// state with the fresh peer's vote, then commit an entry of its own term.
	assuranceWaitFor(20*time.Second, func() bool {
		return rA.State() == Leader && assuranceVoters(rA.configurations.committed) == 2
	})
	time.Sleep(300 * time.Millisecond)

	configIndex := rA.configurations.committedIndex
	var entry Log
	entryErr := rA.logs.GetLog(configIndex, &entry)
	entryType, entryIsConfiguration := "unreadable", false
	if entryErr == nil {
		entryType = entry.Type.String()
		entryIsConfiguration = entry.Type == LogConfiguration
	}

	assuranceEmitPhantom(t, map[string]interface{}{
		"event":                          "committed_config_state",
		"scenario":                       "phantom-1",
		"phase":                          "after_recovery",
		"node_state":                     rA.State().String(),
		"committed_voter_count":          assuranceVoters(rA.configurations.committed),
		"committed_config_index":         configIndex,
		"committed_log_last_index":       rA.LastIndex(),
		"log_entry_type_at_config_index": entryType,
		"log_entry_is_configuration":     entryIsConfiguration,
		"log_entry_read_error":           fmt.Sprintf("%v", entryErr),
		"peer_config_voter_count":        assuranceVoters(rB.getLatestConfiguration()),
	})
}
