package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	pb "go.etcd.io/raft/v3/raftpb"
)

// caEvent emits a single machine-parsable event line.
func caEvent(t *testing.T, v map[string]any) {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceReadIndexPendingGrowth drives a real leader that cannot obtain
// quorum acknowledgements (no MsgAppResp / MsgHeartbeatResp is ever delivered)
// and retries ReadIndex with the same RequestCtx.
func TestAssuranceReadIndexPendingGrowth(t *testing.T) {
	r := newTestRaft(1, 3, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r.becomeCandidate()
	r.becomeLeader()
	caEvent(t, map[string]any{
		"event":          "read_growth_setup",
		"alias":          "isolated_leader",
		"state":          r.state.String(),
		"term":           r.Term,
		"committed":      r.raftLog.committed,
		"last_index":     r.raftLog.lastIndex(),
		"check_quorum":   r.checkQuorum,
		"read_only_safe": r.readOnly.option == ReadOnlySafe,
		"voter_count":    len(r.trk.Voters.IDs()),
	})

	rounds := 64
	ctx := []byte("same-ctx")
	for i := 0; i < rounds; i++ {
		_ = r.Step(&pb.Message{Type: pb.MsgReadIndex.Enum(), Entries: []*pb.Entry{{Data: ctx}}})
		// Drop outbound traffic so growth is measured in raft state, not in msgs.
		r.msgs = nil
		r.msgsAfterAppend = nil
	}
	caEvent(t, map[string]any{
		"event":       "read_growth_probe",
		"alias":       "isolated_leader",
		"rounds":      rounds,
		"pending":     len(r.pendingReadIndexMessages),
		"unconfirmed": len(r.readOnly.unconfirmedReads),
		"state_after": r.state.String(),
	})

	// A higher-term heartbeat deposes the node; the queued duty is not cleared.
	_ = r.Step(&pb.Message{From: new(uint64(2)), Term: new(r.Term + 1), Type: pb.MsgHeartbeat.Enum()})
	caEvent(t, map[string]any{
		"event":             "read_growth_after_stepdown",
		"alias":             "isolated_leader",
		"state_after":       r.state.String(),
		"pending_after":     len(r.pendingReadIndexMessages),
		"unconfirmed_after": len(r.readOnly.unconfirmedReads),
	})
}
