package raft

import (
    "encoding/json"
    "fmt"
    "testing"

    "github.com/lni/dragonboat/v3/config"
    pb "github.com/lni/dragonboat/v3/raftpb"
)

// This driver persists each update before delivering its messages. It uses
// real bootstrap, ticks, elections, forwarding and heartbeat responses.
// Application entries have no user state machine in this protocol-level probe.
func TestAssuranceForwardedReadBatchIdentity(t *testing.T) {
    emit := func(v map[string]interface{}) {
        v["scenario"] = "forwarded_batch"
        b, err := json.Marshal(v)
        if err != nil { t.Fatal(err) }
        fmt.Println("CA_EVENT " + string(b))
    }
    peers := map[uint64]*Peer{}
    stores := map[uint64]*TestLogDB{}
    applied := map[uint64]uint64{}
    ready := map[uint64][]pb.ReadyToRead{}
    addresses := []PeerAddress{{NodeID:1, Address:"n1"}, {NodeID:2, Address:"n2"}, {NodeID:3, Address:"n3"}}
    for id := uint64(1); id <= 3; id++ {
        stores[id] = NewTestLogDB().(*TestLogDB)
        peers[id] = Launch(config.Config{NodeID:id, ClusterID:1, ElectionRTT:10, HeartbeatRTT:1, CheckQuorum:true}, stores[id], nil, addresses, true, true)
    }
    take := func(id uint64) []pb.Message {
        p := peers[id]
        ud := p.GetUpdate(true, applied[id])
        if err := stores[id].Append(ud.EntriesToSave); err != nil { t.Fatal(err) }
        if !pb.IsEmptyState(ud.State) { stores[id].SetState(ud.State) }
        msgs := append([]pb.Message(nil), ud.Messages...)
        ready[id] = append(ready[id], ud.ReadyToReads...)
        for _, rr := range ud.ReadyToReads {
            emit(map[string]interface{}{"event":"ready_result", "origin":id, "ctx":fmt.Sprintf("%d/%d", rr.SystemCtx.Low, rr.SystemCtx.High), "index":rr.Index})
        }
        p.Commit(ud)
        for _, e := range ud.CommittedEntries {
            if e.Type == pb.ConfigChangeEntry {
                var cc pb.ConfigChange
                if err := cc.Unmarshal(e.Cmd); err != nil { t.Fatal(err) }
                p.ApplyConfigChange(cc)
            }
            applied[id] = e.Index
        }
        p.NotifyRaftLastApplied(applied[id])
        return msgs
    }
    var dropped int
    first := pb.SystemCtx{Low:101, High:30}
    second := pb.SystemCtx{Low:202, High:30}
    pump := func(queue []pb.Message, dropFirst bool) {
        for steps := 0; len(queue) > 0; steps++ {
            if steps >= 1000 { t.Fatal("message drain exceeded bound") }
            m := queue[0]
            queue = queue[1:]
            if dropFirst && m.Type == pb.Heartbeat && m.Hint == first.Low && m.HintHigh == first.High {
                dropped++
                emit(map[string]interface{}{"event":"dropped_heartbeat", "from":m.From, "to":m.To, "low":m.Hint, "high":m.HintHigh})
                continue
            }
            if m.Type == pb.ReadIndex || m.Type == pb.ReadIndexResp || (m.Type == pb.HeartbeatResp && m.Hint != 0) {
                emit(map[string]interface{}{"event":"delivered", "type":m.Type.String(), "from":m.From, "to":m.To, "term":m.Term, "low":m.Hint, "high":m.HintHigh, "index":m.LogIndex})
            }
            peers[m.To].Handle(m)
            if m.Type == pb.ReadIndex {
                // Observe the actual admitted object before any response delivery.
                ctx := pb.SystemCtx{Low:m.Hint, High:m.HintHigh}
                if rs, ok := peers[m.To].raft.readIndex.pending[ctx]; ok {
                    emit(map[string]interface{}{"event":"admitted", "origin":rs.from, "ctx":fmt.Sprintf("%d/%d",rs.ctx.Low,rs.ctx.High), "index":rs.index, "leader":m.To})
                }
            }
            queue = append(queue, take(m.To)...)
        }
    }
    for id := uint64(1); id <= 3; id++ { pump(take(id), false) }
    // Only node 1's clock is advanced until it campaigns. All resulting votes
    // and replication messages are delivered through Peer.Handle.
    for i := 0; i < 30 && !peers[1].raft.isLeader(); i++ {
        peers[1].Tick()
        pump(take(1), false)
    }
    if !peers[1].raft.isLeader() || !peers[1].raft.hasCommittedEntryAtCurrentTerm() { t.Fatal("leader prefix incomplete") }
    for id := uint64(1); id <= 3; id++ {
        if peers[id].raft.leaderID != 1 || applied[id] < 4 { t.Fatalf("prefix incomplete on %d", id) }
    }
    for origin := uint64(2); origin <= 3; origin++ {
        emit(map[string]interface{}{"event":"prefix", "origin":origin, "leader_ready":peers[1].raft.isLeader() && peers[1].raft.hasCommittedEntryAtCurrentTerm(), "term":peers[1].raft.term, "commit":peers[1].raft.log.committed, "follower_leader":peers[origin].raft.leaderID, "follower_applied":applied[origin]})
    }
    emit(map[string]interface{}{"event":"invoke", "operation":"first", "origin":2, "low":first.Low, "high":first.High})
    peers[2].ReadIndex(first)
    pump(take(2), true)
    status, ok := peers[1].raft.readIndex.pending[first]
    if !ok || status.from != 2 || dropped != 2 { t.Fatal("first request was not admitted with both heartbeats lost") }
    emit(map[string]interface{}{"event":"first_pending", "origin":status.from, "low":status.ctx.Low, "high":status.ctx.High, "index":status.index})
    emit(map[string]interface{}{"event":"invoke", "operation":"second", "origin":3, "low":second.Low, "high":second.High})
    peers[3].ReadIndex(second)
    pump(take(3), false)
    // Deliver subsequent periodic heartbeats without faults. This is a finite
    // observation of protocol-owned continuation, not a permanent-stall proof.
    for i := 0; i < 3; i++ { peers[1].Tick(); pump(take(1), false) }
    for id := uint64(1); id <= 3; id++ {
        emit(map[string]interface{}{"event":"endpoint", "node":id, "ready":ready[id], "pending":len(peers[id].raft.readIndex.pending), "applied":applied[id], "term":peers[id].raft.term, "leader":peers[id].raft.leaderID})
    }
}
