package dragonboat

import (
	"fmt"
	"testing"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/rsm"
	"github.com/lni/dragonboat/v3/internal/vfs"
	pb "github.com/lni/dragonboat/v3/raftpb"
)

func assuranceCCEntry(t *testing.T, index uint64, cc pb.ConfigChange) pb.Entry {
	t.Helper()
	data, err := cc.Marshal()
	if err != nil {
		t.Fatalf("failed to marshal config change %v", err)
	}
	return pb.Entry{Index: index, Term: 1, Type: pb.ConfigChangeEntry, Cmd: data}
}

// TestAssuranceWitnessRecordFromMembership lets the replicated state machine
// build its membership from configuration-change entries - first the cluster's
// only voting member, then the local node as a witness - and then reads back
// what node.notifyConfigChange stores and what node.getClusterInfo reports.
func TestAssuranceWitnessRecordFromMembership(t *testing.T) {
	fs := vfs.GetTestFS()
	cfg := config.Config{ClusterID: 1, NodeID: 2}
	n := &node{
		clusterID:    1,
		nodeID:       2,
		config:       cfg,
		initializedC: make(chan struct{}),
		sysEvents:    &sysEventListener{},
	}
	n.sm = rsm.NewStateMachine(
		rsm.NewNativeSM(cfg, &rsm.InMemStateMachine{}, nil),
		nil, cfg, &testDummyNodeProxy{}, fs)

	n.sm.TaskQ().Add(rsm.Task{Entries: []pb.Entry{
		assuranceCCEntry(t, 1, pb.ConfigChange{
			Type: pb.AddNode, NodeID: 1, Address: "a1", ConfigChangeId: 0,
		}),
		assuranceCCEntry(t, 2, pb.ConfigChange{
			Type: pb.AddWitness, NodeID: 2, Address: "a2", ConfigChangeId: 1,
		}),
	}})
	if _, err := n.sm.Handle(nil, nil); err != nil {
		t.Fatalf("failed to apply config changes %v", err)
	}
	m := n.sm.GetMembership()
	_, localIsWitness := m.Witnesses[2]
	fmt.Printf("CA_EVENT {\"event\":\"membership\",\"addresses\":%d,\"witnesses\":%d,\"local_is_witness\":%t,\"config_change_id\":%d}\n",
		len(m.Addresses), len(m.Witnesses), localIsWitness, m.ConfigChangeId)

	n.notifyConfigChange()
	stored, ok := n.clusterInfo.Load().(*ClusterInfo)
	if !ok || stored == nil {
		t.Fatalf("no cluster record stored")
	}
	fmt.Printf("CA_EVENT {\"event\":\"stored\",\"is_witness\":%t,\"is_observer\":%t,\"config_index\":%d,\"node_count\":%d}\n",
		stored.IsWitness, stored.IsObserver, stored.ConfigChangeIndex, len(stored.Nodes))

	reported := n.getClusterInfo()
	fmt.Printf("CA_EVENT {\"event\":\"reported\",\"is_witness\":%t,\"is_observer\":%t,\"pending\":%t,\"config_index\":%d,\"node_count\":%d}\n",
		reported.IsWitness, reported.IsObserver, reported.Pending,
		reported.ConfigChangeIndex, len(reported.Nodes))
}
