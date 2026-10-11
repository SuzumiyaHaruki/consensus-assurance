package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func caSend(t *testing.T, ev map[string]interface{}) {
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceInstallSnapshotRewindProbe drives the real replication path with
// repeated isolation/compaction/reconnect rounds and looks for any receiver
// whose applied index moves backwards, which is what an InstallSnapshot older
// than the receiver's applied state would cause. It records the observed
// operands (prior applied index, new applied index, snapshot index, log store
// last index) so a negative or positive result is inspectable.
func TestAssuranceInstallSnapshotRewindProbe(t *testing.T) {
	conf := inmemConfig(t)
	conf.SnapshotInterval = 30 * time.Millisecond
	conf.SnapshotThreshold = 10
	conf.TrailingLogs = 5

	c := MakeCluster(3, t, conf)
	defer c.Close()

	leader := c.Leader()
	if leader == nil {
		t.Fatalf("no leader elected")
	}

	applyN := func(prefix string, n int) {
		var last Future
		for i := 0; i < n; i++ {
			last = leader.Apply([]byte(fmt.Sprintf("%s-%d", prefix, i)), 0)
		}
		if last != nil {
			if err := last.Error(); err != nil {
				t.Fatalf("apply %s: %v", prefix, err)
			}
		}
	}
	lastApplied := func(r *Raft) uint64 { return r.getLastApplied() }
	lastSnap := func(r *Raft) uint64 { i, _ := r.getLastSnapshot(); return i }
	logLast := func(r *Raft) uint64 { i, _ := r.logs.LastIndex(); return i }

	type nodeObs struct {
		id             string
		maxApplied     uint64
		decreases      int
		prevApplied    uint64
		newApplied     uint64
		snapAtDecrease uint64
		logAtDecrease  uint64
		snapChanges    int
		lastSnap       uint64
		installTicks   int
		appliedAtEnd   uint64
	}
	state := map[string]*nodeObs{}
	for _, r := range c.rafts {
		o := &nodeObs{id: string(r.localID), lastSnap: lastSnap(r), maxApplied: lastApplied(r), appliedAtEnd: lastApplied(r)}
		state[o.id] = o
	}

	poll := func(d time.Duration) {
		deadline := time.Now().Add(d)
		for time.Now().Before(deadline) {
			for _, r := range c.rafts {
				o := state[string(r.localID)]
				app := lastApplied(r)
				snap := lastSnap(r)
				ll := logLast(r)
				if snap != o.lastSnap {
					o.snapChanges++
					o.lastSnap = snap
				}
				if snap > ll {
					o.installTicks++
				}
				if app < o.maxApplied {
					o.decreases++
					o.prevApplied = o.maxApplied
					o.newApplied = app
					o.snapAtDecrease = snap
					o.logAtDecrease = ll
				}
				if app > o.maxApplied {
					o.maxApplied = app
				}
				o.appliedAtEnd = app
			}
			time.Sleep(2 * time.Millisecond)
		}
	}

	caSend(t, map[string]interface{}{
		"event":                "probe_start",
		"cluster_size":         len(c.rafts),
		"snapshot_interval_ms": conf.SnapshotInterval.Milliseconds(),
		"snapshot_threshold":   conf.SnapshotThreshold,
		"trailing_logs":        conf.TrailingLogs,
		"leader_id":            string(leader.localID),
	})

	// Per-node admission events carry the identity field the comparisons use.
	for _, r := range c.rafts {
		caSend(t, map[string]interface{}{
			"event":                   "probe_node_start",
			"node":                    string(r.localID),
			"is_leader":               r == leader,
			"applied_at_start":        lastApplied(r),
			"snapshot_index_at_start": lastSnap(r),
			"log_store_last_at_start": logLast(r),
		})
	}

	for round := 0; round < 3; round++ {
		applyN(fmt.Sprintf("warm%d", round), 25)
		time.Sleep(200 * time.Millisecond)

		var victim *Raft
		for _, r := range c.rafts {
			if r != leader && (victim == nil || r.localID < victim.localID) {
				victim = r
			}
		}
		before := lastApplied(victim)
		beforeSnap := lastSnap(victim)
		beforeLog := logLast(victim)
		c.Disconnect(victim.localAddr)
		applyN(fmt.Sprintf("behind%d", round), 60)
		time.Sleep(250 * time.Millisecond)
		c.FullyConnect()

		caSend(t, map[string]interface{}{
			"event":                 "round_start",
			"round":                 round,
			"node":                  string(victim.localID),
			"applied_before":        before,
			"snapshot_before":       beforeSnap,
			"log_store_last_before": beforeLog,
		})
		poll(1200 * time.Millisecond)
	}

	for _, r := range c.rafts {
		o := state[string(r.localID)]
		event := "steady_node_probe_end"
		if o.installTicks > 0 {
			event = "recovered_node_probe_end"
		}
		caSend(t, map[string]interface{}{
			"event":                      event,
			"node":                       o.id,
			"install_signature_seen":     o.installTicks > 0,
			"max_applied_seen":           o.maxApplied,
			"applied_at_end":             lastApplied(r),
			"observed_applied_decrease":  o.decreases > 0,
			"decrease_count":             o.decreases,
			"prior_applied_at_decrease":  o.prevApplied,
			"new_applied_at_decrease":    o.newApplied,
			"snapshot_index_at_decrease": o.snapAtDecrease,
			"log_store_last_at_decrease": o.logAtDecrease,
			"snapshot_index_changes":     o.snapChanges,
			"install_signature_ticks":    o.installTicks,
			"snapshot_index_at_end":      lastSnap(r),
			"log_store_last_at_end":      logLast(r),
		})
	}
}
