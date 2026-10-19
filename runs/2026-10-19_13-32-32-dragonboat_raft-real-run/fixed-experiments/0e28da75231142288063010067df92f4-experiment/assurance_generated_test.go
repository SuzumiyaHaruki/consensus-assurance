package dragonboat

import (
	"fmt"
	"sync"
	"testing"

	"github.com/lni/goutils/random"

	"github.com/lni/dragonboat/v3/client"
	"github.com/lni/dragonboat/v3/config"
	sm "github.com/lni/dragonboat/v3/statemachine"
)

// TestAssuranceNotifyCommitContract probes the two-phase ResultC contract for a
// proposal with commit notification enabled, and the terminal result for a
// proposal that passes its deadline before being applied.
func TestAssuranceNotifyCommitContract(t *testing.T) {
	cfg := config.Config{ClusterID: 1, NodeID: 1}
	q := newEntryQueue(8, 0)
	pool := &sync.Pool{New: func() interface{} { return &RequestState{} }}
	p := newPendingProposal(cfg, true, pool, q)
	s := client.NewNoOPSession(1, random.LockGuardedRand)

	req, err := p.propose(s, []byte("data"), 5)
	if err != nil {
		t.Fatalf("propose failed: %v", err)
	}
	key := req.key
	p.committed(s.ClientID, s.SeriesID, key)
	select {
	case r := <-req.committedC:
		fmt.Printf("CA_EVENT {\"event\":\"phase\",\"got\":%q}\n", r.code.String())
	default:
		fmt.Printf("CA_EVENT {\"event\":\"phase\",\"got\":\"none\"}\n")
	}
	p.applied(s.ClientID, s.SeriesID, key, sm.Result{Value: 7}, false)
	select {
	case r := <-req.CompletedC:
		fmt.Printf("CA_EVENT {\"event\":\"applied\",\"got\":%q}\n", r.code.String())
	default:
		fmt.Printf("CA_EVENT {\"event\":\"applied\",\"got\":\"none\"}\n")
	}

	req2, err := p.propose(s, []byte("late"), 3)
	if err != nil {
		t.Fatalf("second propose failed: %v", err)
	}
	p.tick(10)
	p.applied(s.ClientID, s.SeriesID, req2.key, sm.Result{Value: 8}, false)
	select {
	case r := <-req2.CompletedC:
		fmt.Printf("CA_EVENT {\"event\":\"late\",\"got\":%q}\n", r.code.String())
	default:
		fmt.Printf("CA_EVENT {\"event\":\"late\",\"got\":\"none\"}\n")
	}
	select {
	case <-req2.committedC:
		fmt.Printf("CA_EVENT {\"event\":\"late_commit\",\"got\":\"value\"}\n")
	default:
		fmt.Printf("CA_EVENT {\"event\":\"late_commit\",\"got\":\"none\"}\n")
	}
}
