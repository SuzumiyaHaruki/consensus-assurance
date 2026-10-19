//go:build dragonboat_audit

// Audit-only check of the node-layer consequence of Finding 2: the duplicated
// DroppedReadIndexes record must not notify the client twice.

package dragonboat

import (
	"sync"
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

func TestAuditDroppedReadIndexIsIdempotent(t *testing.T) {
	pool := &sync.Pool{New: func() interface{} {
		return &RequestState{CompletedC: make(chan RequestResult, 1)}
	}}
	queue := newReadIndexQueue(16)
	pending := newPendingReadIndex(pool, queue)
	req := pool.Get().(*RequestState)
	ctx := pb.SystemCtx{Low: 1, High: 2}
	pending.add(ctx, []*RequestState{req})
	pending.dropped(ctx)
	pending.dropped(ctx) // the duplicate entry from the raft update
	if len(req.CompletedC) != 1 {
		t.Fatalf("expected exactly one notification, got %d", len(req.CompletedC))
	}
	if v := <-req.CompletedC; !v.Dropped() {
		t.Fatalf("expected a dropped result, got %v", v)
	}
	if len(req.CompletedC) != 0 {
		t.Fatalf("client notified more than once")
	}
}
