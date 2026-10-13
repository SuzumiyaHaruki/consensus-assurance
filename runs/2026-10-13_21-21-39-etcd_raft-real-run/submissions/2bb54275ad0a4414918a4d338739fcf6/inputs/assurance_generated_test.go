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

// TestAssuranceReadIndexAdmittedGrowth drives the admitted (not queued) path: a
// leader that has committed in its term but whose followers stop acknowledging
// heartbeats still admits every retried ReadIndex into unconfirmedReads and
// broadcasts a heartbeat per request.
func TestAssuranceReadIndexAdmittedGrowth(t *testing.T) {
	r := newTestRaft(1, 3, 1, newTestMemoryStorage(withPeers(1, 2)))
	r.becomeCandidate()
	r.becomeLeader()
	// Deliver the leader's own self-ack for the empty entry, then let node 2
	// acknowledge it, so the leader commits in its term.
	for _, m := range r.msgsAfterAppend {
		_ = r.Step(m)
	}
	_ = r.Step(&pb.Message{From: new(uint64(2)), Type: pb.MsgAppResp.Enum(), Index: new(r.raftLog.lastIndex())})
	r.msgs = nil
	r.msgsAfterAppend = nil
	caEvent(t, map[string]any{
		"event":          "read_admitted_setup",
		"alias":          "committed_no_acks",
		"state":          r.state.String(),
		"term":           r.Term,
		"committed":      r.raftLog.committed,
		"last_index":     r.raftLog.lastIndex(),
		"in_term":        r.committedEntryInCurrentTerm(),
		"check_quorum":   r.checkQuorum,
		"read_only_safe": r.readOnly.option == ReadOnlySafe,
		"voter_count":    len(r.trk.Voters.IDs()),
	})

	rounds := 64
	broadcasts := 0
	ctx := []byte("same-ctx")
	for i := 0; i < rounds; i++ {
		_ = r.Step(&pb.Message{Type: pb.MsgReadIndex.Enum(), Entries: []*pb.Entry{{Data: ctx}}})
		for _, m := range r.msgs {
			if m.GetType() == pb.MsgHeartbeat {
				broadcasts++
			}
		}
		r.msgs = nil
		r.msgsAfterAppend = nil
	}
	caEvent(t, map[string]any{
		"event":       "read_admitted_probe",
		"alias":       "committed_no_acks",
		"rounds":      rounds,
		"unconfirmed": len(r.readOnly.unconfirmedReads),
		"broadcasts":  broadcasts,
		"pending":     len(r.pendingReadIndexMessages),
		"confirmed":   r.readOnly.confirmedReads,
		"state_after": r.state.String(),
	})
}

// TestAssuranceReadIndexQueuedDrainBurst measures what happens when a leader
// that accumulated queued read requests finally commits in its term: the whole
// queue is released in one step, each entry re-admitted and rebroadcast.
func TestAssuranceReadIndexQueuedDrainBurst(t *testing.T) {
	r := newTestRaft(1, 3, 1, newTestMemoryStorage(withPeers(1, 2)))
	r.becomeCandidate()
	r.becomeLeader()
	r.msgs = nil
	r.msgsAfterAppend = nil

	rounds := 64
	ctx := []byte("same-ctx")
	for i := 0; i < rounds; i++ {
		_ = r.Step(&pb.Message{Type: pb.MsgReadIndex.Enum(), Entries: []*pb.Entry{{Data: ctx}}})
		r.msgs = nil
		r.msgsAfterAppend = nil
	}
	caEvent(t, map[string]any{
		"event":       "read_drain_setup",
		"alias":       "queued_then_commit",
		"rounds":      rounds,
		"pending":     len(r.pendingReadIndexMessages),
		"committed":   r.raftLog.committed,
		"in_term":     r.committedEntryInCurrentTerm(),
		"unconfirmed": len(r.readOnly.unconfirmedReads),
	})

	// Now let the leader commit in its term: its own ack, then node 2's ack for
	// the empty entry. The follower's MsgAppResp takes the leader fast path that
	// calls releasePendingReadIndexMessages.
	_ = r.Step(&pb.Message{From: new(uint64(1)), Type: pb.MsgAppResp.Enum(), Index: new(r.raftLog.lastIndex())})
	_ = r.Step(&pb.Message{From: new(uint64(2)), Type: pb.MsgAppResp.Enum(), Index: new(r.raftLog.lastIndex())})
	broadcasts := 0
	for _, m := range r.msgs {
		if m.GetType() == pb.MsgHeartbeat {
			broadcasts++
		}
	}
	caEvent(t, map[string]any{
		"event":       "read_drain_after_commit",
		"alias":       "queued_then_commit",
		"committed":   r.raftLog.committed,
		"in_term":     r.committedEntryInCurrentTerm(),
		"pending":     len(r.pendingReadIndexMessages),
		"unconfirmed": len(r.readOnly.unconfirmedReads),
		"broadcasts":  broadcasts,
		"state_after": r.state.String(),
	})
}

// TestAssuranceReadIndexGrowthWithCheckQuorum is the control for the growth
// claim: with CheckQuorum enabled the leader loses its quorum view within an
// election timeout, so growth should stop - but nothing reclaims what was
// already accumulated.
func TestAssuranceReadIndexGrowthWithCheckQuorum(t *testing.T) {
	cfg := newTestConfig(1, 3, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	cfg.CheckQuorum = true
	r := newRaft(cfg)
	r.becomeCandidate()
	r.becomeLeader()
	r.msgs = nil
	r.msgsAfterAppend = nil

	caEvent(t, map[string]any{
		"event":        "read_ckq_setup",
		"alias":        "check_quorum_on",
		"check_quorum": r.checkQuorum,
		"state":        r.state.String(),
		"election":     r.electionTimeout,
		"voter_count":  len(r.trk.Voters.IDs()),
	})

	ctx := []byte("same-ctx")
	rounds := 0
	for tick := 0; tick < 3 && r.state == StateLeader; tick++ {
		for i := 0; i < 8; i++ {
			_ = r.Step(&pb.Message{Type: pb.MsgReadIndex.Enum(), Entries: []*pb.Entry{{Data: ctx}}})
			rounds++
			r.msgs = nil
			r.msgsAfterAppend = nil
		}
		r.tick()
	}
	pendingBefore := len(r.pendingReadIndexMessages)
	caEvent(t, map[string]any{
		"event":           "read_ckq_before",
		"alias":           "check_quorum_on",
		"check_quorum":    true,
		"rounds":          rounds,
		"state":           r.state.String(),
		"window_closed":   r.state != StateLeader,
		"pending_before":  pendingBefore,
		"unconfirmed":     len(r.readOnly.unconfirmedReads),
		"voter_count":     len(r.trk.Voters.IDs()),
	})

	for i := 0; i < 8; i++ {
		_ = r.Step(&pb.Message{Type: pb.MsgReadIndex.Enum(), Entries: []*pb.Entry{{Data: ctx}}})
		r.msgs = nil
		r.msgsAfterAppend = nil
	}
	caEvent(t, map[string]any{
		"event":             "read_ckq_after",
		"alias":             "check_quorum_on",
		"state_after":       r.state.String(),
		"pending_before":    pendingBefore,
		"pending_after":     len(r.pendingReadIndexMessages),
		"pending_unchanged": len(r.pendingReadIndexMessages) == pendingBefore,
		"unconfirmed_after": len(r.readOnly.unconfirmedReads),
	})
}

// TestAssuranceReadIndexRetainedBytes measures how much caller-supplied payload
// the leader pins when many distinct read requests are accepted while it cannot
// obtain quorum acknowledgements. Each request carries its own RequestCtx
// buffer, as a caller issuing distinct reads would.
func TestAssuranceReadIndexRetainedBytes(t *testing.T) {
	r := newTestRaft(1, 3, 1, newTestMemoryStorage(withPeers(1, 2, 3)))
	r.becomeCandidate()
	r.becomeLeader()
	r.msgs = nil
	r.msgsAfterAppend = nil

	const ctxBytes = 4096
	const rounds = 64
	caEvent(t, map[string]any{
		"event":        "read_bytes_setup",
		"alias":        "retained_bytes",
		"check_quorum": r.checkQuorum,
		"state":        r.state.String(),
		"voter_count":  len(r.trk.Voters.IDs()),
		"ctx_bytes":    ctxBytes,
		"rounds":       rounds,
	})

	for i := 0; i < rounds; i++ {
		ctx := make([]byte, ctxBytes)
		copy(ctx, []byte("distinct-read-context"))
		_ = r.Step(&pb.Message{Type: pb.MsgReadIndex.Enum(), Entries: []*pb.Entry{{Data: ctx}}})
		r.msgs = nil
		r.msgsAfterAppend = nil
	}

	retained := 0
	distinct := map[*byte]struct{}{}
	for _, m := range r.pendingReadIndexMessages {
		for _, e := range m.GetEntries() {
			data := e.GetData()
			retained += len(data)
			if len(data) > 0 {
				distinct[&data[0]] = struct{}{}
			}
		}
	}
	caEvent(t, map[string]any{
		"event":               "read_bytes_probe",
		"alias":               "retained_bytes",
		"pending":             len(r.pendingReadIndexMessages),
		"retained_ctx_bytes":  retained,
		"distinct_ctx_buffers": len(distinct),
		"ctx_bytes":           ctxBytes,
		"rounds":              rounds,
		"state_after":         r.state.String(),
	})
}
