package raft

import (
    "encoding/json"
    "fmt"
    "testing"

    "github.com/lni/dragonboat/v3/config"
    pb "github.com/lni/dragonboat/v3/raftpb"
)

func assuranceReadEvent(v map[string]interface{}) {
    data, err := json.Marshal(v)
    if err != nil { panic(err) }
    fmt.Println("CA_EVENT " + string(data))
}

func assuranceCtx(c pb.SystemCtx) string { return fmt.Sprintf("%d/%d", c.Low, c.High) }

type assuranceReadPeer struct {
    peer *Peer
    db ILogDB
    applied uint64
}

func TestAssuranceReadResponseCorrelation(t *testing.T) {
    // One outstanding request per origin makes destination an independent identity.
    contexts := map[uint64]pb.SystemCtx{2: {Low: 101, High: 30}, 3: {Low: 202, High: 30}}
    nodes := make(map[uint64]*assuranceReadPeer)
    queue := []pb.Message{}
    phase := "prepare"
    qualified := false
    emit := func(event string, origin uint64, fields map[string]interface{}) {
        fields["event"] = event
        fields["scenario"] = "overlapping_remote_reads"
        fields["origin"] = origin
        fields["cluster"] = uint64(7)
        assuranceReadEvent(fields)
    }
    flush := func(id uint64) {
        n := nodes[id]
        ud := n.peer.GetUpdate(true, n.applied)
        if !pb.IsEmptySnapshot(ud.Snapshot) { t.Fatal("unexpected snapshot") }
        if err := n.db.Append(ud.EntriesToSave); err != nil { t.Fatal(err) }
        if !pb.IsEmptyState(ud.State) { n.db.SetState(ud.State) }
        // Complete the accepted bootstrap configurations; no later configuration is proposed.
        for _, e := range ud.CommittedEntries {
            if e.Index != n.applied+1 { t.Fatalf("application gap at node %d", id) }
            if e.Type == pb.ConfigChangeEntry {
                var cc pb.ConfigChange
                if err := cc.Unmarshal(e.Cmd); err != nil { t.Fatal(err) }
                if !cc.Initialize || cc.Type != pb.AddNode { t.Fatal("unexpected configuration") }
                n.peer.ApplyConfigChange(cc)
            }
            n.applied = e.Index
        }
        for _, ready := range ud.ReadyToReads {
            emit("recipient_ready", id, map[string]interface{}{"context": assuranceCtx(ready.SystemCtx), "index": ready.Index})
        }
        for _, msg := range ud.Messages {
            if phase == "reads" && msg.Type == pb.ReadIndexResp {
                emit("response", msg.To, map[string]interface{}{
                    "context": assuranceCtx(pb.SystemCtx{Low: msg.Hint, High: msg.HintHigh}),
                    "index": msg.LogIndex, "term": msg.Term, "sender": msg.From,
                    "qualified": qualified,
                })
            }
            // Predetermined loss policy: suppress only first-context heartbeats.
            // All retained messages use one FIFO delivery path.
            if phase == "reads" && msg.Type == pb.Heartbeat && msg.Hint == contexts[2].Low && msg.HintHigh == contexts[2].High {
                emit("dropped_heartbeat", msg.To, map[string]interface{}{"sender": msg.From, "context": assuranceCtx(contexts[2])})
                continue
            }
            queue = append(queue, msg)
        }
        n.peer.Commit(ud)
        n.peer.NotifyRaftLastApplied(n.applied)
    }
    drain := func() {
        for steps := 0; len(queue) > 0; steps++ {
            if steps > 1000 { t.Fatal("message drain bound exceeded") }
            msg := queue[0]
            queue = queue[1:]
            dst, ok := nodes[msg.To]
            if !ok { t.Fatalf("unknown destination %d", msg.To) }
            isConfirmation := phase == "reads" && !qualified && msg.To == 1 && msg.Type == pb.HeartbeatResp && msg.Hint == contexts[3].Low && msg.HintHigh == contexts[3].High
            if isConfirmation {
                r := dst.peer.raft
                if r.state != leader || r.quorum() != 2 || msg.Term != r.term || msg.From == 1 { t.Fatal("invalid confirmation provenance") }
                if _, ok := r.remotes[msg.From]; !ok { t.Fatal("nonvoter confirmation") }
                for _, origin := range []uint64{2, 3} {
                    s, ok := r.readIndex.pending[contexts[origin]]
                    if !ok || s.from != origin || s.ctx != contexts[origin] { t.Fatal("missing pending request") }
                }
            }
            dst.peer.Handle(msg)
            if isConfirmation {
                qualified = true
                for _, origin := range []uint64{2, 3} {
                    _, remains := dst.peer.raft.readIndex.pending[contexts[origin]]
                    emit("released", origin, map[string]interface{}{
                        "expected_context": assuranceCtx(contexts[origin]), "removed": !remains,
                        "term": dst.peer.raft.term, "confirming_sender": msg.From,
                        "quorum": dst.peer.raft.quorum(), "confirmed_context": assuranceCtx(contexts[3]),
                    })
                }
            }
            flush(msg.To)
        }
    }
    for id := uint64(1); id <= 3; id++ {
        db := NewTestLogDB()
        cfg := config.Config{ClusterID: 7, NodeID: id, ElectionRTT: 10, HeartbeatRTT: 1, CheckQuorum: true}
        p := Launch(cfg, db, nil, []PeerAddress{{NodeID: 1, Address: "n1"}, {NodeID: 2, Address: "n2"}, {NodeID: 3, Address: "n3"}}, true, true)
        nodes[id] = &assuranceReadPeer{peer: p, db: db}
        flush(id)
    }
    drain()
    for tick := 0; tick < 100 && nodes[1].peer.raft.state != leader; tick++ {
        nodes[1].peer.Tick()
        flush(1)
        drain()
    }
    r := nodes[1].peer.raft
    if r.state != leader || !r.hasCommittedEntryAtCurrentTerm() { t.Fatal("current-term leader not established") }
    for id := uint64(1); id <= 3; id++ {
        n := nodes[id]
        if n.peer.raft.term != r.term || n.peer.raft.leaderID != 1 || n.applied != r.log.committed { t.Fatalf("prefix not complete on node %d", id) }
    }
    emit("prefix", 1, map[string]interface{}{"term": r.term, "commit": r.log.committed, "queued_messages": len(queue)})
    phase = "reads"
    for _, origin := range []uint64{2, 3} {
        nodes[origin].peer.ReadIndex(contexts[origin])
        flush(origin)
        // The first drain loses its own context-bearing heartbeats by the fixed policy.
        // The second drain confirms the later context, with the first request still pending.
        drain()
    }
    emit("finished", 1, map[string]interface{}{"qualified": qualified, "pending": len(r.readIndex.pending), "queued_messages": len(queue)})
    if !qualified { t.Fatal("quorum-confirmation prerequisite not reached") }
}
