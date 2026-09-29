package raft

import (
	"context"
	"encoding/json"
	"fmt"
	pb "go.etcd.io/raft/v3/raftpb"
	"testing"
	"time"
)

type caSyncPeer struct {
	rn          *RawNode
	node        *node
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
	fields["event"] = "read_gate_" + stage
	fields["operation"] = "configuration-first-commit"
	fields["request_context"] = "waiting-before-config"
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
		p.node.ApplyConfChange(cc)
		p.node.Status()
	case pb.EntryConfChangeV2:
		var cc pb.ConfChangeV2
		if err := cc.Unmarshal(e.Data); err != nil {
			n.t.Fatal(err)
		}
		p.node.ApplyConfChange(cc)
		p.node.Status()
	}
}
func (n *caSyncNet) collect(id uint64) bool {
	p := n.p[id]
	p.node.Status()
	if !p.rn.HasReady() {
		return false
	}
	var rd Ready
	select {
	case rd = <-p.node.Ready():
	case <-time.After(5 * time.Second):
		n.t.Fatal("Node Ready did not complete")
	}
	p.node.Status()
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
	// Use the public Node early-Advance optimization and keep actual application ordered.
	p.node.Advance()
	p.node.Status()
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
			if err := n.p[m.To].node.Step(context.Background(), m); err != nil && err != ErrStepPeerNotFound {
				n.t.Fatal(err)
			}
			n.p[m.To].node.Status()
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
func (p *caSyncPeer) waiting(ctx string) bool {
	for _, m := range p.rn.raft.pendingReadIndexMessages {
		if len(m.Entries) == 1 && string(m.Entries[0].Data) == ctx {
			return true
		}
	}
	return false
}
func (p *caSyncPeer) currentCommit() bool {
	term, err := p.rn.raft.raftLog.term(p.rn.raft.raftLog.committed)
	return err == nil && term == p.rn.raft.Term
}
func TestAssuranceReadGateRelease(t *testing.T) {
	n := &caSyncNet{t: t, p: map[uint64]*caSyncPeer{}}
	for id := uint64(1); id <= 4; id++ {
		ms := NewMemoryStorage()
		nd := StartNode(&Config{ID: id, ElectionTick: 10, HeartbeatTick: 1, Storage: ms, MaxSizePerMsg: 1 << 20, MaxInflightMsgs: 16}, []Peer{{ID: 1}, {ID: 2}, {ID: 3}, {ID: 4}}).(*node)
		n.p[id] = &caSyncPeer{rn: nd.rn, node: nd, ms: ms}
		defer nd.Stop()
	}
	n.drain()
	if err := n.p[1].node.Campaign(context.Background()); err != nil {
		t.Fatal(err)
	}
	n.drain()
	p := n.p[2]
	p.delayConfig = true
	cc := pb.ConfChange{Type: pb.ConfChangeRemoveNode, NodeID: 4}
	if err := n.p[1].node.ProposeConfChange(context.Background(), cc); err != nil {
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
	if err := p.node.Campaign(context.Background()); err != nil {
		t.Fatal(err)
	}
	n.drain()
	if p.rn.raft.state != StateLeader {
		t.Fatal("target did not become leader")
	}
	before := p.rn.raft.raftLog.committed
	if err := p.node.ReadIndex(context.Background(), []byte("waiting-before-config")); err != nil {
		t.Fatal(err)
	}
	n.drain()
	caExploreEvent("before_activation", map[string]interface{}{"node": 2, "term": p.rn.raft.Term, "committed": before, "last_index": p.rn.raft.raftLog.lastIndex(), "pending_request": p.waiting("waiting-before-config"), "current_term_committed": p.currentCommit(), "pending_reads": len(p.rn.raft.pendingReadIndexMessages), "old_read_results": p.count("waiting-before-config"), "match_self": p.rn.raft.trk.Progress[2].Match, "match_peer3": p.rn.raft.trk.Progress[3].Match})
	for _, e := range p.delayed {
		n.conf(p, e)
	}
	p.delayed = nil
	p.delayConfig = false
	caExploreEvent("activation", map[string]interface{}{"node": 2, "term": p.rn.raft.Term, "prior_commit": before, "committed": p.rn.raft.raftLog.committed, "current_term_committed": p.currentCommit(), "voters": p.rn.raft.trk.VoterNodes()})
	n.hold = nil
	n.drain()
	for i := 0; i < 3; i++ {
		p.node.Tick()
		for spin := 0; len(p.node.tickc) > 0; spin++ {
			if spin > 2000 {
				t.Fatal("tick not processed")
			}
			p.node.Status()
		}
		p.node.Status()
		n.drain()
	}
	if err := p.node.ReadIndex(context.Background(), []byte("fresh-after-config")); err != nil {
		t.Fatal(err)
	}
	n.drain()
	caExploreEvent("gate_observed", map[string]interface{}{"node": 2, "term": p.rn.raft.Term, "current_term_committed": p.currentCommit(), "pending_request": p.waiting("waiting-before-config"), "committed": p.rn.raft.raftLog.committed, "pending_reads": len(p.rn.raft.pendingReadIndexMessages), "old_read_results": p.count("waiting-before-config"), "fresh_read_results": p.count("fresh-after-config"), "network_pending": len(n.net)})
	if err := p.node.Propose(context.Background(), []byte("later-commit-control")); err != nil {
		t.Fatal(err)
	}
	n.drain()
	caExploreEvent("after_later_proposal", map[string]interface{}{"node": 2, "term": p.rn.raft.Term, "current_term_committed": p.currentCommit(), "pending_request": p.waiting("waiting-before-config"), "committed": p.rn.raft.raftLog.committed, "pending_reads": len(p.rn.raft.pendingReadIndexMessages), "old_read_results": p.count("waiting-before-config"), "fresh_read_results": p.count("fresh-after-config"), "network_pending": len(n.net)})
}
