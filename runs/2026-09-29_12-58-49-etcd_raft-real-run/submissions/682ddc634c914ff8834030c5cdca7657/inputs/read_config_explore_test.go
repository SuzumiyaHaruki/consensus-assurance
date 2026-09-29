package raft

import (
	"encoding/json"
	"fmt"
	pb "go.etcd.io/raft/v3/raftpb"
	"testing"
)

type caSyncPeer struct {
	rn          *RawNode
	ms          *MemoryStorage
	delayed     []pb.Entry
	delayConfig bool
	reads       []ReadState
}
type caSyncNet struct {
	t    *testing.T
	p    map[uint64]*caSyncPeer
	net  []pb.Message
	hold func(pb.Message) bool
}

func caExploreEvent(stage string, fields map[string]interface{}) {
	fields["event"] = "config_read_exploration"
	fields["stage"] = stage
	b, e := json.Marshal(fields)
	if e != nil {
		panic(e)
	}
	fmt.Println("CA_EVENT " + string(b))
}
func (n *caSyncNet) conf(p *caSyncPeer, e pb.Entry) {
	switch e.Type {
	case pb.EntryConfChange:
		var cc pb.ConfChange
		if err := cc.Unmarshal(e.Data); err != nil {
			n.t.Fatal(err)
		}
		p.rn.ApplyConfChange(cc)
	case pb.EntryConfChangeV2:
		var cc pb.ConfChangeV2
		if err := cc.Unmarshal(e.Data); err != nil {
			n.t.Fatal(err)
		}
		p.rn.ApplyConfChange(cc)
	}
}
func (n *caSyncNet) collect(id uint64) bool {
	p := n.p[id]
	if !p.rn.HasReady() {
		return false
	}
	rd := p.rn.Ready()
	if !IsEmptySnap(rd.Snapshot) {
		n.t.Fatal("snapshot outside exploration scope")
	}
	if err := p.ms.Append(rd.Entries); err != nil {
		n.t.Fatal(err)
	}
	if !IsEmptyHardState(rd.HardState) {
		if err := p.ms.SetHardState(rd.HardState); err != nil {
			n.t.Fatal(err)
		}
	}
	for _, e := range rd.CommittedEntries {
		if e.Type == pb.EntryConfChange || e.Type == pb.EntryConfChangeV2 {
			if p.delayConfig {
				p.delayed = append(p.delayed, e)
			} else {
				n.conf(p, e)
			}
		} else if len(p.delayed) > 0 {
			n.t.Fatal("later entry applied before delayed configuration")
		}
	}
	p.reads = append(p.reads, rd.ReadStates...)
	n.net = append(n.net, rd.Messages...)
	// This is the explicit applicability question: Node documents an early
	// Advance optimization; RawNode's own comment says applied and saved.
	// The delayed configuration is completed before any later entry is applied.
	p.rn.Advance(rd)
	return true
}
func (n *caSyncNet) drain() {
	for turn := 0; turn < 2000; turn++ {
		work := false
		for id := uint64(1); id <= 4; id++ {
			if n.collect(id) {
				work = true
			}
		}
		for i, m := range n.net {
			if n.hold != nil && n.hold(m) {
				continue
			}
			n.net = append(n.net[:i], n.net[i+1:]...)
			if err := n.p[m.To].rn.Step(m); err != nil && err != ErrStepPeerNotFound {
				n.t.Fatal(err)
			}
			work = true
			break
		}
		if !work {
			return
		}
	}
	n.t.Fatal("exploration scheduler budget exhausted")
}
func (p *caSyncPeer) count(ctx string) int {
	v := 0
	for _, s := range p.reads {
		if string(s.RequestCtx) == ctx {
			v++
		}
	}
	return v
}
func TestAssuranceConfigReadExplore(t *testing.T) {
	n := &caSyncNet{t: t, p: map[uint64]*caSyncPeer{}}
	for id := uint64(1); id <= 4; id++ {
		ms := NewMemoryStorage()
		rn, err := NewRawNode(&Config{ID: id, ElectionTick: 10, HeartbeatTick: 1, Storage: ms, MaxSizePerMsg: 1 << 20, MaxInflightMsgs: 16})
		if err != nil {
			t.Fatal(err)
		}
		n.p[id] = &caSyncPeer{rn: rn, ms: ms}
		if err := rn.Bootstrap([]Peer{{ID: 1}, {ID: 2}, {ID: 3}, {ID: 4}}); err != nil {
			t.Fatal(err)
		}
	}
	n.drain()
	if err := n.p[1].rn.Campaign(); err != nil {
		t.Fatal(err)
	}
	n.drain()
	p := n.p[2]
	p.delayConfig = true
	cc := pb.ConfChange{Type: pb.ConfChangeRemoveNode, NodeID: 4}
	if err := n.p[1].rn.ProposeConfChange(cc); err != nil {
		t.Fatal(err)
	}
	n.drain()
	if len(p.delayed) != 1 {
		t.Fatalf("missing delayed committed configuration: %d", len(p.delayed))
	}
	caExploreEvent("early_advance", map[string]interface{}{"node": 2, "delayed_config_index": p.delayed[0].Index, "applied": p.rn.raft.raftLog.applied, "committed": p.rn.raft.raftLog.committed, "voters": p.rn.raft.trk.VoterNodes()})
	// Delay the old leader and current-term replication to the removed voter.
	// Vote messages to that voter are still allowed by node 2's old membership.
	n.hold = func(m pb.Message) bool { return m.From == 1 || m.To == 1 || (m.Type == pb.MsgApp && m.To == 4) }
	if err := p.rn.Campaign(); err != nil {
		t.Fatal(err)
	}
	n.drain()
	if p.rn.raft.state != StateLeader {
		t.Fatal("target did not become leader")
	}
	before := p.rn.raft.raftLog.committed
	p.rn.ReadIndex([]byte("waiting-before-config"))
	n.drain()
	caExploreEvent("before_activation", map[string]interface{}{"node": 2, "term": p.rn.raft.Term, "committed": before, "last_index": p.rn.raft.raftLog.lastIndex(), "pending_reads": len(p.rn.raft.pendingReadIndexMessages), "old_read_results": p.count("waiting-before-config"), "match_self": p.rn.raft.trk.Progress[2].Match, "match_peer3": p.rn.raft.trk.Progress[3].Match})
	for _, e := range p.delayed {
		n.conf(p, e)
	}
	p.delayed = nil
	p.delayConfig = false
	caExploreEvent("after_activation", map[string]interface{}{"node": 2, "term": p.rn.raft.Term, "committed": p.rn.raft.raftLog.committed, "pending_reads": len(p.rn.raft.pendingReadIndexMessages), "old_read_results": p.count("waiting-before-config"), "voters": p.rn.raft.trk.VoterNodes()})
	n.hold = nil
	n.drain()
	for i := 0; i < 3; i++ {
		p.rn.Tick()
		n.drain()
	}
	p.rn.ReadIndex([]byte("fresh-after-config"))
	n.drain()
	caExploreEvent("after_heartbeats_and_fresh_read", map[string]interface{}{"node": 2, "committed": p.rn.raft.raftLog.committed, "pending_reads": len(p.rn.raft.pendingReadIndexMessages), "old_read_results": p.count("waiting-before-config"), "fresh_read_results": p.count("fresh-after-config"), "network_pending": len(n.net)})
	if err := p.rn.Propose([]byte("later-commit-control")); err != nil {
		t.Fatal(err)
	}
	n.drain()
	caExploreEvent("after_later_proposal", map[string]interface{}{"node": 2, "committed": p.rn.raft.raftLog.committed, "pending_reads": len(p.rn.raft.pendingReadIndexMessages), "old_read_results": p.count("waiting-before-config"), "fresh_read_results": p.count("fresh-after-config"), "network_pending": len(n.net)})
}
