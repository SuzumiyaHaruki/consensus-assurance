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

// TestAssuranceReadIndexIsolatedNetwork exercises the retry-growth trigger over
// a real three-node network: the leader is partitioned from both followers and
// then accepts same-context ReadIndex requests.
func TestAssuranceReadIndexIsolatedNetwork(t *testing.T) {
	nt := newNetwork(nil, nil, nil)
	nt.send(&pb.Message{From: new(uint64(1)), To: new(uint64(1)), Type: pb.MsgHup.Enum()})
	lead := nt.peers[1].(*raft)
	caEvent(t, map[string]any{
		"event":           "net_setup",
		"alias":           "isolated_leader_net",
		"state":           lead.state.String(),
		"id":              lead.id,
		"committed":       lead.raftLog.committed,
		"in_term":         lead.committedEntryInCurrentTerm(),
		"check_quorum":    lead.checkQuorum,
		"read_only_safe":  lead.readOnly.option == ReadOnlySafe,
		"voter_count":     len(lead.trk.Voters.IDs()),
	})

	nt.isolate(2)
	nt.isolate(3)
	lead.msgs, lead.msgsAfterAppend = nil, nil

	ctx := []byte("same-ctx")
	rounds := 32
	broadcasts := 0
	for i := 0; i < rounds; i++ {
		_ = lead.Step(&pb.Message{Type: pb.MsgReadIndex.Enum(), Entries: []*pb.Entry{{Data: ctx}}})
		for _, m := range lead.msgs {
			if m.GetType() == pb.MsgHeartbeat {
				broadcasts++
			}
		}
		lead.msgs, lead.msgsAfterAppend = nil, nil
	}
	caEvent(t, map[string]any{
		"event":       "net_probe",
		"alias":       "isolated_leader_net",
		"rounds":      rounds,
		"unconfirmed": len(lead.readOnly.unconfirmedReads),
		"broadcasts":  broadcasts,
		"pending":     len(lead.pendingReadIndexMessages),
		"confirmed":   lead.readOnly.confirmedReads,
		"state_after": lead.state.String(),
	})
}
