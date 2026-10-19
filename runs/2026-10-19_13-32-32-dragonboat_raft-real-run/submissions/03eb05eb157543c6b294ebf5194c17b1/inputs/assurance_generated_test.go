package dragonboat

import (
	"fmt"
	"testing"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/rsm"
	"github.com/lni/dragonboat/v3/internal/vfs"
)

// assuranceClusterInfoNode builds a node that carries the role flag a witness
// node is started with and a local state machine whose only use here is to
// report the state machine type. The raft peer is left nil, so the leader flag
// is reported as not leader.
func assuranceClusterInfoNode(t *testing.T, isWitness bool) *node {
	t.Helper()
	fs := vfs.GetTestFS()
	cfg := config.Config{ClusterID: 1, NodeID: 2, IsWitness: isWitness}
	n := &node{
		clusterID:    1,
		nodeID:       2,
		config:       cfg,
		initializedC: make(chan struct{}),
	}
	n.sm = rsm.NewStateMachine(
		rsm.NewNativeSM(cfg, &rsm.InMemStateMachine{}, nil),
		nil, cfg, &testDummyNodeProxy{}, fs)
	return n
}

// TestAssuranceClusterInfoWitnessFlag checks whether the per-cluster summary
// returned to a client reports a witness node as a witness. node.getClusterInfo
// rebuilds a ClusterInfo from the atomic record that node.notifyConfigChange
// stores; that record carries both the observer and the witness flag computed
// from the replicated membership. The witness case stores exactly such a
// record on a node whose own config says it is a witness, and the observer case
// stores an equivalent record for an observer as a control.
func TestAssuranceClusterInfoWitnessFlag(t *testing.T) {
	witness := assuranceClusterInfoNode(t, true)
	witness.clusterInfo.Store(&ClusterInfo{
		ClusterID:         1,
		NodeID:            2,
		IsLeader:          false,
		IsObserver:        false,
		IsWitness:         true,
		ConfigChangeIndex: 7,
		Nodes:             map[uint64]string{1: "a1", 2: "a2", 3: "a3"},
	})
	wci := witness.getClusterInfo()
	fmt.Printf("CA_EVENT {\"event\":\"witness_record\",\"stored_is_witness\":%t,\"node_config_is_witness\":%t,\"reported_is_witness\":%t,\"reported_is_observer\":%t,\"config_index\":%d,\"node_count\":%d,\"pending\":%t}\n",
		true, witness.isWitness(), wci.IsWitness, wci.IsObserver,
		wci.ConfigChangeIndex, len(wci.Nodes), wci.Pending)

	observer := assuranceClusterInfoNode(t, false)
	observer.clusterInfo.Store(&ClusterInfo{
		ClusterID:         1,
		NodeID:            2,
		IsLeader:          false,
		IsObserver:        true,
		IsWitness:         false,
		ConfigChangeIndex: 9,
		Nodes:             map[uint64]string{1: "a1", 2: "a2"},
	})
	oci := observer.getClusterInfo()
	fmt.Printf("CA_EVENT {\"event\":\"observer_record\",\"stored_is_observer\":%t,\"reported_is_observer\":%t,\"reported_is_witness\":%t,\"config_index\":%d,\"node_count\":%d,\"pending\":%t}\n",
		true, oci.IsObserver, oci.IsWitness,
		oci.ConfigChangeIndex, len(oci.Nodes), oci.Pending)

	pending := assuranceClusterInfoNode(t, true)
	pci := pending.getClusterInfo()
	fmt.Printf("CA_EVENT {\"event\":\"pending_record\",\"node_config_is_witness\":%t,\"reported_is_witness\":%t,\"pending\":%t,\"config_index\":%d}\n",
		pending.isWitness(), pci.IsWitness, pci.Pending, pci.ConfigChangeIndex)
}
