package raft

import (
	"fmt"
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

// TestAssuranceFastApplySelection probes the selector the engine uses to decide
// whether an update's committed entries may be offered to the state machine
// before the round's log write, or only after it. Each case builds an update
// directly and asks setFastApply which pass it belongs to.
func TestAssuranceFastApplySelection(t *testing.T) {
	report := func(name string, ud pb.Update) {
		firstSave := uint64(0)
		lastSave := uint64(0)
		if len(ud.EntriesToSave) > 0 {
			firstSave = ud.EntriesToSave[0].Index
			lastSave = ud.EntriesToSave[len(ud.EntriesToSave)-1].Index
		}
		lastApply := uint64(0)
		if len(ud.CommittedEntries) > 0 {
			lastApply = ud.CommittedEntries[len(ud.CommittedEntries)-1].Index
		}
		out := setFastApply(ud)
		fmt.Printf("CA_EVENT {\"event\":\"fast_apply\",\"case\":%q,\"fast_apply\":%t,\"first_save\":%d,\"last_save\":%d,\"last_apply\":%d,\"snapshot_index\":%d}\n",
			name, out.FastApply, firstSave, lastSave, lastApply, ud.Snapshot.Index)
	}

	report("apply_covers_save_range", pb.Update{
		EntriesToSave:    []pb.Entry{{Index: 1, Term: 1}, {Index: 2, Term: 1}},
		CommittedEntries: []pb.Entry{{Index: 1, Term: 1}, {Index: 2, Term: 1}},
	})
	report("apply_tail_inside_save_range", pb.Update{
		EntriesToSave:    []pb.Entry{{Index: 3, Term: 2}, {Index: 4, Term: 2}},
		CommittedEntries: []pb.Entry{{Index: 1, Term: 1}, {Index: 2, Term: 1}, {Index: 3, Term: 2}},
	})
	report("apply_strictly_below_save_range", pb.Update{
		EntriesToSave:    []pb.Entry{{Index: 5, Term: 2}, {Index: 6, Term: 2}},
		CommittedEntries: []pb.Entry{{Index: 3, Term: 1}, {Index: 4, Term: 1}},
	})
	report("snapshot_install", pb.Update{
		Snapshot:         pb.Snapshot{Index: 5, Term: 2},
		CommittedEntries: []pb.Entry{{Index: 3, Term: 1}, {Index: 4, Term: 1}},
	})
	report("apply_only", pb.Update{
		CommittedEntries: []pb.Entry{{Index: 3, Term: 1}, {Index: 4, Term: 1}},
	})
	report("save_only", pb.Update{
		EntriesToSave: []pb.Entry{{Index: 5, Term: 2}, {Index: 6, Term: 2}},
	})
}
