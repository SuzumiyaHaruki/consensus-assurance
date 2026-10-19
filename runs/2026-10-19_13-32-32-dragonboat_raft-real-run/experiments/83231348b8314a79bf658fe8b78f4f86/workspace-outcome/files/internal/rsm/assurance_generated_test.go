package rsm

import (
	"fmt"
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

// TestAssuranceMembershipEligibilityMatrix probes the membership acceptance
// rules that decide whose support counts in a configuration.
func TestAssuranceMembershipEligibilityMatrix(t *testing.T) {
	m := newMembership(1, 1, true)
	step := func(name string, cc pb.ConfigChange) {
		accepted := m.handleConfigChange(cc, 1)
		fmt.Printf("CA_EVENT {\"event\":\"cc\",\"case\":%q,\"accepted\":%t}\n", name, accepted)
	}
	step("add-node-a", pb.ConfigChange{Type: pb.AddNode, NodeID: 2, Address: "a", ConfigChangeId: 1})
	step("add-node-a-again", pb.ConfigChange{Type: pb.AddNode, NodeID: 2, Address: "a", ConfigChangeId: 2})
	step("add-observer-b", pb.ConfigChange{Type: pb.AddObserver, NodeID: 3, Address: "b", ConfigChangeId: 3})
	step("promote-b-same-addr", pb.ConfigChange{Type: pb.AddNode, NodeID: 3, Address: "b", ConfigChangeId: 4})
	step("add-observer-c-dup-addr", pb.ConfigChange{Type: pb.AddObserver, NodeID: 4, Address: "b", ConfigChangeId: 5})
	step("add-witness-w", pb.ConfigChange{Type: pb.AddWitness, NodeID: 5, Address: "w", ConfigChangeId: 6})
	step("witness-as-observer", pb.ConfigChange{Type: pb.AddObserver, NodeID: 5, Address: "w", ConfigChangeId: 7})
	step("witness-as-node", pb.ConfigChange{Type: pb.AddNode, NodeID: 5, Address: "w", ConfigChangeId: 8})
	step("remove-a", pb.ConfigChange{Type: pb.RemoveNode, NodeID: 2, ConfigChangeId: 9})
	step("readd-removed-a", pb.ConfigChange{Type: pb.AddNode, NodeID: 2, Address: "a", ConfigChangeId: 10})
	step("remove-b", pb.ConfigChange{Type: pb.RemoveNode, NodeID: 3, ConfigChangeId: 11})
	step("remove-w", pb.ConfigChange{Type: pb.RemoveNode, NodeID: 5, ConfigChangeId: 12})
	step("remove-only-node", pb.ConfigChange{Type: pb.RemoveNode, NodeID: 1, ConfigChangeId: 13})
}
