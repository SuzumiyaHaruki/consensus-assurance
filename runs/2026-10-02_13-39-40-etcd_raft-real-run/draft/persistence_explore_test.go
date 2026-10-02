package raft

import (
    "encoding/json"
    "fmt"
    "testing"

    pb "go.etcd.io/raft/v3/raftpb"
)

// This exploration compares caller policies, not a correctness oracle.
func TestAssurancePersistencePolicy(t *testing.T) {
    for _, early := range []bool{false, true} {
        policy := "persist_before_reply"
        if early { policy = "reply_before_same_batch_append" }
        t.Run(policy, func(t *testing.T) {
            nodes := map[uint64]*RawNode{}
            stores := map[uint64]*MemoryStorage{}
            emit := func(stage string, fields map[string]interface{}) {
                fields["event"] = stage
                fields["policy"] = policy
                b, err := json.Marshal(fields)
                if err != nil { t.Fatal(err) }
                fmt.Println("CA_EVENT " + string(b))
            }
            must := func(err error) { if err != nil { t.Fatal(err) } }
            last := func(id uint64) uint64 {
                n, err := stores[id].LastIndex(); must(err); return n
            }
            for id := uint64(1); id <= 3; id++ {
                s := NewMemoryStorage()
                must(s.ApplySnapshot(pb.Snapshot{Metadata: pb.SnapshotMetadata{
                    Index: 1, Term: 1, ConfState: pb.ConfState{Voters: []uint64{1,2,3}},
                }}))
                must(s.SetHardState(pb.HardState{Term: 1, Commit: 1}))
                rn, err := NewRawNode(&Config{ID:id, ElectionTick:10, HeartbeatTick:1,
                    Storage:s, Applied:1, MaxSizePerMsg:4096, MaxInflightMsgs:16})
                must(err)
                nodes[id], stores[id] = rn, s
            }
            persist := func(id uint64, rd Ready) {
                if !IsEmptySnap(rd.Snapshot) { must(stores[id].ApplySnapshot(rd.Snapshot)) }
                must(stores[id].Append(rd.Entries))
                if !IsEmptyHardState(rd.HardState) { must(stores[id].SetHardState(rd.HardState)) }
            }
            // No faults or substituted replies in this prefix. Drain actual
            // Ready work, persist before send, and serialize all core calls.
            drain := func() {
                for round:=0; round<100; round++ {
                    work := false
                    var messages []pb.Message
                    for id:=uint64(1); id<=3; id++ {
                        if !nodes[id].HasReady() { continue }
                        work = true
                        rd := nodes[id].Ready()
                        persist(id, rd)
                        messages = append(messages, rd.Messages...)
                        nodes[id].Advance(rd)
                    }
                    for _, m := range messages { must(nodes[m.To].Step(m)) }
                    if !work { return }
                }
                t.Fatal("prefix did not quiesce within bounded drain")
            }
            must(nodes[1].Campaign())
            drain()
            if nodes[1].BasicStatus().RaftState != StateLeader { t.Fatal("campaign did not elect node 1") }
            base := nodes[1].BasicStatus().Commit
            emit("prefix", map[string]interface{}{"leader":1,"term":nodes[1].BasicStatus().Term,
                "commit":base,"stored_1":last(1),"stored_2":last(2),"stored_3":last(3)})
            payload := []byte("persistence-policy-operation")
            must(nodes[1].Propose(payload))
            if !nodes[1].HasReady() { t.Fatal("proposal has no Ready") }
            leaderRD := nodes[1].Ready()
            var app pb.Message
            var haveApp bool
            for _, m := range leaderRD.Messages {
                if m.To==2 && m.Type==pb.MsgApp && len(m.Entries)>0 {
                    app, haveApp = m, true
                }
            }
            if !haveApp { t.Fatal("no produced append to follower 2") }
            target := app.Entries[len(app.Entries)-1].Index
            persist(1, leaderRD)
            nodes[1].Advance(leaderRD)
            // Node 3 receives none of this operation's appends. This finite
            // network delay is identical in both independent policy runs.
            must(nodes[2].Step(app))
            if !nodes[2].HasReady() { t.Fatal("follower has no Ready") }
            followerRD := nodes[2].Ready()
            if len(followerRD.Entries)==0 { t.Fatal("missing follower append work") }
            // Restrict this exploration to unchanged HardState. This avoids
            // using a policy that reverses README's Entries/HardState order.
            if !IsEmptyHardState(followerRD.HardState) { t.Fatal("limiting premise: follower HardState changed") }
            var reply pb.Message
            var haveReply bool
            for _, m := range followerRD.Messages {
                if m.Type==pb.MsgAppResp && m.To==1 && !m.Reject && m.Index==target {
                    reply, haveReply = m, true
                }
            }
            if !haveReply { t.Fatal("follower did not produce matching success reply") }
            emit("reply_produced", map[string]interface{}{"target":target,"reply_term":reply.Term,
                "reply_index":reply.Index,"stored_2":last(2),"leader_commit":nodes[1].BasicStatus().Commit})
            if !early { persist(2, followerRD) }
            emit("reply_delivery", map[string]interface{}{"target":target,"stored_2":last(2),
                "leader_commit":nodes[1].BasicStatus().Commit})
            must(nodes[1].Step(reply))
            state := nodes[1].Status()
            emit("reply_consumed", map[string]interface{}{"target":target,"stored_1":last(1),
                "stored_2":last(2),"stored_3":last(3),"leader_commit":state.Commit,
                "follower_match":state.Progress[2].Match})
            // End the delayed write independently of the measured commit.
            if early { persist(2, followerRD) }
            nodes[2].Advance(followerRD)
            drain()
            entries, err := stores[2].Entries(target,target+1,4096); must(err)
            emit("schedule_complete", map[string]interface{}{"target":target,"stored_2":last(2),
                "stored_payload":string(entries[0].Data),"leader_commit":nodes[1].BasicStatus().Commit})
        })
    }
}
