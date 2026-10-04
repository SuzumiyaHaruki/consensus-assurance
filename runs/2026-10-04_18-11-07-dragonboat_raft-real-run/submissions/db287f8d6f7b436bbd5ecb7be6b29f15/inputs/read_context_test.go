package raft

import (
    "encoding/json"
    "fmt"
    "testing"

    "github.com/lni/dragonboat/v3/config"
    pb "github.com/lni/dragonboat/v3/raftpb"
)

func assuranceContext(c pb.SystemCtx) string { return fmt.Sprintf("%d:%d", c.High, c.Low) }
func assuranceEvent(v map[string]interface{}) {
    b, err := json.Marshal(v)
    if err != nil { panic(err) }
    fmt.Println("CA_EVENT " + string(b))
}

type assuranceReadNode struct {
    peer *Peer
    db ILogDB
    applied uint64
}

type assuranceReadNetwork struct {
    t *testing.T
    nodes map[uint64]*assuranceReadNode
    queue []pb.Message
    held []pb.Message
    deferEarly bool
    early pb.SystemCtx
    phase string
    admissions map[uint64]*readStatus
}

// Each update is persisted in the existing memory-backed test LogDB before
// messages are exposed to this crash-free transport. Application is synchronous
// and only bootstrap configuration entries and the elected leader's no-op occur.
func (n *assuranceReadNetwork) harvest(id uint64) {
    x := n.nodes[id]
    for i := 0; x.peer.HasUpdate(true); i++ {
        if i > 100 { n.t.Fatal("update processing did not drain") }
        u := x.peer.GetUpdate(true, x.applied)
        if !pb.IsEmptySnapshot(u.Snapshot) { n.t.Fatal("unexpected snapshot") }
        if err := x.db.Append(u.EntriesToSave); err != nil { n.t.Fatal(err) }
        if !pb.IsEmptyState(u.State) { x.db.SetState(u.State) }
        messages := append([]pb.Message(nil), u.Messages...)
        ready := append([]pb.ReadyToRead(nil), u.ReadyToReads...)
        for _, e := range u.CommittedEntries {
            if e.Index != x.applied+1 { n.t.Fatal("noncontiguous application") }
            if e.Type == pb.ConfigChangeEntry {
                var cc pb.ConfigChange
                if err := cc.Unmarshal(e.Cmd); err != nil { n.t.Fatal(err) }
                if !cc.Initialize || cc.Type != pb.AddNode { n.t.Fatal("unexpected membership mutation") }
                x.peer.ApplyConfigChange(cc)
            } else if e.Type != pb.ApplicationEntry || len(e.Cmd) != 0 {
                n.t.Fatal("unexpected non-noop application")
            }
            x.applied = e.Index
        }
        x.peer.Commit(u)
        x.peer.NotifyRaftLastApplied(x.applied)
        n.queue = append(n.queue, messages...)
        for _, rr := range ready {
            assuranceEvent(map[string]interface{}{
                "event":"read_ready", "scenario":"remote_prefix", "origin":id,
                "context":assuranceContext(rr.SystemCtx), "index":rr.Index,
                "applied":x.applied, "term":x.peer.raft.term, "phase":n.phase,
            })
        }
    }
}

// All phases use this one delivery path. Only genuine early-context heartbeat
// responses are delayed; no message fields are rewritten or forged.
func (n *assuranceReadNetwork) drain() {
    for count := 0; len(n.queue)>0; count++ {
        if count > 10000 { n.t.Fatal("message processing did not drain") }
        m := n.queue[0]
        n.queue = n.queue[1:]
        if n.deferEarly && m.Type == pb.HeartbeatResp && m.Hint == n.early.Low && m.HintHigh == n.early.High {
            n.held = append(n.held,m)
            continue
        }
        x := n.nodes[m.To]
        if x == nil { n.t.Fatal("message addressed outside fixed membership") }
        // Keep references to the actual registered statuses across the handler;
        // confirm mutates their indexes and removes them from the live map.
        var before []*readStatus
        if m.Type == pb.HeartbeatResp && m.To == 1 {
            for _, ctx := range x.peer.raft.readIndex.queue {
                before = append(before, x.peer.raft.readIndex.pending[ctx])
            }
        }
        x.peer.Handle(m)
        if n.phase == "reads" && m.Type == pb.ReadIndex && m.To == 1 {
            ctx := pb.SystemCtx{Low:m.Hint, High:m.HintHigh}
            s, ok := x.peer.raft.readIndex.pending[ctx]
            if !ok || s.from != m.From { n.t.Fatal("read was not registered") }
            if _, exists := n.admissions[s.from]; exists { n.t.Fatal("ambiguous origin identity") }
            n.admissions[s.from] = s
            assuranceEvent(map[string]interface{}{
                "event":"read_admitted", "scenario":"remote_prefix", "origin":s.from,
                "context":assuranceContext(s.ctx), "index":s.index, "term":x.peer.raft.term,
            })
        }
        for _, s := range before {
            if _, ok := x.peer.raft.readIndex.pending[s.ctx]; !ok {
                assuranceEvent(map[string]interface{}{
                    "event":"read_confirmed", "scenario":"remote_prefix", "origin":s.from,
                    "context":assuranceContext(s.ctx), "index":s.index,
                    "term":x.peer.raft.term, "ack_from":m.From,
                    "ack_context":assuranceContext(pb.SystemCtx{Low:m.Hint,High:m.HintHigh}),
                })
            }
        }
        if n.phase == "reads" && m.Type == pb.ReadIndexResp {
            assuranceEvent(map[string]interface{}{
                "event":"response_delivered", "scenario":"remote_prefix", "origin":m.To,
                "context":assuranceContext(pb.SystemCtx{Low:m.Hint,High:m.HintHigh}),
                "index":m.LogIndex, "term":m.Term,
            })
        }
        n.harvest(m.To)
    }
}

func TestAssuranceRemoteReadContext(t *testing.T) {
    n := &assuranceReadNetwork{t:t, nodes:make(map[uint64]*assuranceReadNode),
        phase:"setup", admissions:make(map[uint64]*readStatus)}
    addresses := []PeerAddress{{NodeID:1,Address:"n1"},{NodeID:2,Address:"n2"},{NodeID:3,Address:"n3"}}
    for id:=uint64(1); id<=3; id++ {
        db := NewTestLogDB()
        c := config.Config{ClusterID:41,NodeID:id,ElectionRTT:10,HeartbeatRTT:1,CheckQuorum:true}
        p := Launch(c,db,nil,append([]PeerAddress(nil),addresses...),true,true)
        n.nodes[id]=&assuranceReadNode{peer:p,db:db}
        n.harvest(id)
    }
    n.drain()
    // Only node 1's clock is advanced during election. No node has crashed;
    // all produced messages are processed through the same delivery path.
    for i:=0; i<30 && !n.nodes[1].peer.raft.isLeader(); i++ {
        n.nodes[1].peer.Tick()
        n.harvest(1)
        n.drain()
    }
    leader := n.nodes[1].peer.raft
    if !leader.isLeader() || !leader.hasCommittedEntryAtCurrentTerm() { t.Fatal("current-term committed leader not reached") }
    for id:=uint64(1); id<=3; id++ {
        x:=n.nodes[id]
        if x.peer.raft.leaderID!=1 || x.peer.raft.term!=leader.term || x.applied!=leader.log.committed {
            t.Fatal("stable applied prefix not reached")
        }
    }
    assuranceEvent(map[string]interface{}{"event":"setup", "leader":uint64(1),"term":leader.term,"commit":leader.log.committed})
    n.phase="reads"
    n.early=pb.SystemCtx{Low:101,High:301}
    late:=pb.SystemCtx{Low:202,High:302}
    n.deferEarly=true
    n.nodes[2].peer.ReadIndex(n.early)
    n.harvest(2)
    n.drain()
    if len(n.held)!=2 || len(leader.readIndex.pending)!=1 { t.Fatal("early read overlap prerequisite not reached") }
    n.nodes[3].peer.ReadIndex(late)
    n.harvest(3)
    n.drain()
    // Release all earlier replies regardless of observed contexts/results.
    n.deferEarly=false
    n.queue=append(n.queue,n.held...)
    n.held=nil
    n.drain()
    assuranceEvent(map[string]interface{}{"event":"end", "pending":len(leader.readIndex.pending),"queued":len(n.queue),"held":len(n.held),"admitted":len(n.admissions)})
    // Peer and TestLogDB own no goroutines or open resources. No target state
    // was assigned by the harness; all protocol inputs used Peer methods.
}
