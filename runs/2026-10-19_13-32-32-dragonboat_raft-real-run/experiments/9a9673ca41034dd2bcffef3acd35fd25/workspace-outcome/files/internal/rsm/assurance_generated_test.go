package rsm

import (
	"fmt"
	"testing"

	sm "github.com/lni/dragonboat/v3/statemachine"
)

// TestAssuranceSessionEviction probes which client session the LRU manager
// keeps when the configured capacity is exceeded, and what a client whose
// session was evicted observes when it asks for its stored result.
func TestAssuranceSessionEviction(t *testing.T) {
	l := newLRUSession(2)
	for _, id := range []uint64{11, 22, 33} {
		l.addSession(RaftClientID(id), *newSession(RaftClientID(id)))
		s, ok := l.getSession(RaftClientID(id))
		if !ok {
			t.Fatalf("session %d missing right after add", id)
		}
		s.addResponse(1, sm.Result{Value: id})
	}
	for _, id := range []uint64{11, 22, 33} {
		s, ok := l.getSession(RaftClientID(id))
		kept := ok && s != nil
		var stored uint64
		if ok && s != nil {
			if v, has := s.getResponse(1); has {
				stored = v.Value
			}
		}
		fmt.Printf("CA_EVENT {\"event\":\"session\",\"client\":%d,\"kept\":%t,\"stored\":%d}\n", id, kept, stored)
	}
}
