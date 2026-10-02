package raft

import (
    "encoding/json"
    "fmt"
    "testing"

    pb "go.etcd.io/raft/v3/raftpb"
)

func TestAssuranceStorageReplacementViewFixed(t *testing.T) {
    nodes := map[uint64]*RawNode{}
    stores := map[uint64]*MemoryStorage{}
    var eventSerial uint64
    emit := func(v map[string]interface{}) uint64 {
        eventSerial++
        v["serial"] = eventSerial
        b, err := json.Marshal(v)
        if err != nil { t.Fatal(err) }
        fmt.Println("CA_EVENT " + string(b))
        return eventSerial
    }
    for id := uint64(1); id <= 5; id++ {
        ms := NewMemoryStorage()
        if err := ms.ApplySnapshot(pb.Snapshot{Metadata: pb.SnapshotMetadata{
            Index: 1, Term: 1, ConfState: pb.ConfState{Voters: []uint64{1, 2, 3, 4, 5}},
        }}); err != nil { t.Fatal(err) }
        if err := ms.SetHardState(pb.HardState{Term: 1, Commit: 1}); err != nil { t.Fatal(err) }
        rn, err := NewRawNode(&Config{ID: id, ElectionTick: 10, HeartbeatTick: 1,
            Storage: ms, Applied: 1, AsyncStorageWrites: true,
            MaxSizePerMsg: 1024 * 1024, MaxInflightMsgs: 16})
        if err != nil { t.Fatal(err) }
        nodes[id], stores[id] = rn, ms
    }
    entryValue := func(e pb.Entry) string {
        b, err := json.Marshal(map[string]interface{}{"index":e.Index, "term":e.Term, "type":int32(e.Type), "data":e.Data})
        if err != nil { t.Fatal(err) }
        return string(b)
    }
    phase := "prefix"
    var expectedEntry string
    var replacementSerial uint64
    var network []pb.Message
    var completion2 []pb.Message
    var append2 []pb.Message
    deferCompletion2 := false
    dropped := 0
    var selectedIndex, selectedTerm uint64
    step := func(m pb.Message) {
        if err := nodes[m.To].Step(m); err != nil { t.Fatalf("Step(%s %d->%d): %v", m.Type, m.From, m.To, err) }
    }
    allowed := func(m pb.Message) bool {
        if phase == "prefix" || phase == "finish" { return true }
        if phase == "first" { return (m.From == 1 && m.To == 2) || (m.From == 2 && m.To == 1) }
        // Actual elections run on the available majority. Replication to the
        // two voting supporters is withheld until the controlled interval ends.
        if m.Type == pb.MsgVote || m.Type == pb.MsgVoteResp { return true }
        leader := uint64(3)
        if phase == "return" { leader = 1 }
        return (m.From == leader && m.To == 2) || (m.From == 2 && m.To == leader)
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
            for _, e := range m.Entries {
                if e.Type != pb.EntryNormal { t.Fatalf("unexpected configuration entry %v", e) }
            }
        default:
            t.Fatalf("unexpected worker message %s", m.Type)
        }
        for _, response := range m.Responses {
            if response.To == id {
                if id == 2 && deferCompletion2 { completion2 = append(completion2, response) } else { step(response) }
            } else { network = append(network, response) }
        }
    }
    dispatch := func(id uint64, m pb.Message) {
        if m.To == LocalAppendThread {
            if id == 2 && (len(append2) > 0 || (phase == "return" && len(m.Entries) > 0)) {
                append2 = append(append2, m)
                if replacementSerial == 0 {
                    for _, e := range m.Entries {
                        if e.Index == selectedIndex {
                            expectedEntry = entryValue(e)
                            replacementSerial = emit(map[string]interface{}{
                                "event":"replacement", "op":"replacement", "node":2, "entry_index":e.Index,
                                "expected_entry":expectedEntry, "accepted_term":nodes[2].BasicStatus().Term})
                            break
                        }
                    }
                }
                var firstIndex, firstTerm uint64
                if len(m.Entries) > 0 { firstIndex, firstTerm = m.Entries[0].Index, m.Entries[0].Term }
                emit(map[string]interface{}{"event":"replacement_queued", "op":"replacement", "node":2,
                    "term":nodes[2].BasicStatus().Term, "entries":len(m.Entries),
                    "first_index":firstIndex, "first_term":firstTerm})
            } else { perform(id, m) }
        } else if m.To == LocalApplyThread { perform(id, m) } else { network = append(network, m) }
    }
    pump := func() {
        for iteration := 0; iteration < 10000; iteration++ {
            progress := false
            for id := uint64(1); id <= 5; id++ {
                if nodes[id].HasReady() {
                    rd := nodes[id].Ready()
                    for _, m := range rd.Messages { dispatch(id, m) }
                    progress = true
                }
            }
            if len(network) > 0 {
                m := network[0]
                network = network[1:]
                if allowed(m) { step(m) } else { dropped++ }
                progress = true
            }
            if !progress { return }
        }
        t.Fatal("driver drain bound exceeded")
    }
    campaign := func(id uint64) {
        if err := nodes[id].Campaign(); err != nil { t.Fatal(err) }
        pump()
        if nodes[id].BasicStatus().RaftState != StateLeader { t.Fatalf("node %d did not become leader", id) }
        emit(map[string]interface{}{"event":"leader", "phase":phase, "node":id,
            "term":nodes[id].BasicStatus().Term, "commit":nodes[id].BasicStatus().Commit})
    }
    campaign(1)
    phase, deferCompletion2 = "first", true
    if err := nodes[1].Propose([]byte("retained-from-first-leader")); err != nil { t.Fatal(err) }
    pump()
    if len(completion2) == 0 { t.Fatal("no deferred original storage completion") }
    first := completion2[0]
    selectedIndex, selectedTerm = first.Index, first.LogTerm
    emit(map[string]interface{}{"event":"original_completion", "op":"replacement", "node":2,
        "response_type":first.Type.String(), "response_term":first.Term,
        "entry_index":first.Index, "entry_term":first.LogTerm})

    phase = "middle"
    campaign(3)
    if nodes[1].BasicStatus().RaftState != StateFollower { t.Fatal("node 1 did not step down on actual vote request") }
    phase = "return"
    campaign(1)
    if len(append2) == 0 { t.Fatal("no replacement storage request reached follower") }
    observe := func(at string) {
        logTerm, err := nodes[2].raft.raftLog.term(selectedIndex)
        if err != nil { t.Fatal(err) }
        storedTerm, err := stores[2].Term(selectedIndex)
        if err != nil { t.Fatal(err) }
        u := &nodes[2].raft.raftLog.unstable
        entries, err := nodes[2].raft.raftLog.slice(selectedIndex, selectedIndex+1, noLimit)
        if err != nil || len(entries) != 1 { t.Fatalf("logical entry query failed: %v %v", entries, err) }
        event := "view"
        if at == "after_old_completion" { event = "old_completion_result" }
        emit(map[string]interface{}{"event":event, "log_entry":entryValue(entries[0]), "op":"replacement", "phase":at, "node":2,
            "entry_index":selectedIndex, "original_entry_term":selectedTerm,
            "log_term":logTerm, "stored_term":storedTerm, "raft_term":nodes[2].BasicStatus().Term,
            "unstable_offset":u.offset, "unstable_entries":len(u.entries),
            "pending_writes":len(append2), "pending_completions":len(completion2)})
    }
    observe("before_old_completion")
    if replacementSerial == 0 { t.Fatal("replacement entry producer not observed") }
    stored, err := stores[2].Entries(selectedIndex, selectedIndex+1, ^uint64(0))
    if err != nil || len(stored) != 1 { t.Fatalf("stored entry query failed: %v %v", stored, err) }
    emit(map[string]interface{}{"event":"old_completion_admitted", "op":"replacement", "node":2,
        "entry_index":selectedIndex, "replacement_serial":replacementSerial,
        "completion_type":completion2[0].Type.String(), "old_response_term":completion2[0].Term,
        "active_term":nodes[2].BasicStatus().Term,
        "stale_response":completion2[0].Term < nodes[2].BasicStatus().Term,
        "stored_conflicts":entryValue(stored[0]) != expectedEntry, "pending_writes":len(append2)})
    // Local responses to node 2 retain their production order. Network
    // responses to other recipients can be delivered while these are delayed.
    step(completion2[0])
    completion2 = completion2[1:]
    observe("after_old_completion")
    for _, m := range completion2 { step(m) }
    completion2 = nil
    deferCompletion2 = false
    // Finish every delayed request in append-target order before accepting
    // further work. The current replacement becomes visible in Storage here.
    for _, m := range append2 { perform(2, m) }
    append2 = nil
    observe("after_current_completion")
    phase = "finish"
    pump()
    // A finite explicit heartbeat prompts retransmission of previously lost
    // network traffic; no timer or eventual-commit assumption is an oracle.
    for i := 0; i < 2; i++ { nodes[1].Tick(); pump() }
    emit(map[string]interface{}{"event":"finished", "op":"replacement",
        "node":2, "entry_index":selectedIndex, "pending_network":len(network), "pending_append2":len(append2),
        "pending_completion2":len(completion2), "dropped_network":dropped,
        "follower_applied":nodes[2].BasicStatus().Applied, "follower_commit":nodes[2].BasicStatus().Commit})
}
