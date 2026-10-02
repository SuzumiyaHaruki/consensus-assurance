package raft

import (
    "bytes"
    "encoding/json"
    "fmt"
    "testing"

    pb "go.etcd.io/raft/v3/raftpb"
)

// This adapter models completed stable writes with MemoryStorage. It does not
// model power loss or claim that an in-memory write is physically durable.
type assuranceStorageCluster struct {
    t *testing.T
    nodes [3]*RawNode
    stores [3]*MemoryStorage
    appendQ [3][]pb.Message
    applyQ [3][]pb.Message
    network []pb.Message
    applied [3]uint64
    request string
    phase string
}

func assuranceEmit(v map[string]interface{}) {
    b, err := json.Marshal(v)
    if err != nil { panic(err) }
    fmt.Println("CA_EVENT " + string(b))
}

func (c *assuranceStorageCluster) takeReady(i int) bool {
    n := c.nodes[i]
    if !n.HasReady() { return false }
    rd := n.Ready()
    for _, msg := range rd.Messages {
        switch msg.To {
        case LocalAppendThread:
            if msg.Type != pb.MsgStorageAppend { c.t.Fatal("wrong append target message") }
            c.appendQ[i] = append(c.appendQ[i], msg)
        case LocalApplyThread:
            if msg.Type != pb.MsgStorageApply { c.t.Fatal("wrong apply target message") }
            c.applyQ[i] = append(c.applyQ[i], msg)
        default:
            c.network = append(c.network, msg)
        }
    }
    return true
}

func (c *assuranceStorageCluster) appendOne(i int) bool {
    if len(c.appendQ[i]) == 0 { return false }
    msg := c.appendQ[i][0]
    c.appendQ[i] = c.appendQ[i][1:]
    // Bootstrap does not use snapshots. An unexpected snapshot is a construction
    // gap, not a result of the quorum comparison.
    if msg.Snapshot != nil { c.t.Fatal("unexpected snapshot in fixed configuration history") }
    if err := c.stores[i].Append(msg.Entries); err != nil { c.t.Fatal(err) }
    hs := pb.HardState{Term: msg.Term, Vote: msg.Vote, Commit: msg.Commit}
    if !IsEmptyHardState(hs) {
        if err := c.stores[i].SetHardState(hs); err != nil { c.t.Fatal(err) }
    }
    last, err := c.stores[i].LastIndex()
    if err != nil { c.t.Fatal(err) }
    assuranceEmit(map[string]interface{}{"event":"append_completed", "request":c.request, "phase":c.phase, "node":i+1, "last":last, "responses":len(msg.Responses)})
    c.network = append(c.network, msg.Responses...)
    return true
}

func (c *assuranceStorageCluster) applyOne(i int) bool {
    if len(c.applyQ[i]) == 0 { return false }
    msg := c.applyQ[i][0]
    c.applyQ[i] = c.applyQ[i][1:]
    for _, ent := range msg.Entries {
        if ent.Index != c.applied[i]+1 { c.t.Fatalf("noncontiguous application node=%d index=%d prior=%d",i+1,ent.Index,c.applied[i]) }
        switch ent.Type {
        case pb.EntryConfChange:
            var cc pb.ConfChange
            if err := cc.Unmarshal(ent.Data); err != nil { c.t.Fatal(err) }
            c.nodes[i].ApplyConfChange(cc)
        case pb.EntryConfChangeV2:
            var cc pb.ConfChangeV2
            if err := cc.Unmarshal(ent.Data); err != nil { c.t.Fatal(err) }
            c.nodes[i].ApplyConfChange(cc)
        }
        c.applied[i] = ent.Index
    }
    c.network = append(c.network, msg.Responses...)
    return true
}

// Drain the permitted work, retaining blocked append queues. Termination is
// independent of commitment and of the predicate being checked.
func (c *assuranceStorageCluster) drain(allow [3]bool) {
    for steps:=0; steps<10000; steps++ {
        work := false
        for i:=0; i<3; i++ { if c.takeReady(i) { work=true } }
        for i:=0; i<3; i++ {
            if allow[i] && c.appendOne(i) { work=true }
            if c.applyOne(i) { work=true }
        }
        if len(c.network)>0 {
            msg := c.network[0]
            c.network = c.network[1:]
            if msg.To<1 || msg.To>3 { c.t.Fatalf("unexpected recipient %d",msg.To) }
            assuranceEmit(map[string]interface{}{"event":"message_delivered", "request":c.request, "phase":c.phase, "from":msg.From,"to":msg.To,"type":msg.Type.String(),"index":msg.Index,"term":msg.Term})
            if err := c.nodes[msg.To-1].Step(msg); err != nil { c.t.Fatal(err) }
            work=true
        }
        if !work { return }
    }
    c.t.Fatal("schedule work bound exhausted")
}

func TestAssuranceDelayedLeaderStorageQuorum(t *testing.T) {
    c := &assuranceStorageCluster{t:t,request:"fresh-entry-1",phase:"prefix"}
    peers := []Peer{{ID:1},{ID:2},{ID:3}}
    for i:=0;i<3;i++ {
        c.stores[i]=NewMemoryStorage()
        n,err:=NewRawNode(&Config{ID:uint64(i+1),Storage:c.stores[i],ElectionTick:10,HeartbeatTick:1,MaxSizePerMsg:1<<20,MaxInflightMsgs:8,AsyncStorageWrites:true,Logger:discardLogger})
        if err!=nil { t.Fatal(err) }
        c.nodes[i]=n
        if err=n.Bootstrap(peers);err!=nil { t.Fatal(err) }
    }
    c.drain([3]bool{true,true,true})
    if err:=c.nodes[0].Campaign();err!=nil {t.Fatal(err)}
    c.drain([3]bool{true,true,true})
    r:=c.nodes[0].raft
    if r.state!=StateLeader {t.Fatal("leader prefix not established")}
    prefix:=r.raftLog.lastIndex()
    for i:=0;i<3;i++ {
        last,err:=c.stores[i].LastIndex();if err!=nil {t.Fatal(err)}
        if last!=prefix || c.nodes[i].raft.raftLog.committed!=prefix || c.applied[i]!=prefix || len(c.appendQ[i])!=0 || len(c.applyQ[i])!=0 {t.Fatalf("prefix incomplete at node %d",i+1)}
    }
    payload:=[]byte("independently-observed-proposal")
    if err:=c.nodes[0].Propose(payload);err!=nil {t.Fatal(err)}
    id:=r.raftLog.lastEntryID()
    if id.index!=prefix+1 {t.Fatal("fresh proposal identity not established")}
    phases:=[]struct{name string; allow [3]bool}{
        {"all_appends_held",[3]bool{false,false,false}},
        {"one_follower_completed",[3]bool{false,true,false}},
        {"two_followers_completed",[3]bool{false,true,true}},
        {"leader_completed",[3]bool{true,true,true}},
    }
    for _,p:=range phases {
        c.phase=p.name
        assuranceEmit(map[string]interface{}{"event":"phase_admitted","request":c.request,"phase":p.name,"prefix_index":prefix,"entry_index":id.index,"entry_term":id.term,"prefix_complete":true,"proposal_accepted":true})
        c.drain(p.allow)
        var copies int
        var stored [3]bool
        var last [3]uint64
        var match [3]uint64
        var pending [3]int
        for i:=0;i<3;i++ {
            var err error
            last[i],err=c.stores[i].LastIndex();if err!=nil {t.Fatal(err)}
            if last[i]>=id.index {
                ents,err:=c.stores[i].Entries(id.index,id.index+1,1<<20);if err!=nil {t.Fatal(err)}
                stored[i]=len(ents)==1 && ents[0].Term==id.term && bytes.Equal(ents[0].Data,payload)
                if stored[i] {copies++}
            }
            if pr:=r.trk.Progress[uint64(i+1)];pr!=nil {match[i]=pr.Match}
            pending[i]=len(c.appendQ[i])
        }
        assuranceEmit(map[string]interface{}{"event":"quorum_observed","request":c.request,"phase":p.name,"entry_index":id.index,"entry_term":id.term,"committed":r.raftLog.committed>=id.index,"commit_index":r.raftLog.committed,"append_completed_majority":copies>=2,"stored_copies":copies,"stored":stored,"storage_last":last,"match":match,"pending_appends":pending,"leader_applied":c.applied[0],"leader_term":r.Term,"leader_role":r.state.String(),"schedule_complete":true})
    }
    assuranceEmit(map[string]interface{}{"event":"history_finished","request":c.request,"entry_index":id.index,"leader_commit":r.raftLog.committed,"leader_applied":c.applied[0]})
}
