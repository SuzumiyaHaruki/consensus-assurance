//go:build dragonboat_audit

// Audit-only randomised multi-node protocol check. Three raft nodes exchange
// messages over a lossy, reordering network; after every step the standard
// safety invariants are checked:
//   - at most one leader per term
//   - log matching: all committed entries agree across nodes (term and payload)
//   - per-node commit index never moves backwards
// It also heals the network at the end and requires a leader and a newly
// committed value to appear.

package raft

import (
	"fmt"
	"math/rand"
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

type delayedMsg struct {
	m   pb.Message
	due int
}

func TestAuditRaftSafetyFuzz(t *testing.T) {
	for _, size := range []int{3, 5} {
		ids := make([]uint64, size)
		for i := range ids {
			ids[i] = uint64(i + 1)
		}
		for seed := int64(1); seed <= 10; seed++ {
			rng := rand.New(rand.NewSource(seed * 104729))
			nodes := make(map[uint64]*raft)
			for _, id := range ids {
				nodes[id] = newTestRaft(id, ids, 10, 1, NewTestLogDB())
			}
			leaders := make(map[uint64]uint64)
			committed := make(map[uint64]uint64)
			type nodeTerm struct {
				node uint64
				term uint64
			}
			votes := make(map[nodeTerm]uint64)
			globalCommit := make(map[uint64]pb.Entry)
			checkedTo := make(map[uint64]uint64)
			var pending []delayedMsg
			var proposals int
			partitioned := make(map[uint64]int)

			drain := func(tick int, drop float64) {
				for _, id := range ids {
					r := nodes[id]
					msgs := r.msgs
					r.msgs = nil
					for _, m := range msgs {
						if rng.Float64() < drop {
							continue
						}
						if partitioned[id] > tick || partitioned[m.To] > tick {
							continue
						}
						due := tick + rng.Intn(3)
						pending = append(pending, delayedMsg{m: m, due: due})
					}
				}
			}
			deliver := func(tick int) {
				var remaining []delayedMsg
				for _, pm := range pending {
					if pm.due > tick {
						remaining = append(remaining, pm)
						continue
					}
					if n, ok := nodes[pm.m.To]; ok {
						n.Handle(pm.m)
					}
				}
				pending = remaining
			}
			check := func(tick int) {
				for _, id := range ids {
					r := nodes[id]
					// election safety: a node never changes its vote within a term,
					// and a leader always voted for itself in its term.
					if r.vote != 0 {
						k := nodeTerm{node: id, term: r.term}
						if prev, ok := votes[k]; ok && prev != r.vote {
							t.Fatalf("seed %d tick %d: node %d changed vote in term %d from %d to %d",
								seed, tick, id, r.term, prev, r.vote)
						}
						votes[k] = r.vote
					}
					if r.state == leader && r.vote != r.nodeID {
						t.Fatalf("seed %d tick %d: node %d is leader in term %d but voted for %d",
							seed, tick, id, r.term, r.vote)
					}
					if r.state == leader {
						if prev, ok := leaders[r.term]; ok && prev != id {
							t.Fatalf("seed %d tick %d: two leaders in term %d: %d and %d",
								seed, tick, r.term, prev, id)
						}
						leaders[r.term] = id
					}
					if r.log.committed < committed[id] {
						t.Fatalf("seed %d tick %d: node %d commit index moved backwards %d -> %d",
							seed, tick, id, committed[id], r.log.committed)
					}
					committed[id] = r.log.committed
					// record every entry this node has committed in a global map
					for idx := checkedTo[id] + 1; idx <= r.log.committed; idx++ {
						ents, err := r.log.getEntries(idx, idx+1, noLimit)
						if err != nil || len(ents) != 1 {
							continue
						}
						e := ents[0]
						if prev, ok := globalCommit[idx]; ok {
							if prev.Term != e.Term || string(prev.Cmd) != string(e.Cmd) {
								t.Fatalf("seed %d tick %d: committed entry %d changed: %+v vs %+v",
									seed, tick, idx, prev, e)
							}
						} else {
							globalCommit[idx] = e
						}
					}
					checkedTo[id] = r.log.committed
				}
				// leader completeness: a leader in term T must hold every entry from
				// an earlier term that was ever committed. Entries from term T (or a
				// newer one) are not required: a stale leader may still believe it is
				// the leader while a newer term is being established.
				for _, id := range ids {
					r := nodes[id]
					if r.state != leader {
						continue
					}
					last := r.log.lastIndex()
					for idx, e := range globalCommit {
						if e.Term >= r.term {
							continue
						}
						if idx > last {
							t.Fatalf("seed %d tick %d: leader %d in term %d is missing committed entry %d",
								seed, tick, id, r.term, idx)
						}
						tm, err := r.log.term(idx)
						if err != nil || tm != e.Term {
							t.Fatalf("seed %d tick %d: leader %d in term %d has term %d at committed index %d, want %d",
								seed, tick, id, r.term, tm, idx, e.Term)
						}
					}
				}
				for i := 0; i < len(ids); i++ {
					for j := i + 1; j < len(ids); j++ {
						a, b := nodes[ids[i]], nodes[ids[j]]
						limit := a.log.committed
						if b.log.committed < limit {
							limit = b.log.committed
						}
						for idx := uint64(1); idx <= limit; idx++ {
							ta, erra := a.log.term(idx)
							tb, errb := b.log.term(idx)
							if erra != nil || errb != nil {
								continue
							}
							if ta != tb {
								t.Fatalf("seed %d tick %d: log mismatch at %d between %d (t%d) and %d (t%d)",
									seed, tick, idx, ids[i], ta, ids[j], tb)
							}
							ea, e := a.log.getEntries(idx, idx+1, noLimit)
							if e != nil || len(ea) != 1 {
								continue
							}
							eb, e := b.log.getEntries(idx, idx+1, noLimit)
							if e != nil || len(eb) != 1 {
								continue
							}
							if string(ea[0].Cmd) != string(eb[0].Cmd) ||
								ea[0].Type != eb[0].Type {
								t.Fatalf("seed %d tick %d: committed entry %d differs between nodes %d and %d",
									seed, tick, idx, ids[i], ids[j])
							}
						}
					}
				}
			}

			for tick := 1; tick <= 3000; tick++ {
				if tick%150 == 0 {
					victim := ids[rng.Intn(len(ids))]
					partitioned[victim] = tick + 60
				}
				for _, id := range ids {
					nodes[id].Handle(pb.Message{Type: pb.LocalTick})
				}
				drain(tick, 0.2)
				deliver(tick)
				drain(tick, 0.2)
				// occasionally propose to a leader
				if rng.Intn(4) == 0 {
					for _, id := range ids {
						if nodes[id].state == leader {
							nodes[id].Handle(pb.Message{
								Type: pb.Propose,
								From: id,
								Entries: []pb.Entry{{
									Type: pb.ApplicationEntry,
									Cmd:  []byte(fmt.Sprintf("v-%d-%d", seed, proposals)),
								}},
							})
							proposals++
							break
						}
					}
				}
				if tick%10 == 0 {
					check(tick)
				}
			}
			check(3000)
			maxCommitted := uint64(0)
			for _, id := range ids {
				if nodes[id].log.committed > maxCommitted {
					maxCommitted = nodes[id].log.committed
				}
			}
			if maxCommitted == 0 || len(leaders) < 2 {
				t.Fatalf("seed %d: fuzz did not make progress (committed %d, %d leader terms)",
					seed, maxCommitted, len(leaders))
			}
			t.Logf("size %d seed %d: %d proposals, %d leader terms, max committed %d",
				size, seed, proposals, len(leaders), maxCommitted)
			// heal the network: deliver everything and stop dropping
			var leaderID uint64
			for i := 0; i < 3000 && leaderID == 0; i++ {
				for _, id := range ids {
					nodes[id].Handle(pb.Message{Type: pb.LocalTick})
				}
				drain(3000+i, 0)
				deliver(3000 + i)
				drain(3000+i, 0)
				for _, id := range ids {
					if nodes[id].state == leader {
						leaderID = id
					}
				}
			}
			if leaderID == 0 {
				t.Fatalf("seed %d: no leader elected after healing the network", seed)
			}
			before := nodes[leaderID].log.committed
			nodes[leaderID].Handle(pb.Message{
				Type:    pb.Propose,
				From:    leaderID,
				Entries: []pb.Entry{{Type: pb.ApplicationEntry, Cmd: []byte("healed")}},
			})
			for i := 0; i < 3000 && nodes[leaderID].log.committed == before; i++ {
				for _, id := range ids {
					nodes[id].Handle(pb.Message{Type: pb.LocalTick})
				}
				drain(5000+i, 0)
				deliver(5000 + i)
				drain(5000+i, 0)
				if nodes[leaderID].state != leader {
					t.Fatalf("seed %d: leader lost leadership while healing", seed)
				}
			}
			if nodes[leaderID].log.committed == before {
				t.Fatalf("seed %d: proposal not committed after healing (committed %d)",
					seed, before)
			}
			check(9000)
		}
	}
}
