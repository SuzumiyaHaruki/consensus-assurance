package raft

import (
	"encoding/json"
	"fmt"
	"testing"

	"github.com/lni/dragonboat/v3/config"
	pb "github.com/lni/dragonboat/v3/raftpb"
)

// This scheduler owns all peers and buffers synchronously. It changes delivery,
// never protocol state. A message is released only after its producer's update
// has been saved to the in-memory test store.
type assuranceReadCluster struct {
	t         *testing.T
	scenario  string
	peers     map[uint64]*Peer
	stores    map[uint64]ILogDB
	applied   map[uint64]uint64
	queue     []pb.Message
	ready     map[uint64][]pb.ReadyToRead
	responses map[uint64][]pb.Message
	trace     bool
	delivered int
	lost      int
}

func assuranceReadEvent(v map[string]interface{}) {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func (c *assuranceReadCluster) collect(id uint64) {
	p := c.peers[id]
	if !p.HasUpdate(true) {
		return
	}
	ud := p.GetUpdate(true, c.applied[id])
	if !pb.IsEmptySnapshot(ud.Snapshot) {
		c.t.Fatal("unexpected snapshot")
	}
	if err := c.stores[id].Append(ud.EntriesToSave); err != nil {
		c.t.Fatal(err)
	}
	if !pb.IsEmptyState(ud.State) {
		c.stores[id].SetState(ud.State)
	}
	// Preserve outputs before Commit releases their backing buffers.
	messages := append([]pb.Message(nil), ud.Messages...)
	c.ready[id] = append(c.ready[id], ud.ReadyToReads...)
	entries := append([]pb.Entry(nil), ud.CommittedEntries...)
	p.Commit(ud)
	for _, e := range entries {
		if e.Type == pb.ConfigChangeEntry {
			var cc pb.ConfigChange
			if err := cc.Unmarshal(e.Cmd); err != nil {
				c.t.Fatal(err)
			}
			p.ApplyConfigChange(cc)
		}
		c.applied[id] = e.Index
	}
	p.NotifyRaftLastApplied(c.applied[id])
	for _, m := range messages {
		if c.trace {
			assuranceReadEvent(map[string]interface{}{
				"event": "produced", "scenario": c.scenario,
				"type": m.Type.String(), "from": m.From, "to": m.To,
				"term": m.Term, "low": m.Hint, "high": m.HintHigh,
				"index": m.LogIndex, "commit": m.Commit,
			})
		}
		c.queue = append(c.queue, m)
	}
}

func (c *assuranceReadCluster) drain(dropHeartbeat bool) {
	for count := 0; len(c.queue) > 0; count++ {
		if count > 10000 {
			c.t.Fatal("message drain did not quiesce")
		}
		m := c.queue[0]
		c.queue = c.queue[1:]
		if dropHeartbeat && m.Type == pb.Heartbeat {
			c.lost++
			assuranceReadEvent(map[string]interface{}{
				"event": "lost_heartbeat", "scenario": c.scenario,
				"from": m.From, "to": m.To, "term": m.Term,
				"low": m.Hint, "high": m.HintHigh,
			})
			continue
		}
		if m.Type == pb.ReadIndexResp {
			c.responses[m.To] = append(c.responses[m.To], m)
		}
		c.peers[m.To].Handle(m)
		c.delivered++
		c.collect(m.To)
	}
}

func newAssuranceReadCluster(t *testing.T, scenario string) *assuranceReadCluster {
	c := &assuranceReadCluster{
		t: t, scenario: scenario, peers: make(map[uint64]*Peer),
		stores: make(map[uint64]ILogDB), applied: make(map[uint64]uint64),
		ready: make(map[uint64][]pb.ReadyToRead), responses: make(map[uint64][]pb.Message),
	}
	for id := uint64(1); id <= 3; id++ {
		c.stores[id] = NewTestLogDB()
		cfg := config.Config{ClusterID: 1, NodeID: id, ElectionRTT: 10, HeartbeatRTT: 1, CheckQuorum: true}
		addresses := []PeerAddress{{NodeID: 1, Address: "one"}, {NodeID: 2, Address: "two"}, {NodeID: 3, Address: "three"}}
		c.peers[id] = Launch(cfg, c.stores[id], nil, addresses, true, true)
		c.collect(id)
	}
	c.drain(false)
	// Only node 1's clock needs to expire to produce the initial election.
	for i := 0; i < 30 && !c.peers[1].raft.isLeader(); i++ {
		c.peers[1].Tick()
		c.collect(1)
		c.drain(false)
	}
	if !c.peers[1].raft.isLeader() || !c.peers[1].raft.hasCommittedEntryAtCurrentTerm() {
		t.Fatal("normal election/current-term commit prefix failed")
	}
	for id := uint64(1); id <= 3; id++ {
		p := c.peers[id]
		assuranceReadEvent(map[string]interface{}{
			"event": "prefix", "scenario": scenario, "node": id,
			"leader": p.raft.leaderID, "term": p.raft.term,
			"committed": p.raft.log.committed, "applied": c.applied[id],
			"voters": len(p.raft.remotes),
		})
		if p.raft.leaderID != 1 {
			t.Fatal("follower has no established leader")
		}
	}
	c.trace = true
	return c
}

func TestAssuranceReadIndexContext(t *testing.T) {
	for _, scenario := range []string{"deliver_first_round", "lose_first_round"} {
		t.Run(scenario, func(t *testing.T) {
			c := newAssuranceReadCluster(t, scenario)
			// One request per follower gives an operation identity independent
			// of the returned context. Both fields differ across requests.
			inputs := map[uint64]pb.SystemCtx{
				2: {Low: 1001, High: 31},
				3: {Low: 2002, High: 32},
			}
			for _, origin := range []uint64{2, 3} {
				ctx := inputs[origin]
				assuranceReadEvent(map[string]interface{}{
					"event": "admitted", "scenario": scenario, "origin": origin,
					"input_low": ctx.Low, "input_high": ctx.High,
					"leader": c.peers[origin].raft.leaderID,
					"term":   c.peers[origin].raft.term,
				})
				c.peers[origin].ReadIndex(ctx)
				c.collect(origin)
				c.drain(scenario == "lose_first_round" && origin == 2)
				pending := c.peers[1].raft.readIndex
				statuses := []map[string]interface{}{}
				for _, key := range pending.queue {
					s := pending.pending[key]
					statuses = append(statuses, map[string]interface{}{
						"origin": s.from, "low": s.ctx.Low, "high": s.ctx.High,
						"index": s.index, "confirmations": len(s.confirmed),
					})
				}
				assuranceReadEvent(map[string]interface{}{
					"event": "pending", "scenario": scenario, "after_origin": origin,
					"statuses": statuses, "queue_length": len(pending.queue),
					"lost": c.lost,
				})
			}
			// Recover all links. Run a finite number of normal heartbeat rounds.
			for i := 0; i < 12; i++ {
				for id := uint64(1); id <= 3; id++ {
					c.peers[id].Tick()
					c.collect(id)
					c.drain(false)
				}
			}
			for _, origin := range []uint64{2, 3} {
				// Emit every result without filtering on either context field.
				for ordinal, r := range c.ready[origin] {
					assuranceReadEvent(map[string]interface{}{
						"event": "returned", "scenario": scenario, "origin": origin,
						"ordinal": ordinal, "output_low": r.SystemCtx.Low,
						"output_high": r.SystemCtx.High, "index": r.Index,
						"applied": c.applied[origin],
					})
				}
				assuranceReadEvent(map[string]interface{}{
					"event": "endpoint", "scenario": scenario, "origin": origin,
					"ready_count":     len(c.ready[origin]),
					"response_count":  len(c.responses[origin]),
					"leader_pending":  len(c.peers[1].raft.readIndex.pending),
					"queued_messages": len(c.queue), "lost_heartbeats": c.lost,
					"leader": c.peers[origin].raft.leaderID,
					"term":   c.peers[origin].raft.term, "delivered": c.delivered,
				})
			}
		})
	}
}
