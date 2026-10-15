// Copyright IBM Corp. 2013, 2026
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"io"
	"sync"
	"testing"
	"time"
)

// assuranceRecorder counts the callbacks an application FSM receives.
type assuranceRecorder struct {
	mu                 sync.Mutex
	storeConfigCalls   []uint64
	applyBatchConfigs  int
	applyBatchCommands int
	applyCommands      int
}

func (r *assuranceRecorder) record(name string, log *Log) {
	r.mu.Lock()
	defer r.mu.Unlock()
	switch name {
	case "store":
		r.storeConfigCalls = append(r.storeConfigCalls, log.Index)
	case "apply":
		if log.Type == LogConfiguration {
			r.applyBatchConfigs++
		} else {
			r.applyBatchCommands++
		}
	}
}

func (r *assuranceRecorder) snapshot() map[string]interface{} {
	r.mu.Lock()
	defer r.mu.Unlock()
	return map[string]interface{}{
		"store_configuration_calls": len(r.storeConfigCalls),
		"apply_batch_config_logs":   r.applyBatchConfigs,
		"apply_batch_commands":      r.applyBatchCommands,
	}
}

// assuranceFSM implements FSM and ConfigurationStore, recording both.
type assuranceFSM struct{ rec *assuranceRecorder }

func (f *assuranceFSM) Apply(l *Log) interface{} {
	f.rec.record("apply", l)
	return nil
}
func (f *assuranceFSM) Snapshot() (FSMSnapshot, error) { return &MockSnapshot{}, nil }
func (f *assuranceFSM) Restore(io.ReadCloser) error    { return nil }
func (f *assuranceFSM) StoreConfiguration(index uint64, c Configuration) {
	f.rec.record("store", &Log{Type: LogConfiguration, Index: index})
}

// assuranceBatchingFSM additionally implements BatchingFSM, so the same FSM
// satisfies both public interfaces.
type assuranceBatchingFSM struct{ assuranceFSM }

func (f *assuranceBatchingFSM) ApplyBatch(logs []*Log) []interface{} {
	out := make([]interface{}, len(logs))
	for _, l := range logs {
		f.rec.record("apply", l)
	}
	return out
}

func assuranceEmit(t *testing.T, event map[string]interface{}) {
	b, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	t.Log("CA_EVENT " + string(b))
}

// TestAssuranceConfigurationStoreWithBatching asks whether an FSM that
// implements both BatchingFSM and ConfigurationStore receives a committed
// configuration change through StoreConfiguration, which its own documentation
// promises unconditionally, or only through ApplyBatch.
func TestAssuranceConfigurationStoreWithBatching(t *testing.T) {
	assuranceRunConfigStoreTrial(t, false, "move-voter-address")
	assuranceRunConfigStoreTrial(t, true, "move-voter-address")
	// Other configuration commands take the same apply path; this checks that
	// the missing callback is not specific to one kind of change.
	assuranceRunConfigStoreTrial(t, true, "add-nonvoter")
	assuranceRunConfigStoreTrial(t, true, "remove-follower")
}

func assuranceRunConfigStoreTrial(t *testing.T, batching bool, trigger string) {
	rec := &assuranceRecorder{}
	conf := inmemConfig(t)
	makeFSM := func() FSM {
		if batching {
			return &assuranceBatchingFSM{assuranceFSM{rec: rec}}
		}
		return &assuranceFSM{rec: rec}
	}
	c := MakeClusterCustom(t, &MakeClusterOpts{Peers: 3, Bootstrap: true, Conf: conf, MakeFSMFunc: makeFSM})
	defer c.Close()

	leader := c.Leader()
	var target *Raft
	for _, r := range c.rafts {
		if r != leader {
			target = r
			break
		}
	}
	assuranceEmit(t, map[string]interface{}{
		"event":        "assurance_config_store_setup",
		"batching_fsm": batching,
		"trigger":      trigger,
		"leader_id":    string(leader.localID),
		"target_id":    string(target.localID),
		"peer_count":   len(c.rafts),
	})

	// Trigger one configuration change: move an existing voter's address.
	changeErr := "nil"
	switch trigger {
	case "add-nonvoter":
		if err := leader.AddNonvoter(ServerID("assurance-join-"+string(target.localID)), ServerAddress("assurance-join-addr-"+string(target.localID)), 0, 5*time.Second).Error(); err != nil {
			changeErr = err.Error()
		}
	case "remove-follower":
		if err := leader.RemoveServer(target.localID, 0, 5*time.Second).Error(); err != nil {
			changeErr = err.Error()
		}
	default:
		if err := leader.AddVoter(target.localID, ServerAddress("assurance-moved-"+string(target.localID)), 0, 5*time.Second).Error(); err != nil {
			changeErr = err.Error()
		}
	}

	// Wait for the configuration change to reach the FSM.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		st := rec.snapshot()
		if st["store_configuration_calls"].(int) > 0 || st["apply_batch_config_logs"].(int) > 0 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	time.Sleep(200 * time.Millisecond)

	event := map[string]interface{}{
		"event":        "assurance_config_store_result",
		"batching_fsm": batching,
		"trigger":      trigger,
		"leader_id":    string(leader.localID),
		"target_id":    string(target.localID),
		"change_error": changeErr,
	}
	for k, v := range rec.snapshot() {
		event[k] = v
	}
	assuranceEmit(t, event)
}
