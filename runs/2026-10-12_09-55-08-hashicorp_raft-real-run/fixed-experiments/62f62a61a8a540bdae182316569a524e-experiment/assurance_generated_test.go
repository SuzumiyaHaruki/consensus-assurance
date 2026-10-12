package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"testing"
	"time"
)

func caEvent(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

type countFSM struct {
	*MockFSM
	mu       sync.Mutex
	restores int
}

func (c *countFSM) Restore(in io.ReadCloser) error {
	c.mu.Lock()
	c.restores++
	c.mu.Unlock()
	return c.MockFSM.Restore(in)
}

func (c *countFSM) RestoreCount() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.restores
}

func storeBounds(s LogStore) (uint64, uint64) {
	f, _ := s.FirstIndex()
	l, _ := s.LastIndex()
	return f, l
}

// TestAssurance_ReachabilityDivergentSuffix builds a legal multi-node history in
// which a follower ends up holding an earlier-term entry at a later leader's
// snapshot index, then observes whether the rejoin needs any snapshot at all.
func TestAssurance_ReachabilityDivergentSuffix(t *testing.T) {
	conf := inmemConfig(t)
	conf.TrailingLogs = 0
	conf.SnapshotThreshold = 1 << 20
	conf.SnapshotInterval = time.Hour
	conf.HeartbeatTimeout = 1 * time.Second
	conf.ElectionTimeout = 1 * time.Second
	conf.LeaderLeaseTimeout = 1 * time.Second
	conf.CommitTimeout = 10 * time.Millisecond

	var fsms []*countFSM
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers: 5, Bootstrap: true, Conf: conf, LongstopTimeout: 5 * time.Second,
		MakeFSMFunc: func() FSM { f := &countFSM{MockFSM: &MockFSM{}}; fsms = append(fsms, f); return f },
	})
	defer c.Close()

	deadline := time.Now().Add(12 * time.Second)
	for time.Now().Before(deadline) && c.Leader() == nil {
		time.Sleep(10 * time.Millisecond)
	}
	leader := c.Leader()
	if leader == nil {
		t.Fatalf("no leader")
	}
	followers := c.Followers()
	if len(followers) < 4 {
		t.Fatalf("want 4 followers, got %d", len(followers))
	}
	partner := followers[0]
	var others []*Raft
	for _, r := range c.rafts {
		if r != leader && r != partner {
			others = append(others, r)
		}
	}
	if len(others) != 3 {
		t.Fatalf("want 3 others, got %d", len(others))
	}

	// Isolate the leader from the other three, keeping leader<->partner.
	lt := c.trans[c.IndexOf(leader)]
	for _, o := range others {
		lt.Disconnect(o.localAddr)
		c.trans[c.IndexOf(o)].Disconnect(leader.localAddr)
	}

	base := leader.LastIndex()
	for i := 0; i < 5; i++ {
		leader.Apply([]byte(fmt.Sprintf("uncommitted-%d", i)), 0)
	}
	replicated := false
	for d := time.Now().Add(4 * time.Second); time.Now().Before(d); {
		if partner.LastIndex() > base {
			replicated = true
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	pf, pl := storeBounds(c.stores[c.IndexOf(partner)])
	caEvent(map[string]interface{}{"event": "divergent_prefix", "base_index": base,
		"partitioned_leader_last_index": leader.LastIndex(), "partner_last_index": partner.LastIndex(),
		"partner_store_first": pf, "partner_store_last": pl,
		"partner_replicated_uncommitted": replicated, "divergence_index": base + 1})
	if !replicated {
		t.Skipf("precondition not reached: partner last index %d never exceeded base %d", partner.LastIndex(), base)
	}

	// The majority side elects a successor with a shorter log.
	var successor *Raft
	for d := time.Now().Add(12 * time.Second); time.Now().Before(d); {
		for _, o := range others {
			if o.State() == Leader {
				successor = o
			}
		}
		if successor != nil {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if successor == nil {
		t.Skipf("precondition not reached: no successor elected by the majority side")
	}
	// A real command gives the successor's FSM something to snapshot.
	if err := successor.Apply([]byte("post-election"), 5*time.Second).Error(); err != nil {
		t.Fatalf("post-election apply: %v", err)
	}
	for d := time.Now().Add(5 * time.Second); time.Now().Before(d); {
		if successor.AppliedIndex() >= base+1 {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	sf := successor.Snapshot()
	if err := sf.Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	meta, rc, err := sf.Open()
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	snapIdx := meta.Index
	rc.Close()
	snf, snl := storeBounds(c.stores[c.IndexOf(successor)])
	caEvent(map[string]interface{}{"event": "successor_snapshot", "snapshot_index": snapIdx,
		"snapshot_term": meta.Term, "divergence_index": base + 1,
		"successor_term": successor.CurrentTerm(), "old_leader_term": leader.CurrentTerm(),
		"successor_last_index": successor.LastIndex(), "successor_applied_index": successor.AppliedIndex(),
		"successor_store_first": snf, "successor_store_last": snl})

	pidx := c.IndexOf(partner)
	before := fsms[pidx].RestoreCount()
	c.FullyConnect()
	time.Sleep(300 * time.Millisecond)
	early := fsms[pidx].RestoreCount()
	time.Sleep(1200 * time.Millisecond)
	late := fsms[pidx].RestoreCount()
	pf2, pl2 := storeBounds(c.stores[pidx])
	sf2, sl2 := storeBounds(c.stores[c.IndexOf(successor)])
	caEvent(map[string]interface{}{"event": "rejoin_observe", "restores_before": before,
		"restores_early": early, "restores_late": late,
		"partner_applied_index": partner.AppliedIndex(), "partner_last_index": partner.LastIndex(),
		"partner_store_first": pf2, "partner_store_last": pl2,
		"successor_applied_index": successor.AppliedIndex(), "successor_commit_index": successor.CommitIndex(),
		"successor_store_first": sf2, "successor_store_last": sl2})
}
