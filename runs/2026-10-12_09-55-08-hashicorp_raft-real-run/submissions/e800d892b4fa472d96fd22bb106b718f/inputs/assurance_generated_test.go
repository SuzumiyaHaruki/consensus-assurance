package raft

import (
	"io"
	"encoding/json"
	"fmt"
	"sync"
	"testing"
	"time"
)

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

func TestAssurance_ReachabilityDivergentSuffix(t *testing.T) {
	conf := inmemConfig(t)
	conf.TrailingLogs = 0
	conf.SnapshotThreshold = 1 << 20
	conf.SnapshotInterval = time.Hour
	conf.LeaderLeaseTimeout = 1 * time.Second
	conf.ElectionTimeout = 1 * time.Second
	conf.HeartbeatTimeout = 1 * time.Second
	conf.CommitTimeout = 10 * time.Millisecond

	var fsms []*countFSM
	c := MakeClusterCustom(t, &MakeClusterOpts{
		Peers: 5, Bootstrap: true, Conf: conf, LongstopTimeout: 5 * time.Second,
		MakeFSMFunc: func() FSM { f := &countFSM{MockFSM: &MockFSM{}}; fsms = append(fsms, f); return f },
	})
	defer c.Close()

	deadline := time.Now().Add(5 * time.Second)
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
	// Leader appends entries that reach only the partner (no quorum).
	for i := 0; i < 5; i++ {
		leader.Apply([]byte(fmt.Sprintf("uncommitted-%d", i)), 0)
	}
	ok := false
	for d := time.Now().Add(3 * time.Second); time.Now().Before(d); {
		if partner.LastIndex() > base {
			ok = true
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	caEvent(map[string]interface{}{"event": "divergent_prefix", "base_index": base,
		"partner_last_index": partner.LastIndex(), "partner_replicated_uncommitted": ok,
		"leader_last_index": leader.LastIndex()})
	if !ok {
		t.Fatalf("partner never received the uncommitted suffix")
	}

	// The majority side elects a new leader with a shorter log.
	var newLeader *Raft
	for d := time.Now().Add(10 * time.Second); time.Now().Before(d); {
		for _, o := range others {
			if o.State() == Leader {
				newLeader = o
			}
		}
		if newLeader != nil {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if newLeader == nil {
		t.Fatalf("majority side never elected a leader")
	}
	// The new leader must apply a real command before it has anything to
	// snapshot; the resulting snapshot index lands inside the suffix the
	// partner already holds at the older term.
	if err := newLeader.Apply([]byte("post-election"), 5*time.Second).Error(); err != nil {
		t.Fatalf("post-election apply: %v", err)
	}
	for d := time.Now().Add(5 * time.Second); time.Now().Before(d); {
		if newLeader.AppliedIndex() >= base+1 {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	sf := newLeader.Snapshot()
	if err := sf.Error(); err != nil {
		t.Fatalf("snapshot: %v", err)
	}
	meta, rc, err := sf.Open()
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	snapIdx := meta.Index
	rc.Close()
	caEvent(map[string]interface{}{"event": "new_leader_snapshot", "snapshot_index": snapIdx,
		"divergence_index": base + 1, "new_leader_last_index": newLeader.LastIndex(),
		"new_leader_term": newLeader.CurrentTerm(), "old_leader_term": leader.CurrentTerm()})

	pidx := c.IndexOf(partner)
	before := fsms[pidx].RestoreCount()
	c.FullyConnect()
	time.Sleep(300 * time.Millisecond)
	early := fsms[pidx].RestoreCount()
	time.Sleep(1200 * time.Millisecond)
	late := fsms[pidx].RestoreCount()
	caEvent(map[string]interface{}{"event": "rejoin_observe", "restores_before": before,
		"restores_early": early, "restores_late": late,
		"partner_applied_index": partner.AppliedIndex(), "partner_last_index": partner.LastIndex(),
		"new_leader_applied_index": newLeader.AppliedIndex(), "new_leader_commit_index": newLeader.CommitIndex()})

	b, _ := json.Marshal(map[string]interface{}{"event": "done"})
	fmt.Println("CA_EVENT " + string(b))
}
