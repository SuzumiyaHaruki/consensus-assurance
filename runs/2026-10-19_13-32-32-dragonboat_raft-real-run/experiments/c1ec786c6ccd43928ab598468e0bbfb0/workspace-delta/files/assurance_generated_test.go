package dragonboat

import (
	"fmt"
	"testing"

	"github.com/lni/dragonboat/v3/internal/rsm"
)

// TestAssuranceSnapshotRequestOutcome probes the completion contract of a
// user-requested snapshot: a request that is never reported back is expected to
// end with a timeout once the logical clock passes its deadline, after which the
// object accepts a new request that can be completed normally.
func TestAssuranceSnapshotRequestOutcome(t *testing.T) {
	errName := func(err error) string {
		if err == nil {
			return "nil"
		}
		return err.Error()
	}
	snapshotC := make(chan rsm.SSRequest, 4)
	p := newPendingSnapshot(snapshotC)

	req, err := p.request(rsm.UserRequested, "", false, 0, 5)
	fmt.Printf("CA_EVENT {\"event\":\"snapshot_request\",\"case\":\"expired\",\"err\":%q,\"queued\":%d,\"state_returned\":%t}\n",
		errName(err), len(snapshotC), req != nil)
	if req != nil {
		select {
		case r := <-req.CompletedC:
			fmt.Printf("CA_EVENT {\"event\":\"snapshot_early\",\"got\":%q}\n", r.code.String())
		default:
			fmt.Printf("CA_EVENT {\"event\":\"snapshot_early\",\"got\":\"none\"}\n")
		}
		p.tick(20)
		p.gc()
		select {
		case r := <-req.CompletedC:
			fmt.Printf("CA_EVENT {\"event\":\"snapshot_expired\",\"got\":%q,\"result_value\":%d}\n",
				r.code.String(), r.result.Value)
		default:
			fmt.Printf("CA_EVENT {\"event\":\"snapshot_expired\",\"got\":\"none\"}\n")
		}
	}

	req2, err := p.request(rsm.UserRequested, "", false, 0, 5)
	fmt.Printf("CA_EVENT {\"event\":\"snapshot_request\",\"case\":\"completed\",\"err\":%q,\"queued\":%d,\"state_returned\":%t}\n",
		errName(err), len(snapshotC), req2 != nil)
	if req2 != nil {
		var key uint64
		stale := 0
		for {
			select {
			case ssreq := <-snapshotC:
				if ssreq.Key == req2.key {
					key = ssreq.Key
				} else {
					stale++
				}
				continue
			default:
			}
			break
		}
		matched := key != 0 && key == req2.key
		p.apply(key, false, false, 42)
		select {
		case r := <-req2.CompletedC:
			fmt.Printf("CA_EVENT {\"event\":\"snapshot_completed\",\"key_matched\":%t,\"stale_requests\":%d,\"got\":%q,\"result_value\":%d}\n",
				matched, stale, r.code.String(), r.result.Value)
		default:
			fmt.Printf("CA_EVENT {\"event\":\"snapshot_completed\",\"key_matched\":%t,\"stale_requests\":%d,\"got\":\"none\"}\n",
				matched, stale)
		}
	}

	_, err = p.request(rsm.UserRequested, "", false, 0, 0)
	fmt.Printf("CA_EVENT {\"event\":\"snapshot_request\",\"case\":\"zero_timeout\",\"err\":%q}\n", errName(err))
}
