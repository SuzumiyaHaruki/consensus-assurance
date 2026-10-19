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

// The duplicate also reaches the exported Peer.GetUpdate boundary, which is
// what the node layer (and any root-package test) consumes.
func TestAuditPeerUpdateDroppedReadIndexes(t *testing.T) {
	logdb := NewTestLogDB()
	peers := []PeerAddress{
		{NodeID: 1, Address: "a1"},
		{NodeID: 2, Address: "a2"},
		{NodeID: 3, Address: "a3"},
	}
	p := Launch(newTestConfig(1, 10, 1), logdb, nil, peers, true, true)
	// the bootstrap config entries are committed; pretend the RSM applied them
	// so that the node is allowed to campaign
	p.NotifyRaftLastApplied(3)
	for i := 0; i < 30; i++ {
		p.Tick()
	}
	if p.raft.state != candidate {
		t.Fatalf("expected candidate state, got %v", p.raft.state)
	}
	p.Handle(pb.Message{Type: pb.ReadIndex, From: 2, Hint: 11, HintHigh: 22})
	ud := p.GetUpdate(false, 0)
	if len(ud.DroppedReadIndexes) != 1 {
		t.Fatalf("one dropped ReadIndex produced %d records in pb.Update: %+v",
			len(ud.DroppedReadIndexes), ud.DroppedReadIndexes)
	}
}
