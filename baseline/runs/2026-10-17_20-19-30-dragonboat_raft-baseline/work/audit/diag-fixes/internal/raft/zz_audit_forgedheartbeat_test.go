//go:build dragonboat_audit

// Audit-only reproduction tests. These files are not part of the captured
// implementation; they only exercise it. Delete before any upstream diff.
// Run with: -tags dragonboat_no_rocksdb,dragonboat_audit

package raft

import (
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

// handleHeartbeatMessage passes the leader's Commit value straight to
// entryLog.commitTo, which panics when the value is beyond the follower's
// last index. The Replicate path clamps with min(lastIdx, m.Commit); the
// heartbeat path does not. A single heartbeat is enough, and nothing has to
// match beyond the term, so this is cheaper for a peer to trigger than the
// forged Replicate in Finding 10.
func TestAuditForgedHeartbeatCannotPanic(t *testing.T) {
	r := newAuditFollowerWithCommittedLog() // log 1..3 at term 4, committed 2
	v := auditPanic(func() {
		r.Handle(pb.Message{
			Type:   pb.Heartbeat,
			From:   2,
			To:     1,
			Term:   4,
			Commit: 1000000,
		})
	})
	if v != nil {
		t.Fatalf("forged Heartbeat panicked: %v", v)
	}
	if r.log.committed != 3 {
		t.Fatalf("committed advanced to %d, want it clamped to lastIndex 3",
			r.log.committed)
	}
}

// Control: a heartbeat whose Commit is within the log still advances it.
func TestAuditHeartbeatStillCommits(t *testing.T) {
	r := newAuditFollowerWithCommittedLog()
	r.Handle(pb.Message{
		Type:   pb.Heartbeat,
		From:   2,
		To:     1,
		Term:   4,
		Commit: 3,
	})
	if r.log.committed != 3 {
		t.Fatalf("committed %d, want 3", r.log.committed)
	}
	msgs := r.readMessages()
	if len(msgs) != 1 || msgs[0].Type != pb.HeartbeatResp {
		t.Fatalf("unexpected response %+v", msgs)
	}
}
