//go:build !with_tla

package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	"google.golang.org/protobuf/proto"

	pb "go.etcd.io/raft/v3/raftpb"
)

// assuranceNode drives one raft instance the way an application does: it
// persists unstable entries to Storage, steps the messages raft released after
// that persistence (including the self addressed ones) back into raft, applies
// committed entries together with the configuration changes they carry, and
// then advances.
type assuranceNode struct {
	id      uint64
	r       *raft
	ms      *MemoryStorage
	out     []*pb.Message
	applied []*pb.Entry
}

func newAssuranceNode(id uint64, voters []uint64) *assuranceNode {
	ms := NewMemoryStorage()
	ms.snapshot.Metadata.ConfState.Voters = append([]uint64(nil), voters...)
	r := newRaft(&Config{
		ID:              id,
		ElectionTick:    10,
		HeartbeatTick:   1,
		Storage:         ms,
		MaxSizePerMsg:   noLimit,
		MaxInflightMsgs: 256,
	})
	return &assuranceNode{id: id, r: r, ms: ms}
}

func (n *assuranceNode) process() {
	if ents := n.r.raftLog.nextUnstableEnts(); len(ents) > 0 {
		if err := n.ms.Append(ents); err != nil {
			panic(err)
		}
	}
	n.r.raftLog.stableTo(n.r.raftLog.lastEntryID())

	// Messages that raft queued behind persistence may now be released. Self
	// addressed ones (self vote, self append acknowledgement) are stepped back
	// into raft instead of being sent over the link.
	for len(n.r.msgsAfterAppend) > 0 {
		msgs := n.r.msgsAfterAppend
		n.r.msgsAfterAppend = nil
		for _, m := range msgs {
			if m.GetTo() == n.id {
				if err := n.r.Step(m); err != nil {
					panic(err)
				}
				continue
			}
			n.out = append(n.out, m)
		}
	}

	// Apply committed entries, then advance.
	ents := n.r.raftLog.nextCommittedEnts(true)
	for _, e := range ents {
		n.apply(e)
	}
	if len(ents) > 0 {
		n.r.appliedTo(ents[len(ents)-1].GetIndex(), entsSize(ents))
	}

	n.out = append(n.out, n.r.msgs...)
	n.r.msgs = nil
}

func (n *assuranceNode) apply(e *pb.Entry) {
	n.applied = append(n.applied, e)
	switch e.GetType() {
	case pb.EntryConfChange:
		var cc pb.ConfChange
		if err := proto.Unmarshal(e.GetData(), &cc); err != nil {
			panic(err)
		}
		n.r.applyConfChange(cc.AsV2())
	case pb.EntryConfChangeV2:
		var cc pb.ConfChangeV2
		if err := proto.Unmarshal(e.GetData(), &cc); err != nil {
			panic(err)
		}
		n.r.applyConfChange(&cc)
	}
}

type assuranceLink struct {
	from, to uint64
}

type assuranceNet struct {
	nodes   map[uint64]*assuranceNode
	blocked map[assuranceLink]bool
	dropped int
}

func newAssuranceNet(nodes ...*assuranceNode) *assuranceNet {
	nw := &assuranceNet{nodes: map[uint64]*assuranceNode{}, blocked: map[assuranceLink]bool{}}
	for _, n := range nodes {
		nw.nodes[n.id] = n
	}
	return nw
}

func (nw *assuranceNet) block(from, to uint64) { nw.blocked[assuranceLink{from, to}] = true }

// local delivers a locally generated message (proposal, campaign request, read
// index request) to the named node and drains everything it triggers.
func (nw *assuranceNet) local(id uint64, m *pb.Message) {
	m.To = new(id)
	if m.From == nil {
		m.From = new(id)
	}
	nw.deliver(m)
}

func (nw *assuranceNet) deliver(msgs ...*pb.Message) {
	queue := append([]*pb.Message(nil), msgs...)
	for len(queue) > 0 {
		m := queue[0]
		queue = queue[1:]
		if nw.blocked[assuranceLink{m.GetFrom(), m.GetTo()}] {
			nw.dropped++
			continue
		}
		dst := nw.nodes[m.GetTo()]
		if dst == nil {
			continue
		}
		if err := dst.r.Step(m); err != nil && err != ErrProposalDropped {
			panic(err)
		}
		dst.process()
		queue = append(queue, dst.out...)
		dst.out = nil
	}
}

func (nw *assuranceNet) tick(id uint64) {
	n := nw.nodes[id]
	n.r.tick()
	nw.deliver(n.r.msgs...)
	n.r.msgs = nil
}

func assuranceEmit(t *testing.T, ev map[string]any) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatal(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// assuranceCase labels the two scenarios so that events of the same shape stay
// distinguishable by identity rather than by the values under comparison.
const (
	assuranceCaseSingleton = "singleton_config_excluding_leader"
	assuranceCaseMulti     = "multi_voter_config_excluding_leader"
)

func assuranceProp(data string) *pb.Message {
	return &pb.Message{Type: pb.MsgProp.Enum(), Entries: []*pb.Entry{{Data: []byte(data)}}}
}

func assuranceConfChange(spec string) *pb.Message {
	ccs, err := pb.ConfChangesFromString(spec)
	if err != nil {
		panic(err)
	}
	msg, err := confChangeToMsg(&pb.ConfChangeV2{Changes: ccs})
	if err != nil {
		panic(err)
	}
	return msg
}

func assuranceVoters(n *assuranceNode) string {
	return fmt.Sprintf("%v&&%v", n.r.trk.Voters[0].Slice(), n.r.trk.Voters[1].Slice())
}

func assuranceOwnProgress(n *assuranceNode) bool {
	return n.r.trk.Progress[n.id] != nil
}

// TestAssuranceRemovedLeaderSingletonRead drives three nodes, elects node 1,
// removes node 3 and then removes the leader node 1 itself. With the default
// configuration (StepDownOnRemoval=false) node 1 stays leader while the
// configuration collapses to the singleton {2}, which does not contain node 1.
// Node 2 then wins an election for {2} and commits an entry that node 1 never
// sees. Finally node 1 is asked for a linearizable read (ReadOnlySafe, the
// default and "safe" option) through RawNode.ReadIndex's local request path.
func TestAssuranceRemovedLeaderSingletonRead(t *testing.T) {
	n1 := newAssuranceNode(1, []uint64{1, 2, 3})
	n2 := newAssuranceNode(2, []uint64{1, 2, 3})
	n3 := newAssuranceNode(3, []uint64{1, 2, 3})
	nw := newAssuranceNet(n1, n2, n3)

	// Elect node 1 and commit one entry so that node 1 has a committed entry in
	// its term.
	nw.local(1, &pb.Message{Type: pb.MsgHup.Enum()})
	nw.local(1, assuranceProp("w1"))
	assuranceEmit(t, map[string]any{
		"event":          "leader_before_conf_change",
		"case":           assuranceCaseSingleton,
		"node":           1,
		"state":          n1.r.state.String(),
		"term":           n1.r.Term,
		"committed":      n1.r.raftLog.committed,
		"voters":         assuranceVoters(n1),
		"own_progress":   assuranceOwnProgress(n1),
		"read_only_safe": n1.r.readOnly.option == ReadOnlySafe,
	})
	if n1.r.state != StateLeader || !assuranceOwnProgress(n1) {
		t.Errorf("setup: node 1 is %v with own_progress=%v, want a leader that is a member of {1,2,3}",
			n1.r.state, assuranceOwnProgress(n1))
	}

	// Remove node 3, then remove the leader node 1 itself. Both are simple
	// configuration changes proposed by node 1 and applied by every node.
	nw.local(1, assuranceConfChange("r3"))
	nw.local(1, assuranceConfChange("r1"))

	confChangeIndex := n1.r.raftLog.lastEntryID()
	assuranceEmit(t, map[string]any{
		"event":                "leader_after_own_removal",
		"case":                 assuranceCaseSingleton,
		"node":                 1,
		"state":                n1.r.state.String(),
		"term":                 n1.r.Term,
		"committed":            n1.r.raftLog.committed,
		"last_index":           confChangeIndex.index,
		"voters":               assuranceVoters(n1),
		"own_progress":         assuranceOwnProgress(n1),
		"is_singleton":         n1.r.trk.IsSingleton(),
		"step_down_on_removal": n1.r.stepDownOnRemoval,
	})
	if n1.r.state != StateLeader || assuranceOwnProgress(n1) || !n1.r.trk.IsSingleton() {
		t.Errorf("setup: after its own removal node 1 is state=%v own_progress=%v is_singleton=%v, want an unremoved leader of a singleton it is not part of",
			n1.r.state, assuranceOwnProgress(n1), n1.r.trk.IsSingleton())
	}

	// Node 2 is now the only voter; it wins an election for {2} and commits a
	// write that node 1 cannot see (node 1 is not a member of {2}).
	nw.local(2, &pb.Message{Type: pb.MsgHup.Enum()})
	nw.local(2, assuranceProp("w2-after-removal"))
	writeID := n2.r.raftLog.lastEntryID()
	assuranceEmit(t, map[string]any{
		"event":            "node_committed_write",
		"case":             assuranceCaseSingleton,
		"node":             2,
		"state":            n2.r.state.String(),
		"term":             n2.r.Term,
		"committed":        n2.r.raftLog.committed,
		"write_index":      writeID.index,
		"voters":           assuranceVoters(n2),
		"node1_last_index": n1.r.raftLog.lastEntryID().index,
	})
	if n2.r.state != StateLeader || n2.r.Term <= n1.r.Term || n2.r.raftLog.committed < writeID.index {
		t.Errorf("setup: node 2 is state=%v term=%d committed=%d (node 1 term=%d), want a leader at a higher term that committed the write",
			n2.r.state, n2.r.Term, n2.r.raftLog.committed, n1.r.Term)
	}

	// A linearizable read request arrives at node 1 as the local node, which is
	// what RawNode.ReadIndex/Node.ReadIndex produce.
	n1.r.readStates = nil
	n1.r.msgs = nil
	if err := n1.r.Step(&pb.Message{
		Type:    pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("read-after-removal")}},
	}); err != nil {
		t.Fatalf("read index step: %v", err)
	}
	readIndex := uint64(0)
	answered := len(n1.r.readStates) == 1
	if answered {
		readIndex = n1.r.readStates[0].Index
	}
	assuranceEmit(t, map[string]any{
		"event":                             "read_index_request",
		"case":                              assuranceCaseSingleton,
		"node":                              1,
		"read_answered":                     answered,
		"read_index":                        readIndex,
		"request_ctx":                       "read-after-removal",
		"write_index":                       writeID.index,
		"messages_sent":                     len(n1.r.msgs),
		"node2_committed":                   n2.r.raftLog.committed,
		"node1_committed":                   n1.r.raftLog.committed,
		"read_index_behind_committed_write": readIndex < writeID.index,
	})

	// Fair/normal opportunity to repair: node 1 ticks (heartbeat interval) and
	// its heartbeat reaches node 2, which is at a higher term. Observe whether
	// node 1 learns about the new term and whether a repeated read still
	// returns the same stale index.
	nw.tick(1)
	n1.r.readStates = nil
	n1.r.msgs = nil
	if err := n1.r.Step(&pb.Message{
		Type:    pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("read-after-tick")}},
	}); err != nil {
		t.Fatalf("second read index step: %v", err)
	}
	secondIndex := uint64(0)
	if len(n1.r.readStates) == 1 {
		secondIndex = n1.r.readStates[0].Index
	}
	assuranceEmit(t, map[string]any{
		"event":                   "read_index_after_heartbeat_tick",
		"case":                    assuranceCaseSingleton,
		"node":                    1,
		"read_answered":           len(n1.r.readStates) == 1,
		"read_index":              secondIndex,
		"request_ctx":             "read-after-tick",
		"node1_state":             n1.r.state.String(),
		"node1_term":              n1.r.Term,
		"node2_term":              n2.r.Term,
		"node2_committed":         n2.r.raftLog.committed,
		"write_index":             writeID.index,
		"same_stale_index":        secondIndex == readIndex,
		"read_index_still_behind": secondIndex < n2.r.raftLog.committed,
	})
}

// TestAssuranceRemovedLeaderMultiVoterReadControl is the control for the test
// above: the same removal of the leader, but node 3 is replaced by node 4 so
// that the configuration left behind is {2,4} instead of the singleton {2}.
// Node 2 again wins an election and commits a write node 1 cannot see, and node
// 1 again receives a local read index request. The only structural difference
// is that node 1's configuration is not a singleton.
func TestAssuranceRemovedLeaderMultiVoterReadControl(t *testing.T) {
	n1 := newAssuranceNode(1, []uint64{1, 2, 3, 4})
	n2 := newAssuranceNode(2, []uint64{1, 2, 3, 4})
	n3 := newAssuranceNode(3, []uint64{1, 2, 3, 4})
	n4 := newAssuranceNode(4, []uint64{1, 2, 3, 4})
	nw := newAssuranceNet(n1, n2, n3, n4)

	nw.local(1, &pb.Message{Type: pb.MsgHup.Enum()})
	nw.local(1, assuranceProp("w1"))
	nw.local(1, assuranceConfChange("r3"))
	nw.local(1, assuranceConfChange("r1"))

	assuranceEmit(t, map[string]any{
		"event":                "leader_after_own_removal",
		"case":                 assuranceCaseMulti,
		"node":                 1,
		"state":                n1.r.state.String(),
		"term":                 n1.r.Term,
		"committed":            n1.r.raftLog.committed,
		"voters":               assuranceVoters(n1),
		"own_progress":         assuranceOwnProgress(n1),
		"is_singleton":         n1.r.trk.IsSingleton(),
		"step_down_on_removal": n1.r.stepDownOnRemoval,
	})
	if n1.r.state != StateLeader || assuranceOwnProgress(n1) || n1.r.trk.IsSingleton() {
		t.Errorf("control setup: after its own removal node 1 is state=%v own_progress=%v is_singleton=%v, want an unremoved leader of a non-singleton config it is not part of",
			n1.r.state, assuranceOwnProgress(n1), n1.r.trk.IsSingleton())
	}

	// Node 2 needs node 4's vote and acknowledgement for {2,4} quorums.
	nw.local(2, &pb.Message{Type: pb.MsgHup.Enum()})
	nw.local(2, assuranceProp("w2-after-removal"))
	writeID := n2.r.raftLog.lastEntryID()
	assuranceEmit(t, map[string]any{
		"event":            "node_committed_write",
		"case":             assuranceCaseMulti,
		"node":             2,
		"state":            n2.r.state.String(),
		"term":             n2.r.Term,
		"committed":        n2.r.raftLog.committed,
		"write_index":      writeID.index,
		"voters":           assuranceVoters(n2),
		"node1_last_index": n1.r.raftLog.lastEntryID().index,
	})
	if n2.r.state != StateLeader || n2.r.Term <= n1.r.Term || n2.r.raftLog.committed < writeID.index {
		t.Errorf("control setup: node 2 is state=%v term=%d committed=%d (node 1 term=%d), want a leader at a higher term that committed the write",
			n2.r.state, n2.r.Term, n2.r.raftLog.committed, n1.r.Term)
	}

	n1.r.readStates = nil
	n1.r.msgs = nil
	if err := n1.r.Step(&pb.Message{
		Type:    pb.MsgReadIndex.Enum(),
		Entries: []*pb.Entry{{Data: []byte("read-after-removal")}},
	}); err != nil {
		t.Fatalf("read index step: %v", err)
	}
	pending := len(n1.r.readOnly.unconfirmedReads)
	assuranceEmit(t, map[string]any{
		"event":           "read_index_request",
		"case":            assuranceCaseMulti,
		"node":            1,
		"read_answered":   len(n1.r.readStates) == 1,
		"pending_reads":   pending,
		"messages_sent":   len(n1.r.msgs),
		"request_ctx":     "read-after-removal",
		"node2_committed": n2.r.raftLog.committed,
		"node1_committed": n1.r.raftLog.committed,
		"is_singleton":    n1.r.trk.IsSingleton(),
	})

	// Deliver whatever node 1 emitted (heartbeats to {2,4} at the old term) and
	// check whether the read is ever confirmed.
	nw.deliver(n1.r.msgs...)
	n1.r.msgs = nil
	assuranceEmit(t, map[string]any{
		"event":           "read_index_after_delivery",
		"case":            assuranceCaseMulti,
		"node":            1,
		"read_answered":   len(n1.r.readStates) == 1,
		"request_ctx":     "read-after-removal",
		"node2_committed": n2.r.raftLog.committed,
		"node1_committed": n1.r.raftLog.committed,
	})
}
