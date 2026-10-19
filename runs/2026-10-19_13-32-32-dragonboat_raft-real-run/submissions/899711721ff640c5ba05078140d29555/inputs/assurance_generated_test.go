package dragonboat

import (
	"fmt"
	"sync"
	"testing"
)

// TestAssuranceReadIndexDeadlineTimeout exercises the node-layer completion of a
// read request whose context was never indexed: the request is registered in a
// read batch with no ready-to-read index, the logical clock passes the caller
// deadline, and an event-loop iteration calls applied.
func TestAssuranceReadIndexDeadlineTimeout(t *testing.T) {
	pool := &sync.Pool{New: func() interface{} { return &RequestState{} }}
	q := newReadIndexQueue(16)
	p := newPendingReadIndex(pool, q)
	req, err := p.read(5)
	if err != nil {
		t.Fatalf("read registration failed: %v", err)
	}
	reqs := q.get()
	if len(reqs) != 1 {
		t.Fatalf("unexpected read queue size: %d", len(reqs))
	}
	ctx := p.nextCtx()
	p.add(ctx, reqs)
	p.tick(6)
	p.applied(0)
	select {
	case r := <-req.CompletedC:
		fmt.Printf("CA_EVENT {\"event\":\"result\",\"code\":\"%s\"}\n", r.code)
		if r.code != requestTimeout {
			t.Fatalf("expected timeout, got %s", r.code)
		}
	default:
		fmt.Printf("CA_EVENT {\"event\":\"result\",\"code\":\"none\"}\n")
		t.Fatalf("no terminal result delivered")
	}
}
