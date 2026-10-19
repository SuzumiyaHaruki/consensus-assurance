//go:build dragonboat_audit

// Audit-only reproduction tests. These files are not part of the captured
// implementation; they only exercise it. Delete before any upstream diff.
// Run with: -tags dragonboat_no_rocksdb,dragonboat_audit

package raft

import (
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

// newAuditFollowerWithCommittedLog returns a follower at term 4 whose log holds
// entries 1..3 at term 4, with entries 1..2 committed. Any peer that has seen
// the cluster's traffic knows these index/term pairs; they are not secrets.
func newAuditFollowerWithCommittedLog() *raft {
	r := newTestRaft(1, []uint64{1, 2, 3}, 10, 1, NewTestLogDB())
	r.becomeFollower(4, 2)
	r.log.append([]pb.Entry{
		{Index: 1, Term: 4, Type: pb.ApplicationEntry},
		{Index: 2, Term: 4, Type: pb.ApplicationEntry},
		{Index: 3, Term: 4, Type: pb.ApplicationEntry},
	})
	r.log.commitTo(2)
	return r
}

// auditPanic runs f and returns the value it panicked with, if any.
func auditPanic(f func()) (v interface{}) {
	defer func() { v = recover() }()
	f()
	return nil
}

// A Replicate message is peer input arriving over the transport. Nothing
// validates that Entries[i].Index == LogIndex+1+i, so a peer (or anyone who can
// guess the deployment ID) can send an entry that claims an index inside the
// committed region with a different term. entryLog.getConflictIndex returns
// that index, entryLog.tryAppend sees conflictIndex <= committed and calls
// plog.Panicf("entry %d conflicts with committed entry..."). In a running
// NodeHost this panic happens on the exec-engine step worker, which only
// recovers when error injection is enabled, so the process dies.
func TestAuditForgedReplicateCannotPanicOnCommittedConflict(t *testing.T) {
	r := newAuditFollowerWithCommittedLog()
	v := auditPanic(func() {
		r.Handle(pb.Message{
			Type:     pb.Replicate,
			From:     2,
			To:       1,
			Term:     4,
			LogIndex: 2, // equals committed; anchor term matches
			LogTerm:  4,
			Entries: []pb.Entry{
				// claims to be the already-committed entry 1, but at term 9
				{Index: 1, Term: 9, Type: pb.ApplicationEntry},
			},
		})
	})
	if v != nil {
		t.Fatalf("forged Replicate panicked: %v", v)
	}
}

// The same missing validation also lets a peer install a non-contiguous log:
// entries 4 and 9 are accepted with LogIndex 3, the log silently ends up with
// indices 1,2,3,4,9 and committed=5 (the last index is computed as
// LogIndex+len(Entries), not from the entries themselves). Applying the
// committed region then has to materialise an entry that does not exist.
func TestAuditForgedReplicateCannotCreateLogHole(t *testing.T) {
	r := newAuditFollowerWithCommittedLog()
	v := auditPanic(func() {
		r.Handle(pb.Message{
			Type:     pb.Replicate,
			From:     2,
			To:       1,
			Term:     4,
			LogIndex: 3,
			LogTerm:  4,
			Entries: []pb.Entry{
				{Index: 4, Term: 4, Type: pb.ApplicationEntry},
				{Index: 9, Term: 4, Type: pb.ApplicationEntry},
			},
		})
	})
	if v != nil {
		t.Fatalf("forged Replicate installed an unreadable log: %v", v)
	}
	first, last := r.log.firstIndex(), r.log.lastIndex()
	var ents []pb.Entry
	var err error
	v = auditPanic(func() {
		ents, err = r.log.getEntries(first, last+1, maxEntriesToApplySize)
	})
	if v != nil {
		t.Fatalf("forged Replicate installed an unreadable log: %v", v)
	}
	if err != nil {
		t.Fatalf("log unreadable after forged Replicate: %v", err)
	}
	if uint64(len(ents)) != last-first+1 {
		idx := make([]uint64, 0, len(ents))
		for _, e := range ents {
			idx = append(idx, e.Index)
		}
		t.Fatalf("forged Replicate installed a non-contiguous log: "+
			"range %d..%d, entries %v, committed %d",
			first, last, idx, r.log.committed)
	}
}

// Control: a well formed Replicate must still be accepted and committed.
func TestAuditWellFormedReplicateStillAccepted(t *testing.T) {
	r := newAuditFollowerWithCommittedLog()
	r.Handle(pb.Message{
		Type:     pb.Replicate,
		From:     2,
		To:       1,
		Term:     4,
		LogIndex: 3,
		LogTerm:  4,
		Commit:   4,
		Entries: []pb.Entry{
			{Index: 4, Term: 4, Type: pb.ApplicationEntry},
		},
	})
	if r.log.lastIndex() != 4 || r.log.committed != 4 {
		t.Fatalf("valid Replicate not applied: lastIndex %d, committed %d",
			r.log.lastIndex(), r.log.committed)
	}
}
