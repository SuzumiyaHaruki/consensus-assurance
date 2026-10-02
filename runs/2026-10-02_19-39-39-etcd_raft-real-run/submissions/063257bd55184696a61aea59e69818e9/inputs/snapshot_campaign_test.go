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
    holdApply bool
    partition bool
    appData [3][]string
    conf [3]pb.ConfState
    snapshotIndex uint64
    snapshotDelivered bool
    snapshotCompleted bool
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
    if msg.Snapshot != nil {
        if i!=2 || len(c.applyQ[i])!=0 { c.t.Fatal("snapshot installation requires older apply work drained") }
        if err:=c.stores[i].ApplySnapshot(*msg.Snapshot);err!=nil {c.t.Fatal(err)}
        if err:=json.Unmarshal(msg.Snapshot.Data,&c.appData[i]);err!=nil {c.t.Fatal(err)}
        c.applied[i]=msg.Snapshot.Metadata.Index
        c.conf[i]=msg.Snapshot.Metadata.ConfState
        c.snapshotCompleted=true
        assuranceEmit(map[string]interface{}{"event":"snapshot_installed","request":c.request,"snapshot_index":c.applied[i],"payload":c.appData[i]})
    }
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
            c.conf[i]=*c.nodes[i].ApplyConfChange(cc)
        case pb.EntryConfChangeV2:
            var cc pb.ConfChangeV2
            if err := cc.Unmarshal(ent.Data); err != nil { c.t.Fatal(err) }
            c.conf[i]=*c.nodes[i].ApplyConfChange(cc)
        }
        if ent.Type==pb.EntryNormal { c.appData[i]=append(c.appData[i],string(ent.Data)) }
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
            // While snapshot work is held, earlier FIFO append work must still
            // complete so genuine rejection replies can trigger snapshot fallback.
            appendAllowed:=allow[i] || (i==2 && len(c.appendQ[i])>0 && c.appendQ[i][0].Snapshot==nil)
            if appendAllowed && c.appendOne(i) { work=true }
            if !(i==2 && c.holdApply) && c.applyOne(i) { work=true }
        }
        if len(c.network)>0 {
            msg := c.network[0]
            c.network = c.network[1:]
            if msg.To<1 || msg.To>3 { c.t.Fatalf("unexpected recipient %d",msg.To) }
            if c.partition && msg.From<=3 && (msg.From==3 || msg.To==3) { continue }
            assuranceEmit(map[string]interface{}{"event":"message_delivered", "request":c.request, "phase":c.phase, "from":msg.From,"to":msg.To,"type":msg.Type.String(),"index":msg.Index,"term":msg.Term})
            if err := c.nodes[msg.To-1].Step(msg); err != nil { c.t.Fatal(err) }
            if msg.Type==pb.MsgSnap {
                if msg.To!=3 || msg.Snapshot==nil || msg.Snapshot.Metadata.Index!=c.snapshotIndex { c.t.Fatal("unexpected snapshot delivery") }
                c.snapshotDelivered=true
                c.nodes[msg.From-1].ReportSnapshot(msg.To,SnapshotFinish)
            }
            work=true
        }
        if !work { return }
    }
    c.t.Fatal("schedule work bound exhausted")
}


func TestAssuranceSnapshotCampaignBarrier(t *testing.T) {
    c := &assuranceStorageCluster{t:t,request:"snapshot-campaign-1",phase:"prefix"}
    all:=[3]bool{true,true,true}
    held:=[3]bool{true,true,false}
    peers:=[]Peer{{ID:1},{ID:2},{ID:3}}
    for i:=0;i<3;i++ {
        c.stores[i]=NewMemoryStorage()
        n,err:=NewRawNode(&Config{ID:uint64(i+1),Storage:c.stores[i],ElectionTick:10,HeartbeatTick:1,MaxSizePerMsg:1<<20,MaxInflightMsgs:8,AsyncStorageWrites:true,Logger:discardLogger})
        if err!=nil {t.Fatal(err)}
        c.nodes[i]=n
        if err=n.Bootstrap(peers);err!=nil {t.Fatal(err)}
    }
    c.drain(all)
    if err:=c.nodes[0].Campaign();err!=nil {t.Fatal(err)}
    c.drain(all)
    prefix:=c.applied[0]
    for i:=0;i<3;i++ {if c.applied[i]!=prefix || len(c.applyQ[i])!=0 || c.nodes[i].BasicStatus().Commit!=prefix {t.Fatal("incomplete election prefix")}}
    c.holdApply=true
    c.phase="older_normal_apply"
    if err:=c.nodes[0].Propose([]byte("old-normal"));err!=nil {t.Fatal(err)}
    c.drain(all)
    oldIndex:=c.nodes[2].BasicStatus().Commit
    if len(c.applyQ[2])!=1 || oldIndex!=prefix+1 {t.Fatal("older apply batch missing")}
    for _,ent:=range c.applyQ[2][0].Entries {if ent.Type!=pb.EntryNormal {t.Fatal("older batch includes configuration")}}
    c.partition=true
    c.phase="snapshot_prefix"
    for _,payload:=range []string{"new-normal-a","new-normal-b"} {
        if err:=c.nodes[0].Propose([]byte(payload));err!=nil {t.Fatal(err)}
        c.drain(all)
    }
    c.snapshotIndex=c.applied[0]
    data,err:=json.Marshal(c.appData[0]);if err!=nil {t.Fatal(err)}
    snap,err:=c.stores[0].CreateSnapshot(c.snapshotIndex,&c.conf[0],data);if err!=nil {t.Fatal(err)}
    if err=c.stores[0].Compact(c.snapshotIndex);err!=nil {t.Fatal(err)}
    followerLast,err:=c.stores[2].LastIndex();if err!=nil {t.Fatal(err)}
    if c.snapshotIndex<=followerLast || snap.Metadata.Index!=c.nodes[0].BasicStatus().Commit {t.Fatal("snapshot prefix does not require full restore")}
    c.partition=false
    c.phase="snapshot_pending"
    c.nodes[0].Tick()
    c.drain(held)
    if !c.snapshotDelivered {t.Fatal("automatic snapshot path not reached")}
    found:=false
    for _,m:=range c.appendQ[2] {if m.Snapshot!=nil && m.Snapshot.Metadata.Index==c.snapshotIndex {found=true}}
    if !found {t.Fatal("snapshot work missing")}
    assuranceEmit(map[string]interface{}{"event":"producer_prefix","request":c.request,"old_index":oldIndex,"snapshot_index":c.snapshotIndex,"snapshot_term":snap.Metadata.Term,"follower_stored_last":followerLast,"older_apply_batches":len(c.applyQ[2]),"payload":c.appData[0]})
    phases:=[]string{"snapshot_and_apply_held","older_apply_completed","snapshot_completed"}
    for _,phase:=range phases {
        c.phase=phase
        if phase=="older_apply_completed" {c.holdApply=false;c.drain(held)}
        if phase=="snapshot_completed" {c.drain(all)}
        before:=c.nodes[2].BasicStatus()
        assuranceEmit(map[string]interface{}{"event":"campaign_admitted","request":c.request,"phase":phase,"node":3,"snapshot_index":c.snapshotIndex,"snapshot_completed":c.snapshotCompleted,"old_apply_completed":len(c.applyQ[2])==0,"before_term":before.Term,"before_role":before.RaftState.String()})
        if err:=c.nodes[2].Campaign();err!=nil {t.Fatal(err)}
        after:=c.nodes[2].BasicStatus()
        started:=after.Term>before.Term || after.RaftState==StateCandidate || after.RaftState==StatePreCandidate || after.RaftState==StateLeader
        assuranceEmit(map[string]interface{}{"event":"campaign_observed","request":c.request,"phase":phase,"node":3,"snapshot_index":c.snapshotIndex,"snapshot_completed":c.snapshotCompleted,"campaign_started":started,"before_term":before.Term,"after_term":after.Term,"after_role":after.RaftState.String(),"applied":after.Applied,"app_applied":c.applied[2],"call_completed":true})
        if phase=="snapshot_completed" {c.drain(all)} else {c.drain(held)}
    }
    assuranceEmit(map[string]interface{}{"event":"history_finished","request":c.request,"snapshot_index":c.snapshotIndex,"final_term":c.nodes[2].BasicStatus().Term,"final_role":c.nodes[2].BasicStatus().RaftState.String()})
}
