package rsm

import (
	"fmt"
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

// TestAssuranceRemoveNonMember probes removal of a node identity that is not in
// a realistic configuration, and whether that identity can still be added.
func TestAssuranceRemoveNonMember(t *testing.T) {
	m := newMembership(1, 1, true)
	var last, index uint64
	step := func(name string, cc pb.ConfigChange) bool {
		index++
		cc.ConfigChangeId = last
		accepted := m.handleConfigChange(cc, index)
		if accepted {
			last = index
		}
		mm := m.get()
		fmt.Printf("CA_EVENT {\"event\":\"cc\",\"case\":%q,\"accepted\":%t,\"index\":%d,\"nodes\":%d,\"observers\":%d,\"witnesses\":%d,\"removed9\":%t}\n",
			name, accepted, index, len(mm.Addresses), len(mm.Observers), len(mm.Witnesses), mm.Removed[9])
		return accepted
	}
	step("add-node-1", pb.ConfigChange{Type: pb.AddNode, NodeID: 1, Address: "n1"})
	step("add-node-2", pb.ConfigChange{Type: pb.AddNode, NodeID: 2, Address: "n2"})
	step("remove-non-member-9", pb.ConfigChange{Type: pb.RemoveNode, NodeID: 9})
	step("add-node-9-after", pb.ConfigChange{Type: pb.AddNode, NodeID: 9, Address: "n9"})
}
