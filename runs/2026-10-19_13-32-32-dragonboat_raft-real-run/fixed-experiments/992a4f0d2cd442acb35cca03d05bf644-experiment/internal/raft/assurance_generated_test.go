package raft

import (
	"fmt"
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

// TestAssuranceSavedIndexAfterTruncation checks the in-memory saved-index
// accounting when a conflicting append replaces already-persisted entries.
func TestAssuranceSavedIndexAfterTruncation(t *testing.T) {
	l := newEntryLog(NewTestLogDB(), nil)
	l.append([]pb.Entry{
		{Index: 1, Term: 1}, {Index: 2, Term: 1}, {Index: 3, Term: 1}, {Index: 4, Term: 1},
	})
	l.commitUpdate(pb.UpdateCommit{StableLogTo: 4, StableLogTerm: 1})
	before := l.entriesToSave()
	l.tryAppend(2, []pb.Entry{{Index: 3, Term: 2}, {Index: 4, Term: 2}})
	after := l.entriesToSave()
	firstBefore := uint64(0)
	if len(before) > 0 {
		firstBefore = before[0].Index
	}
	firstAfter := uint64(0)
	if len(after) > 0 {
		firstAfter = after[0].Index
	}
	fmt.Printf("CA_EVENT {\"event\":\"save_range\",\"before_first\":%d,\"before_len\":%d,\"after_first\":%d,\"after_len\":%d,\"last_index\":%d,\"last_term\":%d}\n",
		firstBefore, len(before), firstAfter, len(after), l.lastIndex(), l.lastTerm())
}
