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

// A node must persist its term and vote and must not grant a second, different
// vote in the same term after a crash-restart.
func TestAuditVoteSurvivesRestart(t *testing.T) {
	peers := []PeerAddress{
		{NodeID: 1, Address: "a1"},
		{NodeID: 2, Address: "a2"},
		{NodeID: 3, Address: "a3"},
	}
	cfg := newTestConfig(1, 10, 1)
	logdb := NewTestLogDB()
	p := Launch(cfg, logdb, nil, peers, true, true)
	p.NotifyRaftLastApplied(3)
	for i := 0; i < 30 && p.raft.state != candidate; i++ {
		p.Tick()
	}
	if p.raft.state != candidate {
		t.Fatalf("expected candidate, got %v", p.raft.state)
	}
	if p.raft.vote != p.raft.nodeID {
		t.Fatalf("candidate did not vote for itself")
	}
	ud := p.GetUpdate(false, 0)
	if err := logdb.Append(ud.EntriesToSave); err != nil {
		t.Fatalf("append: %v", err)
	}
	logdb.SetState(ud.State)
	p.Commit(ud)
	term, vote := p.raft.term, p.raft.vote

	p2 := Launch(cfg, logdb, nil, peers, false, false)
	if p2.raft.term != term || p2.raft.vote != vote {
		t.Fatalf("restart lost vote: term %d vote %d, want term %d vote %d",
			p2.raft.term, p2.raft.vote, term, vote)
	}
	p2.Handle(pb.Message{
		Type:     pb.RequestVote,
		From:     2,
		Term:     term,
		LogIndex: 100,
		LogTerm:  term,
	})
	var resp *pb.Message
	for i := range p2.raft.msgs {
		if p2.raft.msgs[i].Type == pb.RequestVoteResp {
			resp = &p2.raft.msgs[i]
		}
	}
	if resp == nil {
		t.Fatalf("no RequestVoteResp sent")
	}
	if !resp.Reject {
		t.Fatalf("node granted a second vote in term %d (voted for %d, granted %d)",
			term, vote, 2)
	}
}

// Peer.HasUpdate reports a pending update when a read index was dropped, but
// pb.Update.HasUpdate ignores DroppedReadIndexes, so the same state is
// described differently by the two layers.
func TestAuditUpdateHasUpdateWithDroppedReadIndexes(t *testing.T) {
	peers := []PeerAddress{
		{NodeID: 1, Address: "a1"},
		{NodeID: 2, Address: "a2"},
		{NodeID: 3, Address: "a3"},
	}
	p := Launch(newTestConfig(1, 10, 1), NewTestLogDB(), nil, peers, true, true)
	p.NotifyRaftLastApplied(3)
	for i := 0; i < 30 && p.raft.state != candidate; i++ {
		p.Tick()
	}
	if p.raft.state != candidate {
		t.Fatalf("expected candidate, got %v", p.raft.state)
	}
	// drain any update produced so far
	drained := p.GetUpdate(false, 0)
	if err := p.entryLog().logdb.Append(drained.EntriesToSave); err != nil {
		t.Fatalf("%v", err)
	}
	p.Commit(drained)
	p.Handle(pb.Message{Type: pb.ReadIndex, From: 2, Hint: 1, HintHigh: 2})
	if !p.HasUpdate(false) {
		t.Fatalf("Peer.HasUpdate() should report the dropped read index")
	}
	ud := p.GetUpdate(false, 0)
	if len(ud.DroppedReadIndexes) == 0 {
		t.Fatalf("expected dropped read indexes in the update")
	}
	if !ud.HasUpdate() {
		t.Fatalf("pb.Update.HasUpdate() reported false for an update carrying %d "+
			"dropped read index(es)", len(ud.DroppedReadIndexes))
	}
}
