//go:build dragonboat_audit

// Audit-only reproduction tests. These files are not part of the captured
// implementation; they only exercise it. Delete before any upstream diff.
// Run with: -tags dragonboat_no_rocksdb,dragonboat_audit

package raft

import (
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

// A ReadIndex request received by a candidate has no leader to forward it to,
// so the request must be reported as dropped exactly once. The analogous
// proposal path (handleCandidatePropose -> reportDroppedProposal) records one
// entry per dropped proposal entry.
func TestAuditCandidateReadIndexIsDroppedOnce(t *testing.T) {
	r := newTestRaft(1, []uint64{1, 2, 3}, 10, 1, NewTestLogDB())
	r.becomeCandidate()
	r.droppedReadIndexes = nil

	r.Handle(pb.Message{
		Type:     pb.ReadIndex,
		From:     2,
		Hint:     0x1234,
		HintHigh: 0x5678,
	})

	if len(r.droppedReadIndexes) != 1 {
		t.Fatalf("one dropped ReadIndex request produced %d records: %+v",
			len(r.droppedReadIndexes), r.droppedReadIndexes)
	}
}

// Control: a dropped proposal is recorded exactly once.
func TestAuditCandidateProposalIsDroppedOnce(t *testing.T) {
	r := newTestRaft(1, []uint64{1, 2, 3}, 10, 1, NewTestLogDB())
	r.becomeCandidate()
	r.droppedEntries = nil

	r.Handle(pb.Message{
		Type:    pb.Propose,
		From:    1,
		Entries: []pb.Entry{{Type: pb.ApplicationEntry, Cmd: []byte("x")}},
	})

	if len(r.droppedEntries) != 1 {
		t.Fatalf("one dropped proposal produced %d records", len(r.droppedEntries))
	}
}
