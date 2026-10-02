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
            if len(r.applyQ) > 0 {
                work = true
                c.applyOne(r)
            }
        }
        messages := c.network
        c.network = nil
        for _, m := range messages {
            work = true
            if m.To < 1 || m.To > uint64(len(c.replicas)) {
                c.t.Fatalf("unexpected destination %d", m.To)
            }
            if err := c.replicas[m.To-1].rn.Step(m); err != nil { c.t.Fatal(err) }
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

func (c *assuranceCluster) observe(caseID, phase string, index, term uint64, data []byte, turns int) {
    persisted := 0
    indexes := []uint64{}
    for _, r := range c.replicas {
        last, err := r.store.LastIndex()
        if err != nil { c.t.Fatal(err) }
        indexes = append(indexes,last)
        if last >= index {
            es, err := r.store.Entries(index,index+1,^uint64(0))
            if err != nil { c.t.Fatal(err) }
            if len(es)==1 && es[0].Term==term && string(es[0].Data)==string(data) { persisted++ }
        }
    }
    leader := c.replicas[0]
    committed := leader.rn.BasicStatus().Commit
    threshold := len(c.replicas)/2+1
    assuranceEvent(map[string]interface{}{
        "event":"checkpoint", "observation_id":caseID+"/"+phase,
        "case_id":caseID, "phase":phase, "schedule_complete":true,
        "target_index":index, "target_term":term, "leader_commit":committed,
        "leader_match":leader.rn.raft.trk.Progress[1].Match,
        "storage_last_indexes":indexes, "persisted_replicas":persisted,
        "quorum_threshold":threshold, "committed_target":committed>=index,
        "storage_quorum":persisted>=threshold, "drain_turns":turns,
        "held_append_count":len(leader.appendQ),
        "leader_state":leader.rn.BasicStatus().RaftState.String(),
    })
}

func TestAssuranceAsyncCommitSupport(t *testing.T) {
    for _, count := range []int{2,3} {
        t.Run(fmt.Sprintf("voters_%d",count),func(t *testing.T) {
            c := assuranceNewCluster(t,count)
            leader := c.replicas[0].rn
            caseID := fmt.Sprintf("voters-%d",count)
            data := []byte("assurance-proposal/"+caseID)
            if err := leader.Propose(data); err != nil { t.Fatal(err) }
            index, term := leader.raft.raftLog.lastIndex(), leader.BasicStatus().Term
            for _, phase := range []string{"leader_storage_held","all_storage_released"} {
                assuranceEvent(map[string]interface{}{
                    "event":"admitted", "observation_id":caseID+"/"+phase,
                    "case_id":caseID, "target_index":index, "target_term":term,
                    "proposal_admitted":true, "voter_count":count,
                })
                hold := uint64(1)
                if phase=="all_storage_released" { hold=0 }
                turns := c.drain(hold)
                c.observe(caseID,phase,index,term,data,turns)
            }
            assuranceEvent(map[string]interface{}{"event":"scenario_complete","case_id":caseID,
                "final_commit":leader.BasicStatus().Commit,"target_index":index,
                "final_applied":leader.raft.raftLog.applied})
        })
    }
}
