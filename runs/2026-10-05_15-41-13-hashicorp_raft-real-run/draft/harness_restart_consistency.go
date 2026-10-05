package raft

import (
	"encoding/json"
	"errors"
	"fmt"
	"testing"
	"time"
)

type assuranceRestartStore struct {
	*InmemStore
	injectFailures int
	injected       int
}

func (s *assuranceRestartStore) StoreLogs(logs []*Log) error {
	if s.injectFailures > 0 {
		s.injectFailures--
		s.injected++
		return errors.New("assurance: injected log store failure")
	}
	return s.InmemStore.StoreLogs(logs)
}

func assuranceRestartVoters(c Configuration) int {
	voters := 0
	for _, server := range c.Servers {
		if server.Suffrage == Voter {
			voters++
		}
	}
	return voters
}

func assuranceRestartEmit(t *testing.T, event map[string]interface{}) {
	payload, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("assurance: cannot encode event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(payload))
}

func assuranceRestartWaitFor(deadline time.Duration, condition func() bool) bool {
	limit := time.Now().Add(deadline)
	for time.Now().Before(limit) {
		if condition() {
			return true
		}
		time.Sleep(10 * time.Millisecond)
	}
	return condition()
}

// TestAssuranceRestartConfigurationConsistency repeats the configuration-write
// failure that leads a node to adopt an unpersisted configuration, lets it
// commit that configuration, then restarts the node over the same stores and
// observes which configuration it re-derives from its log.
func TestAssuranceRestartConfigurationConsistency(t *testing.T) {
	storeA := NewInmemStore()
	logsA := &assuranceRestartStore{InmemStore: storeA}
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
	rB, err := NewRaft(confB, &MockFSM{}, storeB, storeB, snapsB, transB)
	if err != nil {
		t.Fatalf("assurance: node B failed: %v", err)
	}
	defer rB.Shutdown()

	if !assuranceRestartWaitFor(5*time.Second, func() bool { return rA.State() == Leader && rA.CommitIndex() >= 2 }) {
		t.Fatalf("assurance: node A did not stabilise: state=%v commit=%d", rA.State(), rA.CommitIndex())
	}

	logsA.injectFailures = 1
	future := rA.AddVoter(ServerID(addrB), addrB, 0, 5*time.Second)
	appendErr := future.Error()

	// Let node A return to the leader state under the adopted voter set and
	// commit that configuration before it is restarted.
	assuranceRestartWaitFor(20*time.Second, func() bool {
		return rA.State() == Leader && assuranceRestartVoters(rA.configurations.committed) == 2
	})
	time.Sleep(200 * time.Millisecond)

	assuranceRestartEmit(t, map[string]interface{}{
		"event":                          "configuration_attempt",
		"scenario":                       "restart-1",
		"injected_failures":              logsA.injected,
		"append_error":                   fmt.Sprintf("%v", appendErr),
		"pre_restart_committed_voters":   assuranceRestartVoters(rA.configurations.committed),
		"pre_restart_config_index":       rA.configurations.committedIndex,
		"pre_restart_log_last_index":     rA.LastIndex(),
	})

	// Restart the node over the same stores.
	_ = rA.Shutdown().Error()

	rA2, err := NewRaft(confA, &MockFSM{}, logsA, storeA, snapsA, transA)
	if err != nil {
		t.Fatalf("assurance: restarted node failed: %v", err)
	}
	defer rA2.Shutdown()

	// Let the restarted node re-derive its configuration and commit an entry.
	assuranceRestartWaitFor(10*time.Second, func() bool {
		return rA2.State() == Leader && rA2.CommitIndex() > 3
	})
	time.Sleep(200 * time.Millisecond)

	latestIndex := rA2.configurations.latestIndex
	var entry Log
	entryErr := rA2.logs.GetLog(latestIndex, &entry)
	entryType, entryIsConfiguration := "unreadable", false
	if entryErr == nil {
		entryType = entry.Type.String()
		entryIsConfiguration = entry.Type == LogConfiguration
	}

	assuranceRestartEmit(t, map[string]interface{}{
		"event":                              "restart_configuration_state",
		"scenario":                           "restart-1",
		"phase":                              "after_restart",
		"restarted_state":                    rA2.State().String(),
		"restarted_latest_voter_count":       assuranceRestartVoters(rA2.configurations.latest),
		"restarted_committed_voter_count":    assuranceRestartVoters(rA2.configurations.committed),
		"restarted_latest_config_index":      latestIndex,
		"restarted_committed_config_index":   rA2.configurations.committedIndex,
		"restarted_log_last_index":           rA2.LastIndex(),
		"log_entry_type_at_latest_config":    entryType,
		"log_entry_is_configuration":         entryIsConfiguration,
		"log_entry_read_error":               fmt.Sprintf("%v", entryErr),
	})
}
