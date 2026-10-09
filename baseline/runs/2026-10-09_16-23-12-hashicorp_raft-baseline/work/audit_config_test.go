package raft_test

import (
	"io"
	"testing"
	"time"

	raft "github.com/hashicorp/raft"
)

func TestAuditGetConfigurationDisablesStartup(t *testing.T) {
	for _, inspect := range []bool{true, false} {
		name := "reuse_config_after_GetConfiguration"
		if !inspect {
			name = "without_GetConfiguration_control"
		}
		t.Run(name, func(t *testing.T) {
			cfg := raft.DefaultConfig()
			cfg.LocalID = "only-node"
			cfg.HeartbeatTimeout = 20 * time.Millisecond
			cfg.ElectionTimeout = 20 * time.Millisecond
			cfg.LeaderLeaseTimeout = 20 * time.Millisecond
			cfg.LogOutput = io.Discard
			_, trans := raft.NewInmemTransport("only-node")
			store, snaps := raft.NewInmemStore(), raft.NewInmemSnapshotStore()
			membership := raft.Configuration{Servers: []raft.Server{{ID: "only-node", Address: "only-node", Suffrage: raft.Voter}}}
			if err := raft.BootstrapCluster(cfg, store, store, snaps, trans, membership); err != nil {
				t.Fatal(err)
			}
			if inspect {
				actual, err := raft.GetConfiguration(cfg, &raft.MockFSM{}, store, store, snaps, trans)
				if err != nil {
					t.Fatal(err)
				}
				if len(actual.Servers) != 1 {
					t.Fatalf("unexpected configuration: %+v", actual)
				}
			}
			node, err := raft.NewRaft(cfg, &raft.MockFSM{}, store, store, snaps, trans)
			if err != nil {
				t.Fatal(err)
			}
			defer func() { node.Shutdown().Error() }()
			deadline := time.Now().Add(300 * time.Millisecond)
			for node.State() != raft.Leader && time.Now().Before(deadline) {
				time.Sleep(time.Millisecond)
			}
			err = node.Apply([]byte("command"), 50*time.Millisecond).Error()
			t.Logf("after inspection=%v: state=%s term=%d apply error=%v", inspect, node.State(), node.CurrentTerm(), err)
			if node.State() != raft.Leader || err != nil {
				t.Error("new single-voter node did not start after reuse of Config passed to GetConfiguration")
			}
		})
	}
}
