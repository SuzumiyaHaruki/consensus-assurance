package raft

import (
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
    heldVotes []pb.Message
    currentTerm uint64
    delivered map[uint64]bool
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
            assuranceEmit(map[string]interface{}{"event":"message_dequeued", "request":c.request, "phase":c.phase, "from":msg.From,"to":msg.To,"type":msg.Type.String(),"index":msg.Index,"term":msg.Term})
            if msg.Type==pb.MsgVoteResp && msg.To==1 {
                hs,_,err:=c.stores[msg.From-1].InitialState();if err!=nil {c.t.Fatal(err)}
                if msg.Reject || hs.Term!=msg.Term || hs.Vote!=1 {c.t.Fatal("grant lacks matching completed vote at capture")}
                c.heldVotes=append(c.heldVotes,msg)
                assuranceEmit(map[string]interface{}{"event":"grant_captured","request":c.request,"from":msg.From,"term":msg.Term,"stored_term":hs.Term,"stored_vote":hs.Vote})
            } else {c.deliver(msg)}
            work=true
        }
        if !work { return }
    }
    c.t.Fatal("schedule work bound exhausted")
}


func (c *assuranceStorageCluster) deliver(msg pb.Message) {
    if msg.Type==pb.MsgVoteResp && msg.To==1 && !msg.Reject && msg.Term==c.currentTerm {c.delivered[msg.From]=true}
    assuranceEmit(map[string]interface{}{"event":"actual_delivery","request":c.request,"phase":c.phase,"from":msg.From,"to":msg.To,"type":msg.Type.String(),"term":msg.Term})
    if err:=c.nodes[msg.To-1].Step(msg);err!=nil {c.t.Fatal(err)}
}
func (c *assuranceStorageCluster) release(term,from uint64) {
    for i,m:=range c.heldVotes {
        if m.Term==term && m.From==from {
            c.heldVotes=append(c.heldVotes[:i],c.heldVotes[i+1:]...)
            c.deliver(m)
            return
        }
    }
    c.t.Fatalf("missing actual grant term=%d from=%d",term,from)
}
func TestAssuranceDelayedElectionGrants(t *testing.T) {
    c:=&assuranceStorageCluster{t:t,request:"consecutive-campaigns-1",phase:"bootstrap",delivered:map[uint64]bool{}}
    all:=[3]bool{true,true,true}
    peers:=[]Peer{{ID:1},{ID:2},{ID:3}}
    for i:=0;i<3;i++ {
        c.stores[i]=NewMemoryStorage()
        n,err:=NewRawNode(&Config{ID:uint64(i+1),Storage:c.stores[i],ElectionTick:10,HeartbeatTick:1,MaxSizePerMsg:1<<20,MaxInflightMsgs:8,AsyncStorageWrites:true,Logger:discardLogger})
        if err!=nil {t.Fatal(err)}
        c.nodes[i]=n
        if err=n.Bootstrap(peers);err!=nil {t.Fatal(err)}
    }
    c.drain(all)
    c.phase="first_campaign"
    if err:=c.nodes[0].Campaign();err!=nil {t.Fatal(err)}
    oldTerm:=c.nodes[0].BasicStatus().Term
    c.drain(all)
    if len(c.heldVotes)!=3 || c.nodes[0].BasicStatus().RaftState!=StateCandidate {t.Fatal("first campaign prefix missing")}
    c.phase="second_campaign"
    if err:=c.nodes[0].Campaign();err!=nil {t.Fatal(err)}
    c.currentTerm=c.nodes[0].BasicStatus().Term
    c.drain(all)
    if len(c.heldVotes)!=6 || c.currentTerm!=oldTerm+1 || c.nodes[0].BasicStatus().RaftState!=StateCandidate {t.Fatal("second campaign prefix missing")}
    phases:=[]struct{name string;term,from uint64}{
        {"old_self",oldTerm,1},{"old_peer_2",oldTerm,2},{"old_peer_3",oldTerm,3},
        {"current_self",c.currentTerm,1},{"current_peer_2",c.currentTerm,2},{"current_peer_3",c.currentTerm,3},
    }
    for _,p:=range phases {
        c.phase=p.name
        assuranceEmit(map[string]interface{}{"event":"vote_phase_admitted","request":c.request,"phase":p.name,"node":1,"campaign_term":c.currentTerm,"prefix_ready":true,"released_term":p.term,"released_sender":p.from})
        c.release(p.term,p.from)
        c.drain(all)
        st:=c.nodes[0].BasicStatus()
        assuranceEmit(map[string]interface{}{"event":"election_observed","request":c.request,"phase":p.name,"node":1,"campaign_term":c.currentTerm,"actual_term":st.Term,"role":st.RaftState.String(),"leader":st.RaftState==StateLeader,"current_grants":len(c.delivered),"current_majority":len(c.delivered)>=2,"senders":c.delivered,"held_grants":len(c.heldVotes),"schedule_complete":true})
    }
    assuranceEmit(map[string]interface{}{"event":"history_finished","request":c.request,"campaign_term":c.currentTerm,"held_grants":len(c.heldVotes)})
}
