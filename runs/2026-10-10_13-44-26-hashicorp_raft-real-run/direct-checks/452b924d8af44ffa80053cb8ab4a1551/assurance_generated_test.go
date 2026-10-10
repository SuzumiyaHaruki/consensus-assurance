package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"testing"
	"time"

	"github.com/hashicorp/go-hclog"
)

type assuranceBatchConfigFSM struct {
	mu sync.Mutex

	applyBatchConfigs int
	storeConfigs      int
}

func (f *assuranceBatchConfigFSM) Apply(*Log) interface{} {
	return nil
}

func (f *assuranceBatchConfigFSM) ApplyBatch(logs []*Log) []interface{} {
	f.mu.Lock()
	defer f.mu.Unlock()
	responses := make([]interface{}, len(logs))
	for _, entry := range logs {
		if entry.Type == LogConfiguration {
			f.applyBatchConfigs++
		}
	}
	return responses
}

func (f *assuranceBatchConfigFSM) StoreConfiguration(uint64, Configuration) {
	f.mu.Lock()
	f.storeConfigs++
	f.mu.Unlock()
}

func (f *assuranceBatchConfigFSM) Snapshot() (FSMSnapshot, error) {
	return assuranceBatchConfigSnapshot{}, nil
}

func (f *assuranceBatchConfigFSM) Restore(io.ReadCloser) error {
	return nil
}

type assuranceBatchConfigSnapshot struct{}

func (assuranceBatchConfigSnapshot) Persist(sink SnapshotSink) error {
	return sink.Close()
}

func (assuranceBatchConfigSnapshot) Release() {}

func assuranceBatchConfigEmit(t *testing.T, value map[string]interface{}) {
	t.Helper()
	encoded, err := json.Marshal(value)
	if err != nil {
		t.Fatalf("encode event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(encoded))
}

func TestAssuranceBatchConfigStoreCallback(t *testing.T) {
	fsm := &assuranceBatchConfigFSM{}
	conf := DefaultConfig()
	conf.ProtocolVersion = ProtocolVersionMax
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 100 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.SnapshotInterval = time.Hour
	conf.SnapshotThreshold = 1 << 20
	conf.TrailingLogs = 1024
	conf.Logger = hclog.NewNullLogger()

	cluster := MakeClusterCustom(t, &MakeClusterOpts{
		Peers:     1,
		Bootstrap: true,
		Conf:      conf,
		MakeFSMFunc: func() FSM {
			return fsm
		},
	})
	defer cluster.Close()

	leader := cluster.Leader()
	assuranceBatchConfigEmit(t, map[string]interface{}{
		"event":                "fsm_setup",
		"fsm_id":               "batch-config-fsm",
		"operation":            "FSMConfigDelivery",
		"batching_enabled":     true,
		"config_store_enabled": true,
		"leader_id":            string(leader.localID),
	})

	if err := leader.Barrier(5 * time.Second).Error(); err != nil {
		t.Fatalf("barrier: %v", err)
	}

	fsm.mu.Lock()
	batchConfigs := fsm.applyBatchConfigs
	storeConfigs := fsm.storeConfigs
	fsm.mu.Unlock()

	assuranceBatchConfigEmit(t, map[string]interface{}{
		"event":                           "config_delivery",
		"fsm_id":                          "batch-config-fsm",
		"operation":                       "FSMConfigDelivery",
		"config_entry_delivered_to_batch": batchConfigs > 0,
		"apply_batch_config_count":        batchConfigs,
		"store_config_count":              storeConfigs,
	})
}
