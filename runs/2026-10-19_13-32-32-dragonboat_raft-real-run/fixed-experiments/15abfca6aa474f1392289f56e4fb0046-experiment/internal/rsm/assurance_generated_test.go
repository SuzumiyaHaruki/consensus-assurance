package rsm

import (
	"fmt"
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

// TestAssuranceMembershipEligibilityMatrix probes the membership acceptance
// rules. Ordered config changes require ConfigChangeId to equal the id of the
// last accepted change, which starts at zero and becomes the accepted entry
// index, so the harness tracks it.
func TestAssuranceMembershipEligibilityMatrix(t *testing.T) {
	m := newMembership(1, 1, true)
	last := uint64(0)
	var index uint64
	step := func(name string, cc pb.ConfigChange) {
		index++
		cc.ConfigChangeId = last
		accepted := m.handleConfigChange(cc, index)
		if accepted {
			last = index
		}
		fmt.Printf("CA_EVENT {\"event\":\"cc\",\"case\":%q,\"accepted\":%t,\"ccid\":%d,\"index\":%d}\n",
			name, accepted, cc.ConfigChangeId, index)
	}
	step("add-node-a", pb.ConfigChange{Type: pb.AddNode, NodeID: 2, Address: "a"})
	step("add-node-a-again", pb.ConfigChange{Type: pb.AddNode, NodeID: 2, Address: "a"})
	step("add-observer-b", pb.ConfigChange{Type: pb.AddObserver, NodeID: 3, Address: "b"})
	step("promote-b-same-addr", pb.ConfigChange{Type: pb.AddNode, NodeID: 3, Address: "b"})
	step("add-observer-c-dup-addr", pb.ConfigChange{Type: pb.AddObserver, NodeID: 4, Address: "b"})
	step("add-witness-w", pb.ConfigChange{Type: pb.AddWitness, NodeID: 5, Address: "w"})
	step("witness-as-observer", pb.ConfigChange{Type: pb.AddObserver, NodeID: 5, Address: "w"})
	step("witness-as-node", pb.ConfigChange{Type: pb.AddNode, NodeID: 5, Address: "w"})
	step("remove-a", pb.ConfigChange{Type: pb.RemoveNode, NodeID: 2})
	step("readd-removed-a", pb.ConfigChange{Type: pb.AddNode, NodeID: 2, Address: "a"})
	step("remove-b", pb.ConfigChange{Type: pb.RemoveNode, NodeID: 3})
	step("remove-w", pb.ConfigChange{Type: pb.RemoveNode, NodeID: 5})
	step("remove-only-node", pb.ConfigChange{Type: pb.RemoveNode, NodeID: 1})
}
