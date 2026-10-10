package raft

import (
    "encoding/json"
    "fmt"
    "testing"

    "github.com/lni/dragonboat/v3/config"
    pb "github.com/lni/dragonboat/v3/raftpb"
)

// This simulator persists each update before publishing its messages. It applies
// bootstrap membership entries and notifies the peer of the actual applied prefix.
// There are no crashes, storage rewrites, fabricated replies, or private handlers.
func TestAssuranceForwardedReadBatchContext(t *testing.T) {
    emit := func(v interface{}) {
        b, err := json.Marshal(v)
        if err != nil { t.Fatal(err) }
        fmt.Println("CA_EVENT " + string(b))
    }
    peers := map[uint64]*Peer{}
    stores := map[uint64]ILogDB{}
    applied := map[uint64]uint64{}
    ready := map[uint64][]pb.ReadyToRead{}
    addresses := []PeerAddress{{NodeID:1, Address:"n1"}, {NodeID:2, Address:"n2"}, {NodeID:3, Address:"n3"}}
    var queue []pb.Message
    var responses []pb.Message
    collect := func(id uint64) {
        p := peers[id]
        if !p.HasUpdate(true) { return }
        ud := p.GetUpdate(true, applied[id])
        if err := stores[id].Append(ud.EntriesToSave); err != nil { t.Fatal(err) }
        if !pb.IsEmptyState(ud.State) { stores[id].SetState(ud.State) }
        for _, e := range ud.CommittedEntries {
            if e.Type == pb.ConfigChangeEntry {
                var cc pb.ConfigChange
                if err := cc.Unmarshal(e.Cmd); err != nil { t.Fatal(err) }
                p.ApplyConfigChange(cc)
            }
            applied[id] = e.Index
        }
        ready[id] = append(ready[id], ud.ReadyToReads...)
        for _, m := range ud.Messages {
            queue = append(queue, m)
            if m.Type == pb.ReadIndexResp { responses = append(responses, m) }
        }
        p.Commit(ud)
        p.NotifyRaftLastApplied(applied[id])
    }
    drain := func() {
        for steps := 0; len(queue) > 0; steps++ {
            if steps > 1000 { t.Fatal("message drain exceeded bound") }
            m := queue[0]
            queue = queue[1:]
            peers[m.To].Handle(m)
            collect(m.To)
        }
    }
    for id := uint64(1); id <= 3; id++ {
        stores[id] = NewTestLogDB()
        peers[id] = Launch(config.Config{NodeID:id, ClusterID:1, ElectionRTT:10, HeartbeatRTT:1, CheckQuorum:true}, stores[id], nil, addresses, true, true)
        collect(id)
    }
    drain()
    for tick := 0; tick < 25 && !peers[1].raft.isLeader(); tick++ {
        peers[1].Tick()
        collect(1)
        drain()
    }
    if !peers[1].raft.isLeader() || !peers[1].raft.hasCommittedEntryAtCurrentTerm() {
        t.Fatal("election and current-term commit prerequisite not reached")
    }
    for id := uint64(1); id <= 3; id++ {
        if applied[id] != peers[1].raft.log.committed { t.Fatal("initial applied prefixes differ") }
    }
    emit(map[string]interface{}{"event":"initialized", "leader":1, "term":peers[1].raft.term, "commit":peers[1].raft.log.committed, "applied":applied})

    // Distinct nonzero contexts are admitted directly by Peer.ReadIndex. These
    // are caller inputs, not injected leader state or fabricated confirmations.
    a := pb.SystemCtx{Low:101, High:30}
    b := pb.SystemCtx{Low:202, High:30}
    peers[2].ReadIndex(a)
    collect(2)
    peers[3].ReadIndex(b)
    collect(3)
    emit(map[string]interface{}{"event":"submitted", "request_a_node":2, "request_a":a, "request_b_node":3, "request_b":b})
    dropped := 0
    // The first two queued messages are real forwarded requests. All subsequent
    // messages retain FIFO order. Only A's initial heartbeats are lost.
    for steps := 0; len(queue) > 0; steps++ {
        if steps > 1000 { t.Fatal("read delivery exceeded bound") }
        m := queue[0]
        queue = queue[1:]
        if m.Type == pb.Heartbeat && m.Hint == a.Low && m.HintHigh == a.High {
            dropped++
            continue
        }
        peers[m.To].Handle(m)
        collect(m.To)
    }
    emit(map[string]interface{}{"event":"batch_drained", "dropped_first_heartbeats":dropped, "responses":responses, "node2_ready":ready[2], "node3_ready":ready[3], "leader_pending":len(peers[1].raft.readIndex.pending), "queue_length":len(queue)})
    // Restore full delivery and advance three heartbeat intervals. This is a
    // bounded observation, not a claim of infinite failure or client timeout.
    for tick := 0; tick < 3; tick++ {
        peers[1].Tick()
        collect(1)
        drain()
    }
    aMatches, bMatches := 0, 0
    for _, r := range ready[2] { if r.SystemCtx == a { aMatches++ } }
    for _, r := range ready[3] { if r.SystemCtx == b { bMatches++ } }
    emit(map[string]interface{}{"event":"after_three_heartbeats", "request_a_node":2, "request_a":a, "request_a_matching_ready":aMatches, "request_b_node":3, "request_b":b, "request_b_matching_ready":bMatches, "node2_ready":ready[2], "node3_ready":ready[3], "leader_pending":len(peers[1].raft.readIndex.pending), "queue_length":len(queue), "leader":peers[1].raft.leaderID, "term":peers[1].raft.term})
}
