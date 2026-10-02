package raft

import (
    "encoding/json"
    "fmt"
    "testing"

    pb "go.etcd.io/raft/v3/raftpb"
)

// This driver substitutes ordered in-memory storage workers and a controllable
// transport. It does not simulate device failure or alter raft internals.
func TestAssuranceStorageTermReconfirmation(t *testing.T) {
    nodes := map[uint64]*RawNode{}
    stores := map[uint64]*MemoryStorage{}
    emit := func(v map[string]interface{}) {
        b, err := json.Marshal(v)
        if err != nil { t.Fatal(err) }
        fmt.Println("CA_EVENT " + string(b))
    }
    for id := uint64(1); id <= 3; id++ {
        ms := NewMemoryStorage()
        if err := ms.ApplySnapshot(pb.Snapshot{Metadata: pb.SnapshotMetadata{
            Index: 1, Term: 1, ConfState: pb.ConfState{Voters: []uint64{1, 2, 3}},
        }}); err != nil { t.Fatal(err) }
        if err := ms.SetHardState(pb.HardState{Term: 1, Commit: 1}); err != nil { t.Fatal(err) }
        rn, err := NewRawNode(&Config{ID: id, ElectionTick: 10, HeartbeatTick: 1,
            Storage: ms, Applied: 1, AsyncStorageWrites: true,
            MaxSizePerMsg: 1024 * 1024, MaxInflightMsgs: 16})
        if err != nil { t.Fatal(err) }
        nodes[id], stores[id] = rn, ms
    }
    var network []pb.Message
    held := map[uint64][]pb.Message{}
    blockAppend2 := false
    dropTo3 := false
    dropped := 0
    step := func(m pb.Message) {
        if err := nodes[m.To].Step(m); err != nil { t.Fatalf("Step(%s %d->%d): %v", m.Type, m.From, m.To, err) }
    }
    perform := func(id uint64, m pb.Message) {
        ms := stores[id]
        switch m.Type {
        case pb.MsgStorageAppend:
            if m.Snapshot != nil {
                if err := ms.ApplySnapshot(*m.Snapshot); err != nil { t.Fatal(err) }
            }
            if len(m.Entries) != 0 {
                if err := ms.Append(m.Entries); err != nil { t.Fatal(err) }
            }
            hs := pb.HardState{Term: m.Term, Vote: m.Vote, Commit: m.Commit}
            if !IsEmptyHardState(hs) {
                if err := ms.SetHardState(hs); err != nil { t.Fatal(err) }
            }
        case pb.MsgStorageApply:
            // The application consumes each delivered entry before replying.
            for _, e := range m.Entries {
                if e.Type != pb.EntryNormal { t.Fatalf("unexpected configuration entry %v", e) }
            }
        default:
            t.Fatalf("unexpected local worker message %s", m.Type)
        }
        for _, response := range m.Responses {
            if response.To == id { step(response) } else { network = append(network, response) }
        }
    }
    dispatch := func(id uint64, m pb.Message) {
        if m.To == LocalAppendThread {
            if blockAppend2 && id == 2 {
                held[id] = append(held[id], m)
            } else { perform(id, m) }
        } else if m.To == LocalApplyThread { perform(id, m) } else { network = append(network, m) }
    }
    pump := func() {
        for iteration := 0; iteration < 10000; iteration++ {
            progress := false
            for id := uint64(1); id <= 3; id++ {
                if nodes[id].HasReady() {
                    rd := nodes[id].Ready()
                    for _, m := range rd.Messages { dispatch(id, m) }
                    progress = true
                }
            }
            if len(network) > 0 {
                m := network[0]
                network = network[1:]
                if dropTo3 && m.To == 3 { dropped++ } else { step(m) }
                progress = true
            }
            if !progress { return }
        }
        t.Fatal("driver drain bound exceeded")
    }
    if err := nodes[1].Campaign(); err != nil { t.Fatal(err) }
    pump()
    if nodes[1].BasicStatus().RaftState != StateLeader { t.Fatal("prefix did not elect node 1") }
    emit(map[string]interface{}{"event":"prefix", "leader_term":nodes[1].BasicStatus().Term,
        "leader_commit":nodes[1].BasicStatus().Commit, "follower_applied":nodes[2].BasicStatus().Applied})

    blockAppend2, dropTo3 = true, true
    if err := nodes[1].Propose([]byte("reconfirm-storage-term")); err != nil { t.Fatal(err) }
    pump()
    if len(held[2]) != 1 || len(held[2][0].Entries) != 1 { t.Fatalf("unexpected held append shape: %v", held[2]) }
    old := held[2][0]
    entry := old.Entries[0]
    emit(map[string]interface{}{"event":"append_held", "op":"reconfirm", "node":2,
        "entry_index":entry.Index, "entry_term":entry.Term, "request_term":old.Term,
        "unstable_offset":nodes[2].raft.raftLog.unstable.offset})

    // Node 3 did not receive the proposal. Its actual campaign produces a vote
    // request which advances node 2's term even though node 2 rejects the vote.
    if err := nodes[3].Campaign(); err != nil { t.Fatal(err) }
    if !nodes[3].HasReady() { t.Fatal("campaign produced no Ready") }
    campaignReady := nodes[3].Ready()
    var request pb.Message
    var deferred3 []pb.Message
    for _, m := range campaignReady.Messages {
        if m.Type == pb.MsgVote && m.To == 2 { request = m } else { deferred3 = append(deferred3, m) }
    }
    if request.Type != pb.MsgVote { t.Fatal("campaign did not produce request to node 2") }
    step(request)
    if !nodes[2].HasReady() { t.Fatal("term transition produced no Ready") }
    transitionReady := nodes[2].Ready()
    for _, m := range transitionReady.Messages { dispatch(2, m) }
    if len(held[2]) != 2 { t.Fatalf("expected ordered pair of storage requests, got %d", len(held[2])) }
    current := held[2][1]
    emit(map[string]interface{}{"event":"term_transition", "op":"reconfirm", "node":2,
        "new_term":nodes[2].BasicStatus().Term, "vote_request_term":request.Term,
        "new_append_term":current.Term, "new_append_entries":len(current.Entries)})

    observe := func(phase string) {
        u := &nodes[2].raft.raftLog.unstable
        term, err := stores[2].Term(entry.Index)
        if err != nil { t.Fatal(err) }
        emit(map[string]interface{}{"event":"frontier", "op":"reconfirm", "phase":phase,
            "node":2, "term":nodes[2].BasicStatus().Term, "entry_index":entry.Index,
            "stored_entry_term":term, "unstable_offset":u.offset,
            "unstable_entries":len(u.entries), "offset_in_progress":u.offsetInProgress})
    }
    // Storage requests and all their responses are processed in target FIFO
    // order. The term-changing network input occurs while the first is delayed.
    perform(2, old)
    observe("old_completion")
    perform(2, current)
    observe("current_completion")
    held[2] = nil
    blockAppend2, dropTo3 = false, false
    for _, m := range deferred3 { dispatch(3, m) }
    pump()
    emit(map[string]interface{}{"event":"finished", "op":"reconfirm", "pending_network":len(network),
        "pending_append2":len(held[2]), "dropped_network":dropped,
        "follower_term":nodes[2].BasicStatus().Term})
}
