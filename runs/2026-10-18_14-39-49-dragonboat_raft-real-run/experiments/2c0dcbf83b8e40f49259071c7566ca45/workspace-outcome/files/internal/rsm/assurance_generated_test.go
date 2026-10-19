package rsm

import (
	"encoding/json"
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

func emitPromotionAssuranceEvent(t *testing.T, event map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("failed to marshal assurance event: %v", err)
	}
	t.Logf("CA_EVENT %s", b)
}

func TestAssuranceObserverPromotionTargets(t *testing.T) {
	cases := []struct {
		id   string
		kind string
		addr string
		want bool
	}{
		{id: "promote-matching", kind: "matching", addr: "a2", want: true},
		{id: "promote-different", kind: "different", addr: "a3", want: false},
		{id: "promote-empty", kind: "empty", addr: "", want: false},
	}
	for _, tc := range cases {
		m := newMembership(1, 2, true)
		m.members.Observers[100] = "a2"
		emitPromotionAssuranceEvent(t, map[string]interface{}{
			"event":             "promotion_target_requested",
			"request_id":        tc.id,
			"node_id":           uint64(100),
			"target_kind":       tc.kind,
			"target":            tc.addr,
			"expected":          tc.want,
			"expected_retained": !tc.want,
		})
		accepted := m.handleConfigChange(pb.ConfigChange{
			Type:    pb.AddNode,
			NodeID:  100,
			Address: tc.addr,
		}, 1000)
		_, stillObserver := m.members.Observers[100]
		emitPromotionAssuranceEvent(t, map[string]interface{}{
			"event":                  "promotion_target_decision",
			"request_id":             tc.id,
			"target_kind":            tc.kind,
			"accepted":               accepted,
			"expected":               tc.want,
			"observer_role_retained": stillObserver,
		})
	}
}
