package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	pb "go.etcd.io/raft/v3/raftpb"
)

type assuranceAppendJob struct {
	seq     uint64
	message pb.Message
}
type assurancePeer struct {
	rn           *RawNode
	storage      *MemoryStorage
	appends      []assuranceAppendJob
	applies      []pb.Message
	nextSeq      uint64
	completedSeq uint64
}
type assuranceCluster struct {
	t       *testing.T
	peers   map[uint64]*assurancePeer
	network []pb.Message
}

func assuranceEmit(event string, fields map[string]interface{}) {
	fields["event"] = event
	fields["operation"] = "delayed-append"
	fields["node"] = uint64(2)
	b, err := json.Marshal(fields)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}
func assuranceRequire(t *testing.T, ok bool, format string, args ...interface{}) {
	t.Helper()
	if !ok {
		t.Fatalf(format, args...)
	}
}
func (c *assuranceCluster) step(m pb.Message) {
	c.t.Helper()
	p := c.peers[m.To]
	assuranceRequire(c.t, p != nil, "unknown recipient %d", m.To)
	if err := p.rn.Step(m); err != nil {
		c.t.Fatalf("Step %s %d->%d: %v", m.Type, m.From, m.To, err)
	}
}
func (c *assuranceCluster) collect(id uint64) bool {
	p := c.peers[id]
	if !p.rn.HasReady() {
		return false
	}
	rd := p.rn.Ready()
	for _, m := range rd.Messages {
		switch m.To {
		case LocalAppendThread:
			p.nextSeq++
			p.appends = append(p.appends, assuranceAppendJob{p.nextSeq, m})
		case LocalApplyThread:
			p.applies = append(p.applies, m)
		default:
			c.network = append(c.network, m)
		}
	}
	return true
}
func (c *assuranceCluster) writeAppend(id uint64) assuranceAppendJob {
	c.t.Helper()
	p := c.peers[id]
	assuranceRequire(c.t, len(p.appends) > 0, "no append job for %d", id)
	j := p.appends[0]
	p.appends = p.appends[1:]
	assuranceRequire(c.t, j.seq == p.completedSeq+1, "append order mismatch")
	m := j.message
	if m.Snapshot != nil && !IsEmptySnap(*m.Snapshot) {
		if err := p.storage.ApplySnapshot(*m.Snapshot); err != nil {
			c.t.Fatal(err)
		}
	}
	if err := p.storage.Append(m.Entries); err != nil {
		c.t.Fatal(err)
	}
	hs := pb.HardState{Term: m.Term, Vote: m.Vote, Commit: m.Commit}
	if !IsEmptyHardState(hs) {
		if err := p.storage.SetHardState(hs); err != nil {
			c.t.Fatal(err)
		}
	}
	p.completedSeq = j.seq
	return j
}
func (c *assuranceCluster) release(id uint64, j assuranceAppendJob, observe func(pb.Message)) {
	for _, m := range j.message.Responses {
		if m.To == id {
			if observe != nil && m.Type == pb.MsgStorageAppendResp {
				observe(m)
			} else {
				c.step(m)
			}
		} else {
			c.network = append(c.network, m)
		}
	}
}
func (c *assuranceCluster) apply(id uint64) bool {
	p := c.peers[id]
	if len(p.applies) == 0 {
		return false
	}
	m := p.applies[0]
	p.applies = p.applies[1:]
	for _, e := range m.Entries {
		switch e.Type {
		case pb.EntryConfChange:
			var cc pb.ConfChange
			if err := cc.Unmarshal(e.Data); err != nil {
				c.t.Fatal(err)
			}
			p.rn.ApplyConfChange(cc)
		case pb.EntryConfChangeV2:
			var cc pb.ConfChangeV2
			if err := cc.Unmarshal(e.Data); err != nil {
				c.t.Fatal(err)
			}
			p.rn.ApplyConfChange(cc)
		}
	}
	for _, resp := range m.Responses {
		c.step(resp)
	}
	return true
}
func (c *assuranceCluster) drain() {
	c.t.Helper()
	for round := 0; round < 1000; round++ {
		work := false
		for id := uint64(1); id <= 3; id++ {
			if c.collect(id) {
				work = true
			}
			if len(c.peers[id].appends) > 0 {
				j := c.writeAppend(id)
				c.release(id, j, nil)
				work = true
			}
			if c.apply(id) {
				work = true
			}
		}
		if len(c.network) > 0 {
			m := c.network[0]
			c.network = c.network[1:]
			c.step(m)
			work = true
		}
		if !work {
			return
		}
	}
	c.t.Fatal("scheduler budget exhausted; no property conclusion")
}
func assuranceToken(t *testing.T, j assuranceAppendJob) pb.Message {
	t.Helper()
	var result pb.Message
	count := 0
	for _, m := range j.message.Responses {
		if m.Type == pb.MsgStorageAppendResp {
			result = m
			count++
		}
	}
	assuranceRequire(t, count == 1, "expected one storage completion, found %d", count)
	return result
}
func (c *assuranceCluster) takeNetwork(kind pb.MessageType, from, to uint64) pb.Message {
	c.t.Helper()
	for i, m := range c.network {
		if m.Type == kind && m.From == from && m.To == to {
			c.network = append(c.network[:i], c.network[i+1:]...)
			return m
		}
	}
	c.t.Fatalf("missing emitted %s %d->%d", kind, from, to)
	return pb.Message{}
}

func TestAssuranceOldAppendCompletion(t *testing.T) {
	c := &assuranceCluster{t: t, peers: make(map[uint64]*assurancePeer)}
	for id := uint64(1); id <= 3; id++ {
		s := NewMemoryStorage()
		rn, err := NewRawNode(&Config{ID: id, ElectionTick: 10, HeartbeatTick: 1, Storage: s,
			MaxSizePerMsg: 1 << 20, MaxInflightMsgs: 16, AsyncStorageWrites: true})
		if err != nil {
			t.Fatal(err)
		}
		c.peers[id] = &assurancePeer{rn: rn, storage: s}
		if err := rn.Bootstrap([]Peer{{ID: 1}, {ID: 2}, {ID: 3}}); err != nil {
			t.Fatal(err)
		}
	}
	c.drain()
	for id := uint64(1); id <= 3; id++ {
		assuranceRequire(t, c.peers[id].rn.raft.raftLog.applied == 3, "bootstrap not applied on %d", id)
	}
	if err := c.peers[1].rn.Campaign(); err != nil {
		t.Fatal(err)
	}
	c.drain()
	leader := c.peers[1].rn.raft
	assuranceRequire(t, leader.state == StateLeader, "campaign did not elect node 1")
	assuranceRequire(t, leader.raftLog.committed == leader.raftLog.lastIndex(), "initial leader entry not committed")
	p := c.peers[2]
	priorTerm := p.rn.raft.Term
	assuranceEmit("prefix_ready", map[string]interface{}{"leader": leader.id, "term": leader.Term,
		"follower_term": priorTerm, "committed": p.rn.raft.raftLog.committed, "applied": p.rn.raft.raftLog.applied})

	if err := c.peers[1].rn.Propose([]byte("completion-context-entry")); err != nil {
		t.Fatal(err)
	}
	c.collect(1)
	// Process the leader's storage work. Delay network delivery to node 3.
	for len(c.peers[1].appends) > 0 {
		j := c.writeAppend(1)
		c.release(1, j, nil)
	}
	c.step(c.takeNetwork(pb.MsgApp, 1, 2))
	c.collect(2)
	assuranceRequire(t, len(p.appends) == 1, "expected one held follower append")
	held := p.appends[0]
	old := assuranceToken(t, held)
	assuranceRequire(t, len(held.message.Entries) > 0 && old.Index > 0 && old.Snapshot == nil, "entry-only token not produced")
	assuranceRequire(t, old.Term == priorTerm, "unexpected issuance term")
	assuranceEmit("token_issued", map[string]interface{}{"batch": held.seq, "issue_term": old.Term,
		"index": old.Index, "log_term": old.LogTerm, "prefix_term": priorTerm, "entry_count": len(held.message.Entries)})

	// The lagging peer campaigns from its real, shorter log. Its genuine vote
	// request advances node 2's term even though node 2 will reject the vote.
	if err := c.peers[3].rn.Campaign(); err != nil {
		t.Fatal(err)
	}
	c.collect(3)
	for len(c.peers[3].appends) > 0 {
		j := c.writeAppend(3)
		c.release(3, j, nil)
	}
	vote := c.takeNetwork(pb.MsgVote, 3, 2)
	c.step(vote)
	now := p.rn.raft.Term
	assuranceRequire(t, now > old.Term, "vote request did not advance term")
	assuranceEmit("context_changed", map[string]interface{}{"issue_term": old.Term, "current_term": now,
		"request_term": vote.Term, "request_index": vote.Index, "request_log_term": vote.LogTerm, "sender": vote.From})
	c.collect(2)
	assuranceRequire(t, len(p.appends) == 2, "term transition did not emit a second storage request")
	freshJob := p.appends[1]
	fresh := assuranceToken(t, freshJob)
	assuranceRequire(t, len(freshJob.message.Entries) == 0, "reconfirmation request unexpectedly appended entries")
	assuranceRequire(t, fresh.Term == now && fresh.Index == old.Index && fresh.LogTerm == old.LogTerm, "tail not reconfirmed in current term")
	rejected := false
	for _, m := range freshJob.message.Responses {
		if m.Type == pb.MsgVoteResp && m.To == 3 && m.Reject {
			rejected = true
		}
	}
	assuranceRequire(t, rejected, "expected actual stale-log vote rejection")

	written := c.writeAppend(2)
	stableTerm, err := p.storage.Term(old.Index)
	if err != nil {
		t.Fatal(err)
	}
	assuranceEmit("batch_written", map[string]interface{}{"batch": written.seq, "issue_term": old.Term,
		"stable_term": stableTerm, "index": old.Index, "completed_seq": p.completedSeq})
	observed := false
	c.release(2, written, func(m pb.Message) {
		observed = true
		before := p.rn.raft.raftLog.unstable.offset
		last := p.rn.raft.raftLog.lastEntryID()
		assuranceRequire(t, m.Term < now && last.index == m.Index && last.term == m.LogTerm && before <= m.Index,
			"discriminator preconditions not reached")
		assuranceEmit("completion_admitted", map[string]interface{}{"batch": written.seq, "completed_seq": p.completedSeq,
			"issue_term": m.Term, "current_term": now, "offset": before, "index": m.Index, "log_term": m.LogTerm,
			"stale": m.Term < now, "identity_matches": last.index == m.Index && last.term == m.LogTerm, "has_snapshot": m.Snapshot != nil})
		c.step(m)
		assuranceEmit("completion_consumed", map[string]interface{}{"batch": written.seq,
			"offset": p.rn.raft.raftLog.unstable.offset, "current_term": p.rn.raft.Term,
			"stale": m.Term < p.rn.raft.Term, "identity_matches": last.index == m.Index && last.term == m.LogTerm,
			"has_snapshot": m.Snapshot != nil, "index": m.Index, "log_term": m.LogTerm})
	})
	assuranceRequire(t, observed, "old completion was not delivered")

	currentWritten := c.writeAppend(2)
	c.release(2, currentWritten, func(m pb.Message) {
		before := p.rn.raft.raftLog.unstable.offset
		c.step(m)
		assuranceEmit("permitted_control", map[string]interface{}{"batch": currentWritten.seq, "issue_term": m.Term,
			"current_term": p.rn.raft.Term, "index": m.Index, "log_term": m.LogTerm, "entries_in_request": len(currentWritten.message.Entries),
			"before_offset": before, "after_offset": p.rn.raft.raftLog.unstable.offset})
	})
	// Finish every delayed worker and network delivery; no tick or eventual
	// election is needed to terminate this finite controlled schedule.
	c.drain()
	assuranceEmit("schedule_complete", map[string]interface{}{"network_pending": len(c.network),
		"append_pending": len(p.appends), "apply_pending": len(p.applies), "offset": p.rn.raft.raftLog.unstable.offset})
}
