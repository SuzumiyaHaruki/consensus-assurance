package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"testing"
	"time"
)

// csBatchingFSM implements FSM, BatchingFSM and ConfigurationStore. It mirrors
// a persistent FSM that expects the library to deliver committed configuration
// entries through ConfigurationStore, and records what it actually receives.
type csBatchingFSM struct {
	mu            sync.Mutex
	applied       [][]byte
	storedConfigs []uint64
	batchConfigs  []uint64
}

func (f *csBatchingFSM) Apply(l *Log) interface{} {
	f.mu.Lock()
	defer f.mu.Unlock()
	if l.Type == LogCommand {
		f.applied = append(f.applied, l.Data)
	}
	return len(f.applied)
}

func (f *csBatchingFSM) ApplyBatch(logs []*Log) []interface{} {
	f.mu.Lock()
	defer f.mu.Unlock()
	ret := make([]interface{}, len(logs))
	for i, l := range logs {
		switch l.Type {
		case LogCommand:
			f.applied = append(f.applied, l.Data)
			ret[i] = len(f.applied)
		case LogConfiguration:
			f.batchConfigs = append(f.batchConfigs, l.Index)
		default:
			ret[i] = nil
		}
	}
	return ret
}

func (f *csBatchingFSM) StoreConfiguration(index uint64, config Configuration) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.storedConfigs = append(f.storedConfigs, index)
}

func (f *csBatchingFSM) Snapshot() (FSMSnapshot, error) { return &csSnapshot{}, nil }

func (f *csBatchingFSM) Restore(r io.ReadCloser) error {
	r.Close()
	return nil
}

func (f *csBatchingFSM) observed() (stores []uint64, batch []uint64) {
	f.mu.Lock()
	defer f.mu.Unlock()
	stores = append(stores, f.storedConfigs...)
	batch = append(batch, f.batchConfigs...)
	return stores, batch
}

type csSnapshot struct{}

func (s *csSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (s *csSnapshot) Release()                        {}

func csEmit(t *testing.T, ev map[string]interface{}) {
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceConfigStoreDeliveryForBatchingFSM observes whether the library
// delivers a committed LogConfiguration entry to an FSM that implements both
// BatchingFSM and ConfigurationStore: does StoreConfiguration get called, or
// does the entry only reach ApplyBatch?
func TestAssuranceConfigStoreDeliveryForBatchingFSM(t *testing.T) {
	conf := inmemConfig(t)
	conf.SnapshotThreshold = 1 << 62
	conf.SnapshotInterval = time.Hour

	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:       1,
		Bootstrap:   true,
		Conf:        conf,
		MakeFSMFunc: func() FSM { return &csBatchingFSM{} },
	})
	defer c.Close()

	leader := c.Leader()
	fsm := c.fsms[0].(*csBatchingFSM)

	_, batching := interface{}(fsm).(BatchingFSM)
	_, configStore := interface{}(fsm).(ConfigurationStore)
	csEmit(t, map[string]interface{}{
		"event":                              "scenario_declared",
		"fsm_implements_batching":            batching,
		"fsm_implements_configuration_store": configStore,
	})

	// Ensure an entry of this leader's term is committed so configuration
	// changes are permitted (configurationChangeChIfStable).
	if err := leader.Barrier(10 * time.Second).Error(); err != nil {
		t.Fatalf("barrier before configuration change: %v", err)
	}

	// Commit a configuration change entry.
	add := leader.AddNonvoter(ServerID("assurance-n2"), ServerAddress("assurance-n2"), 0, 10*time.Second)
	if err := add.Error(); err != nil {
		t.Fatalf("add nonvoter: %v", err)
	}
	configIndex := add.Index()
	csEmit(t, map[string]interface{}{
		"event":        "config_change_committed",
		"op_id":        "cfg-1",
		"config_index": configIndex,
		"committed":    true,
	})

	// A barrier queued after the configuration entry guarantees the FSM
	// goroutine processed the configuration entry before sampling.
	if err := leader.Barrier(10 * time.Second).Error(); err != nil {
		t.Fatalf("barrier after configuration change: %v", err)
	}

	stores, batch := fsm.observed()
	delivered := false
	for _, idx := range batch {
		if idx == configIndex {
			delivered = true
		}
	}
	csEmit(t, map[string]interface{}{
		"event":                      "fsm_config_delivery",
		"op_id":                      "cfg-1",
		"config_index":               configIndex,
		"entry_delivered_to_fsm":     delivered,
		"applybatch_config_indices":  batch,
		"store_configuration_calls":  len(stores),
		"store_configuration_called": len(stores) > 0,
	})
}
