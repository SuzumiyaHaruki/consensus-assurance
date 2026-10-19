package rsm

import (
	"fmt"
	"testing"

	sm "github.com/lni/dragonboat/v3/statemachine"
)

// TestAssuranceSessionExactlyOnce probes the session decision logic that
// prevents a retried proposal from updating the state machine twice.
func TestAssuranceSessionExactlyOnce(t *testing.T) {
	ds := NewSessionManager()
	ds.RegisterClientID(42)
	s, ok := ds.ClientRegistered(42)
	if !ok {
		t.Fatalf("session not registered")
	}
	ds.UpdateRespondedTo(s, 0)
	_, responded, toUpdate := ds.UpdateRequired(s, 1)
	fmt.Printf("CA_EVENT {\"event\":\"first\",\"responded\":%t,\"update\":%t}\n", responded, toUpdate)
	ds.AddResponse(s, 1, sm.Result{Value: 9})
	v, responded, toUpdate := ds.UpdateRequired(s, 1)
	fmt.Printf("CA_EVENT {\"event\":\"retry_unacked\",\"responded\":%t,\"update\":%t,\"stored\":%d}\n", responded, toUpdate, v.Value)
	ds.UpdateRespondedTo(s, 1)
	_, responded, toUpdate = ds.UpdateRequired(s, 1)
	fmt.Printf("CA_EVENT {\"event\":\"retry_acked\",\"responded\":%t,\"update\":%t}\n", responded, toUpdate)
}
