package raft

import (
    "encoding/json"
    "fmt"
    "testing"

    pb "go.etcd.io/raft/v3/raftpb"
)

type assuranceReplica struct {
    rn *RawNode
    store *MemoryStorage
    appendQ []pb.Message
    applyQ []pb.Message
}

type assuranceCluster struct {
    t *testing.T
    replicas []*assuranceReplica
    network []pb.Message
    holdApply uint64
    isolate uint64
    snapshots int
}

func assuranceEvent(v map[string]interface{}) {
    data, err := json.Marshal(v)
    if err != nil { panic(err) }
    fmt.Println("CA_EVENT " + string(data))
}

// The storage worker models successful stable storage using MemoryStorage.
// No process crash or actual filesystem durability is represented.
func (c *assuranceCluster) appendOne(r *assuranceReplica) {
    m := r.appendQ[0]
    r.appendQ = r.appendQ[1:]
    if len(m.Entries) != 0 {
        if err := r.store.Append(m.Entries); err != nil { c.t.Fatal(err) }
    }
    hs := pb.HardState{Term:m.Term, Vote:m.Vote, Commit:m.Commit}
    if !IsEmptyHardState(hs) {
        if err := r.store.SetHardState(hs); err != nil { c.t.Fatal(err) }
    }
    if m.Snapshot != nil {
        if err := r.store.ApplySnapshot(*m.Snapshot); err != nil { c.t.Fatal(err) }
    }
    // Release only after all earlier writes on this worker have completed.
    c.network = append(c.network, m.Responses...)
}

func (c *assuranceCluster) applyOne(r *assuranceReplica) {
    m := r.applyQ[0]
    r.applyQ = r.applyQ[1:]
    for _, e := range m.Entries {
        switch e.Type {
        case pb.EntryConfChange:
            var cc pb.ConfChange
            if err := cc.Unmarshal(e.Data); err != nil { c.t.Fatal(err) }
            r.rn.ApplyConfChange(cc)
        case pb.EntryConfChangeV2:
            var cc pb.ConfChangeV2
            if err := cc.Unmarshal(e.Data); err != nil { c.t.Fatal(err) }
            r.rn.ApplyConfChange(cc)
        }
    }
    c.network = append(c.network, m.Responses...)
}

// Execute all available network/application work. Each local worker is FIFO.
// Holding an append worker does not stop remote peers or the apply worker.
func (c *assuranceCluster) drain(holdAppendID uint64) int {
    for turn := 0; turn < 2000; turn++ {
        work := false
        for _, r := range c.replicas {
            if r.rn.HasReady() {
                work = true
                rd := r.rn.Ready()
                for _, m := range rd.Messages {
                    switch m.To {
                    case LocalAppendThread:
                        r.appendQ = append(r.appendQ, m)
                    case LocalApplyThread:
                        r.applyQ = append(r.applyQ, m)
                    default:
                        c.network = append(c.network, m)
                    }
                }
            }
        }
        for _, r := range c.replicas {
            if r.rn.raft.id != holdAppendID && len(r.appendQ) > 0 {
                work = true
                c.appendOne(r)
            }
            if r.rn.BasicStatus().ID != c.holdApply && len(r.applyQ) > 0 {
                work = true
                c.applyOne(r)
            }
        }
        messages := c.network
        c.network = nil
        for _, m := range messages {
            work = true
            if c.isolate != 0 && m.From!=m.To && (m.To==c.isolate || m.From==c.isolate) && m.From!=LocalAppendThread && m.From!=LocalApplyThread { continue }
            if m.Type==pb.MsgSnap { c.snapshots++; assuranceEvent(map[string]interface{}{"event":"actual_snapshot_message","from":m.From,"to":m.To,"snapshot":m.Snapshot}) }
            if m.To < 1 || m.To > uint64(len(c.replicas)) {
                c.t.Fatalf("unexpected destination %d", m.To)
            }
            if err := c.replicas[m.To-1].rn.Step(m); err != nil {
                if err == ErrStepPeerNotFound {
                    assuranceEvent(map[string]interface{}{"event":"peer_response_rejected","from":m.From,"to":m.To,"type":m.Type.String(),"error":err.Error()})
                } else { c.t.Fatal(err) }
            }
        }
        if !work { return turn }
    }
    c.t.Fatal("driver exceeded finite drain budget")
    return 0
}

func assuranceNewCluster(t *testing.T, count int) *assuranceCluster {
    c := &assuranceCluster{t:t}
    peers := make([]Peer, count)
    for i := range peers { peers[i].ID = uint64(i+1) }
    for i := 0; i < count; i++ {
        s := NewMemoryStorage()
        rn, err := NewRawNode(&Config{ID:uint64(i+1), ElectionTick:10, HeartbeatTick:1,
            Storage:s, AsyncStorageWrites:true, MaxInflightMsgs:16, MaxSizePerMsg:4096})
        if err != nil { t.Fatal(err) }
        if err := rn.Bootstrap(peers); err != nil { t.Fatal(err) }
        c.replicas = append(c.replicas, &assuranceReplica{rn:rn, store:s})
    }
    c.drain(0)
    if err := c.replicas[0].rn.Campaign(); err != nil { t.Fatal(err) }
    c.drain(0)
    if c.replicas[0].rn.BasicStatus().RaftState != StateLeader {
        t.Fatal("election prefix did not establish leader")
    }
    return c
}

func TestAssuranceOutstandingApplySnapshotExplore(t *testing.T) {
 c:=assuranceNewCluster(t,4)
 leader:=c.replicas[0]
 follower:=c.replicas[1]
 c.holdApply=2
 cc:=pb.ConfChangeV2{Transition:pb.ConfChangeTransitionJointExplicit,Changes:[]pb.ConfChangeSingle{{Type:pb.ConfChangeRemoveNode,NodeID:4}}}
 if err:=leader.rn.ProposeConfChange(cc);err!=nil {t.Fatal(err)}
 c.drain(0)
 if len(follower.applyQ)==0 {t.Fatal("no dispatched application batch")}
 assuranceEvent(map[string]interface{}{"event":"held_apply_prefix","status":follower.rn.Status(),"batch":follower.applyQ[0]})
 c.isolate=2
 if err:=leader.rn.ProposeConfChange(pb.ConfChangeV2{});err!=nil {t.Fatal(err)}
 c.drain(0)
 for i:=0;i<3;i++ {if err:=leader.rn.Propose([]byte(fmt.Sprintf("snapshot-prefix-%d",i)));err!=nil {t.Fatal(err)};c.drain(0)}
 st:=leader.rn.Status()
 cs:=leader.rn.raft.trk.ConfState()
 snap,err:=leader.store.CreateSnapshot(st.Applied,&cs,[]byte("exploration-no-external-state-machine"));if err!=nil {t.Fatal(err)}
 if err:=leader.store.Compact(st.Applied);err!=nil {t.Fatal(err)}
 beforeLast,err:=follower.store.LastIndex();if err!=nil {t.Fatal(err)}
 assuranceEvent(map[string]interface{}{"event":"snapshot_produced","index":snap.Metadata.Index,"leader_applied":st.Applied,"follower_last":beforeLast,"configuration":cs})
 c.isolate=0
 for i:=0;i<3;i++ {leader.rn.Tick();c.drain(0)}
 fs:=follower.rn.Status()
 stored,err:=follower.store.Snapshot();if err!=nil {t.Fatal(err)}
 assuranceEvent(map[string]interface{}{"event":"recovery_endpoint","snapshot_messages":c.snapshots,"follower_status":fs,"stored_snapshot":stored,"outstanding_apply_batches":len(follower.applyQ),"old_batch":follower.applyQ[0]})
 // Stop before choosing whether to apply or discard snapshot-covered work.
 // That caller contract remains the subject of investigation.
}
