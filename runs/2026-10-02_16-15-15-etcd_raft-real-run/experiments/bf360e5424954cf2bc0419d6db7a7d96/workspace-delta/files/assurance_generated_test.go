package raft

import (
    "context"
    "encoding/json"
    "fmt"
    "testing"
    "time"

    pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssurancePendingConfigurationAdmission(t *testing.T) {
    for _, policy := range []string{"deferred_no_advance", "deferred_early_advance", "applied_then_advance"} {
        t.Run(policy, func(t *testing.T) {
            emit := func(v map[string]interface{}) {
                v["policy"] = policy
                v["op"] = "second-config-" + policy
                v["node"] = uint64(1)
                v["proposal_seq"] = 2
                b, err := json.Marshal(v)
                if err != nil { t.Fatal(err) }
                fmt.Println("CA_EVENT " + string(b))
            }
            ms := NewMemoryStorage()
            if err := ms.ApplySnapshot(pb.Snapshot{Metadata: pb.SnapshotMetadata{Index:1, Term:1,
                ConfState:pb.ConfState{Voters:[]uint64{1}}}}); err != nil { t.Fatal(err) }
            if err := ms.SetHardState(pb.HardState{Term:1, Commit:1}); err != nil { t.Fatal(err) }
            n := RestartNode(&Config{ID:1, ElectionTick:10, HeartbeatTick:1, Storage:ms,
                Applied:1, MaxSizePerMsg:1024*1024, MaxInflightMsgs:16})
            defer n.Stop()
            ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
            defer cancel()
            receive := func() Ready {
                select {
                case rd := <-n.Ready(): return rd
                case <-ctx.Done(): t.Fatal("driver Ready deadline exceeded"); return Ready{}
                }
            }
            save := func(rd Ready) {
                if !IsEmptySnap(rd.Snapshot) {
                    if err := ms.ApplySnapshot(rd.Snapshot); err != nil { t.Fatal(err) }
                }
                if err := ms.Append(rd.Entries); err != nil { t.Fatal(err) }
                if !IsEmptyHardState(rd.HardState) {
                    if err := ms.SetHardState(rd.HardState); err != nil { t.Fatal(err) }
                }
                // Outbound messages to not-yet-running new peers are dropped.
                // Persistence always precedes any possible message delivery.
            }
            advance := func() Status { n.Advance(); return n.Status() }
            applyConfig := func(e pb.Entry) {
                if e.Type != pb.EntryConfChange { t.Fatalf("unexpected config type %s", e.Type) }
                var cc pb.ConfChange
                if err := cc.Unmarshal(e.Data); err != nil { t.Fatal(err) }
                n.ApplyConfChange(cc)
            }
            if err := n.Campaign(ctx); err != nil { t.Fatal(err) }
            for i := 0; i < 12; i++ {
                st := n.Status()
                if st.RaftState == StateLeader && st.Applied >= 2 { break }
                rd := receive(); save(rd); advance()
                if i == 11 { t.Fatal("initial producer prefix did not finish") }
            }
            firstCC := pb.ConfChange{Type:pb.ConfChangeAddNode, NodeID:2}
            if err := n.ProposeConfChange(ctx, firstCC); err != nil { t.Fatal(err) }
            var first pb.Entry
            var firstReady Ready
            for i := 0; i < 12; i++ {
                rd := receive(); save(rd)
                for _, e := range rd.CommittedEntries {
                    if e.Type == pb.EntryConfChange { first, firstReady = e, rd }
                }
                if first.Index != 0 { break }
                advance()
                if i == 11 { t.Fatal("first committed configuration not delivered") }
            }
            _ = firstReady
            emit(map[string]interface{}{"event":"first_committed", "first_index":first.Index, "first_term":first.Term, "first_type":first.Type.String(), "persisted":true})
            activatedFirst := false
            if policy == "applied_then_advance" { applyConfig(first); activatedFirst = true }
            if policy != "deferred_no_advance" { advance() }
            before := n.Status()
            emit(map[string]interface{}{"event":"before_second", "first_index":first.Index,
                "first_activated":activatedFirst, "internal_applied":before.Applied,
                "commit":before.Commit, "voters":before.Config.Voters.IDs()})
            secondCC := pb.ConfChange{Type:pb.ConfChangeAddNode, NodeID:3}
            emit(map[string]interface{}{"event":"proposal_admitted", "first_index":first.Index, "first_pending":!activatedFirst, "first_rejected":false, "saved":true})
            if err := n.ProposeConfChange(ctx, secondCC); err != nil { t.Fatal(err) }
            // Status is a public event-loop barrier after proposal processing.
            afterProposal := n.Status()
            pendingAtProcessing := !activatedFirst
            emit(map[string]interface{}{"event":"second_proposal_processed", "first_index":first.Index,
                "first_activated":activatedFirst, "internal_applied":afterProposal.Applied,
                "commit":afterProposal.Commit, "voters":afterProposal.Config.Voters.IDs()})
            if policy == "deferred_no_advance" {
                applyConfig(first); activatedFirst = true; advance()
            }
            rd := receive(); save(rd)
            var second pb.Entry
            for _, e := range rd.Entries {
                if e.Index > first.Index { second = e; break }
            }
            if second.Index == 0 { t.Fatal("no second proposal entry reached Ready") }
            emit(map[string]interface{}{"event":"second_entry", "first_index":first.Index,
                "first_activated":activatedFirst, "second_index":second.Index,
                "entry_type":second.Type.String(), "entry_data_bytes":len(second.Data)})
            emit(map[string]interface{}{"event":"proposal_result", "phase":"processed_entry", "first_index":first.Index, "first_pending_at_processing":pendingAtProcessing, "first_rejected":false, "accepted_as_configuration":second.Type == pb.EntryConfChange || second.Type == pb.EntryConfChangeV2, "second_index":second.Index, "entry_type":second.Type.String(), "entry_data_bytes":len(second.Data), "processing_term":afterProposal.Term})
            st := advance()
            emit(map[string]interface{}{"event":"second_stored", "first_index":first.Index,
                "first_activated":activatedFirst, "second_index":second.Index,
                "commit":st.Commit, "internal_applied":st.Applied, "voters":st.Config.Voters.IDs()})
            if policy == "deferred_early_advance" {
                // Observe the second committed batch but do not apply it before
                // the first. This preserves the documented inter-Ready order.
                committedReady := receive(); save(committedReady)
                emit(map[string]interface{}{"event":"before_activation", "first_index":first.Index,
                    "first_activated":activatedFirst, "commit":n.Status().Commit,
                    "committed_count":len(committedReady.CommittedEntries)})
                applyConfig(first); activatedFirst = true
                for _, e := range committedReady.CommittedEntries {
                    if e.Type == pb.EntryConfChange { applyConfig(e) }
                }
                advance()
            }
            final := n.Status()
            emit(map[string]interface{}{"event":"finished", "first_activated":activatedFirst,
                "commit":final.Commit, "internal_applied":final.Applied,
                "voters":final.Config.Voters.IDs()})
            // Stopping with an uncommitted second proposal is a finite controlled
            // endpoint, not a liveness failure or a claim that it must commit.
        })
    }
}
