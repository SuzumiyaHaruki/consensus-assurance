package raft

import (
    "encoding/json"
    "fmt"
    "testing"

    "github.com/lni/dragonboat/v3/config"
    pb "github.com/lni/dragonboat/v3/raftpb"
)

func assuranceReadEvent(t *testing.T, v map[string]interface{}) {
    t.Helper()
    b, err := json.Marshal(v)
    if err != nil { t.Fatal(err) }
    fmt.Println("CA_EVENT " + string(b))
}

func assuranceReadContext(c pb.SystemCtx) string {
    return fmt.Sprintf("%d:%d", c.Low, c.High)
}

// All Peer inputs, outputs, persistence and observation are owned by this
// test goroutine. The transport policy is fixed before either read starts.
func TestAssuranceForwardedReadContext(t *testing.T) {
    const scenario = "coalesced_distinct_origins"
    type node struct {
        p *Peer
        db ILogDB
        applied uint64
        ready []pb.ReadyToRead
    }
    nodes := map[uint64]*node{}
    addresses := []PeerAddress{{NodeID:1, Address:"n1"}, {NodeID:2, Address:"n2"}, {NodeID:3, Address:"n3"}}
    for id := uint64(1); id <= 3; id++ {
        db := NewTestLogDB()
        cfg := config.Config{ClusterID:1, NodeID:id, ElectionRTT:10, HeartbeatRTT:1, CheckQuorum:true}
        nodes[id] = &node{p:Launch(cfg, db, nil, append([]PeerAddress(nil), addresses...), true, true), db:db}
    }
    var queue []pb.Message
    var responses []pb.Message
    var sequence uint64
    ctxA := pb.SystemCtx{Low:101, High:30}
    ctxB := pb.SystemCtx{Low:202, High:30}
    droppedA := 0
    stage := "bootstrap"
    // Consume the real Peer Update interface. Persist entries and state before
    // delivering any message (a permitted conservative ordering of replication).
    collect := func(id uint64) {
        n := nodes[id]
        ud := n.p.GetUpdate(true, n.applied)
        if !pb.IsEmptySnapshot(ud.Snapshot) { t.Fatal("unexpected snapshot") }
        if err := n.db.Append(ud.EntriesToSave); err != nil { t.Fatal(err) }
        if !pb.IsEmptyState(ud.State) { n.db.SetState(ud.State) }
        for _, e := range ud.CommittedEntries {
            if e.Index != n.applied+1 { t.Fatalf("nonsequential application node=%d index=%d applied=%d", id,e.Index,n.applied) }
            if e.Type == pb.ConfigChangeEntry {
                var cc pb.ConfigChange
                if err := cc.Unmarshal(e.Cmd); err != nil { t.Fatal(err) }
                if !cc.Initialize { t.Fatal("unexpected nonbootstrap configuration") }
                n.p.ApplyConfigChange(cc)
            } else if len(e.Cmd) != 0 { t.Fatal("unexpected application command") }
            n.applied = e.Index
        }
        n.ready = append(n.ready, ud.ReadyToReads...)
        for _, m := range ud.Messages {
            sequence++
            assuranceReadEvent(t, map[string]interface{}{"event":"wire_emitted", "scenario":scenario,"sequence":sequence,"stage":stage,"from":m.From,"to":m.To,"type":m.Type.String(),"term":m.Term,"context":assuranceReadContext(pb.SystemCtx{Low:m.Hint,High:m.HintHigh})})
            queue = append(queue,m)
            if m.Type == pb.ReadIndexResp { responses = append(responses,m) }
        }
        n.p.Commit(ud)
        n.p.NotifyRaftLastApplied(n.applied)
    }
    // FIFO among all surviving messages is stronger than the per-link order
    // needed here. Only A's heartbeat replies are lost. B's replies can be
    // held temporarily to observe admission, without moving any queue item.
    pump := func(holdB bool) {
        steps := 0
        for len(queue) > 0 {
            steps++
            if steps > 500 { t.Fatal("unexpected nonquiescent message cascade") }
            m := queue[0]
            c := pb.SystemCtx{Low:m.Hint,High:m.HintHigh}
            if holdB && m.Type == pb.HeartbeatResp && c == ctxB { return }
            queue = queue[1:]
            if m.Type == pb.HeartbeatResp && c == ctxA {
                droppedA++
                assuranceReadEvent(t,map[string]interface{}{"event":"wire_lost","scenario":scenario,"from":m.From,"to":m.To,"context":assuranceReadContext(c)})
                continue
            }
            n, ok := nodes[m.To]
            if !ok { t.Fatalf("unknown destination %d",m.To) }
            n.p.Handle(m)
            collect(m.To)
        }
    }
    for id:=uint64(1);id<=3;id++ { collect(id) }
    pump(false)
    stage = "election"
    // Ticks, not a direct role assignment, cause node 1 to campaign. Other
    // nodes process every produced message but have no election tick yet.
    for i:=0;i<30 && !nodes[1].p.raft.isLeader();i++ {
        nodes[1].p.Tick(); collect(1); pump(false)
    }
    leader := nodes[1].p.raft
    if !leader.isLeader() || !leader.hasCommittedEntryAtCurrentTerm() { t.Fatal("current-term leader prefix not reached") }
    for id:=uint64(1);id<=3;id++ {
        n:=nodes[id]
        collect(id)
        if n.applied != leader.log.committed || n.p.raft.term != leader.term || n.p.raft.leaderID != 1 { t.Fatalf("node %d has not reached common prefix",id) }
        if len(n.p.raft.remotes)!=3 { t.Fatal("unexpected membership") }
    }
    pump(false)
    term := leader.term
    assuranceReadEvent(t,map[string]interface{}{"event":"prepared","scenario":scenario,"leader":uint64(1),"term":term,"commit":leader.log.committed,"all_applied":true,"queue_empty":len(queue)==0})
    stage = "reads"
    nodes[2].p.ReadIndex(ctxA); collect(2); pump(false)
    if droppedA != 2 || len(leader.readIndex.pending)!=1 { t.Fatalf("first admission/loss premise not reached: dropped=%d pending=%d",droppedA,len(leader.readIndex.pending)) }
    nodes[3].p.ReadIndex(ctxB); collect(3); pump(true)
    if len(leader.readIndex.pending)!=2 || len(leader.readIndex.queue)!=2 || len(responses)!=0 { t.Fatal("overlapping read prefix not reached") }
    for _, input := range []struct{origin uint64; ctx pb.SystemCtx}{{2,ctxA},{3,ctxB}} {
        st, ok := leader.readIndex.pending[input.ctx]
        if !ok || st.from != input.origin || st.ctx != input.ctx { t.Fatal("admission identity mismatch") }
        assuranceReadEvent(t,map[string]interface{}{"event":"read_admitted","scenario":scenario,"origin":input.origin,"expected_context":assuranceReadContext(input.ctx),"term":leader.term,"pending":len(leader.readIndex.pending),"dropped_first_replies":droppedA})
    }
    stage = "confirmation"
    pump(false)
    for id:=uint64(1);id<=3;id++ { collect(id) }
    pump(false)
    if leader.term != term || !leader.isLeader() { t.Fatal("authority changed during read scenario") }
    assuranceReadEvent(t,map[string]interface{}{"event":"drained","scenario":scenario,"pending":len(leader.readIndex.pending),"queue_length":len(queue),"responses":len(responses),"term":leader.term})
    // Each requesting origin has exactly one request, so destination supplies
    // independent identity; no association is made using the compared context.
    for origin:=uint64(2);origin<=3;origin++ {
        var rs []pb.Message
        for _, m := range responses { if m.To==origin { rs=append(rs,m) } }
        ready := nodes[origin].ready
        if len(rs)!=1 || len(ready)!=1 { t.Fatalf("ambiguous/missing output for origin %d: responses=%d ready=%d",origin,len(rs),len(ready)) }
        m:=rs[0]
        assuranceReadEvent(t,map[string]interface{}{"event":"read_reply","scenario":scenario,"origin":origin,"actual_context":assuranceReadContext(pb.SystemCtx{Low:m.Hint,High:m.HintHigh}),"received_context":assuranceReadContext(ready[0].SystemCtx),"reply_index":m.LogIndex,"received_index":ready[0].Index,"applied":nodes[origin].applied,"term":m.Term,"pending_after":len(leader.readIndex.pending)})
    }
    // There are no goroutines, transports, waiters, or persistent resources to
    // close. Every surviving message and each Peer Update was consumed.
}
