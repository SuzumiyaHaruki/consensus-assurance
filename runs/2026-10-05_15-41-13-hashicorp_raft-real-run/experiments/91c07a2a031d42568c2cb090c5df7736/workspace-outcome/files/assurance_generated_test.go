package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func assuranceEmitReadout(t *testing.T, event map[string]interface{}) {
	payload, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("assurance: cannot encode event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(payload))
}

// TestAssuranceConfigurationIndexReadout drives a real single-voter cluster into
// the leader state and compares the configuration index reported by the public
// read API with the index of the configuration the node is actually using.
func TestAssuranceConfigurationIndexReadout(t *testing.T) {
	store := NewInmemStore()
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

	if err := BootstrapCluster(conf, store, store, snaps, trans, configuration); err != nil {
		t.Fatalf("assurance: bootstrap failed: %v", err)
	}

	r, err := NewRaft(conf, &MockFSM{}, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("assurance: NewRaft failed: %v", err)
	}
	defer r.Shutdown()

	// Wait until the bootstrap configuration is committed and this leader has
	// committed an entry of its own term.
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

	assuranceEmitReadout(t, map[string]interface{}{
		"event":                       "config_index_probe",
		"probe":                       "cfg-index-1",
		"live_latest_config_index":    r.configurations.latestIndex,
		"live_committed_config_index": r.configurations.committedIndex,
	})

	future := r.GetConfiguration()
	readErr := future.Error()
	reported := future.Index()
	statsReported := r.Stats()["latest_configuration_index"]

	assuranceEmitReadout(t, map[string]interface{}{
		"event":                        "config_index_readout",
		"probe":                        "cfg-index-1",
		"phase":                        "readout",
		"read_error":                   fmt.Sprintf("%v", readErr),
		"reported_index":               reported,
		"stats_reported_index":         statsReported,
		"live_latest_config_index_now": r.configurations.latestIndex,
	})
}
