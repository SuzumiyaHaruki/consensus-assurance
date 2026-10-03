package raft

import (
    "encoding/json"
    "fmt"
    "testing"

    "github.com/lni/dragonboat/v3/config"
    pb "github.com/lni/dragonboat/v3/raftpb"
)

type assuranceReadNode struct {
    peer *Peer
    db *TestLogDB
    applied uint64
}

type assuranceReadNetwork struct {
    t *testing.T
    scenario string
    nodes map[uint64]*assuranceReadNode
    observing bool
    resultCount int
    steps int
}

func assuranceReadEvent(v map[string]interface{}) {
    data, err := json.Marshal(v)
    if err != nil { panic(err) }
    fmt.Println("CA_EVENT " + string(data))
}

func assuranceContext(ctx pb.SystemCtx) string {
    return fmt.Sprintf("%d:%d", ctx.Low, ctx.High)
}

// A storage/application adapter for a crash-free Peer execution. Every Update
// is saved before any outgoing message is made deliverable. Only bootstrap
// configuration entries and the elected leader's no-op are applied.
func (n *assuranceReadNetwork) collect(id uint64) []pb.Message {
    x := n.nodes[id]
    if !x.peer.HasUpdate(true) { return nil }
    ud := x.peer.GetUpdate(true, x.applied)
    if !pb.IsEmptySnapshot(ud.Snapshot) { n.t.Fatal("unexpected snapshot") }
    if err := x.db.Append(ud.EntriesToSave); err != nil { n.t.Fatal(err) }
    if !pb.IsEmptyState(ud.State) { x.db.SetState(ud.State) }
    msgs := append([]pb.Message(nil), ud.Messages...)
    ready := append([]pb.ReadyToRead(nil), ud.ReadyToReads...)
    entries := append([]pb.Entry(nil), ud.CommittedEntries...)
    x.peer.Commit(ud)
    for _, e := range entries {
        if e.Index != x.applied+1 { n.t.Fatalf("nonsequential application %d after %d", e.Index, x.applied) }
        if e.Type == pb.ConfigChangeEntry {
            var cc pb.ConfigChange
            if err := cc.Unmarshal(e.Cmd); err != nil { n.t.Fatal(err) }
            if !cc.Initialize { n.t.Fatal("unexpected non-bootstrap config") }
            x.peer.ApplyConfigChange(cc)
        } else if len(e.Cmd) != 0 { n.t.Fatal("unexpected application payload") }
        x.applied = e.Index
    }
    x.peer.NotifyRaftLastApplied(x.applied)
    if n.observing {
        for _, m := range msgs {
            if m.Type == pb.ReadIndexResp {
                assuranceReadEvent(map[string]interface{}{
                    "event":"wire_response", "scenario":n.scenario,
                    "origin":m.To, "from":m.From, "term":m.Term,
                    "ctx":assuranceContext(pb.SystemCtx{Low:m.Hint, High:m.HintHigh}), "index":m.LogIndex,
                })
            }
        }
        for _, r := range ready {
            n.resultCount++
            assuranceReadEvent(map[string]interface{}{
                "event":"read_result", "scenario":n.scenario, "origin":id,
                "ctx":assuranceContext(r.SystemCtx), "index":r.Index,
                "term":x.peer.raft.term, "applied":x.applied,
            })
        }
    } else if len(ready) != 0 { n.t.Fatal("unexpected readiness during initialization") }
    return msgs
}

func (n *assuranceReadNetwork) deliver(m pb.Message) []pb.Message {
    n.steps++
    if n.steps > 500 { n.t.Fatal("message drain exceeded construction bound") }
    x, ok := n.nodes[m.To]
    if !ok { n.t.Fatalf("unknown destination %d", m.To) }
    x.peer.Handle(m)
    return n.collect(m.To)
}

func (n *assuranceReadNetwork) drain(msgs []pb.Message) {
    q := append([]pb.Message(nil), msgs...)
    for len(q)>0 {
        m := q[0]
        q = q[1:]
        q = append(q, n.deliver(m)...)
    }
}

func assuranceNewReadNetwork(t *testing.T, scenario string) *assuranceReadNetwork {
    n := &assuranceReadNetwork{t:t, scenario:scenario, nodes:make(map[uint64]*assuranceReadNode)}
    addresses := []PeerAddress{{NodeID:1, Address:"n1"}, {NodeID:2, Address:"n2"}, {NodeID:3, Address:"n3"}}
    for id:=uint64(1); id<=3; id++ {
        db := NewTestLogDB().(*TestLogDB)
        p := Launch(config.Config{ClusterID:1, NodeID:id, ElectionRTT:10, HeartbeatRTT:1}, db, nil, addresses, true, true)
        n.nodes[id] = &assuranceReadNode{peer:p, db:db}
        n.drain(n.collect(id))
    }
    for i:=0; i<40 && !n.nodes[1].peer.raft.isLeader(); i++ {
        n.nodes[1].peer.Tick()
        n.drain(n.collect(1))
    }
    r := n.nodes[1].peer.raft
    if !r.isLeader() || !r.hasCommittedEntryAtCurrentTerm() { t.Fatal("election/commit prerequisite not reached") }
    for id:=uint64(1); id<=3; id++ {
        x := n.nodes[id]
        if x.peer.raft.term != r.term || x.peer.raft.leaderID != 1 || x.applied != r.log.committed {
            t.Fatalf("node %d not synchronized after prefix", id)
        }
    }
    assuranceReadEvent(map[string]interface{}{"event":"prefix", "scenario":scenario, "term":r.term, "commit":r.log.committed, "voters":r.numVotingMembers()})
    n.observing = true
    return n
}

// Each origin submits one operation in each fresh network. This makes origin
// independent of the context under comparison, with no association by output
// context or result value.
func (n *assuranceReadNetwork) admit(origin uint64, ctx pb.SystemCtx) []pb.Message {
    n.nodes[origin].peer.ReadIndex(ctx)
    forwarded := n.collect(origin)
    if len(forwarded)!=1 || forwarded[0].Type!=pb.ReadIndex || forwarded[0].To!=1 {
        n.t.Fatal("forwarded-read prerequisite not reached")
    }
    probes := n.deliver(forwarded[0])
    r := n.nodes[1].peer.raft
    s, ok := r.readIndex.pending[ctx]
    if !ok || s.from != origin || s.ctx != ctx { n.t.Fatal("leader admission prerequisite not reached") }
    assuranceReadEvent(map[string]interface{}{
        "event":"read_admitted", "scenario":n.scenario, "origin":origin,
        "ctx":assuranceContext(ctx), "term":r.term, "captured_index":s.index,
        "pending_count":len(r.readIndex.queue),
    })
    return probes
}

func TestAssuranceForwardedReadContexts(t *testing.T) {
    for _, overlap := range []bool{false,true} {
        scenario := "serial"
        if overlap { scenario="overlap" }
        t.Run(scenario, func(t *testing.T) {
            n := assuranceNewReadNetwork(t, scenario)
            first := n.admit(2, pb.SystemCtx{Low:101,High:1001})
            if !overlap { n.drain(first) }
            second := n.admit(3, pb.SystemCtx{Low:202,High:2002})
            // Deliver the later request's probes and all their descendants
            // before delivering any of the earlier request's held probes.
            // No message is fabricated, rewritten, or dropped.
            n.drain(second)
            if overlap { n.drain(first) }
            r := n.nodes[1].peer.raft
            assuranceReadEvent(map[string]interface{}{
                "event":"drained", "scenario":scenario, "term":r.term,
                "pending_count":len(r.readIndex.queue), "result_count":n.resultCount,
                "steps":n.steps,
            })
        })
    }
}
