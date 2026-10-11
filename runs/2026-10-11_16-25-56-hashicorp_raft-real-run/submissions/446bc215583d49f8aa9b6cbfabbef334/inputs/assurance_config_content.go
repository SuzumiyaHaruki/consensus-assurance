package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func caSay(t *testing.T, ev map[string]interface{}) {
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceConfigurationContentConvergence repeats the captured upgrade
// scenario and measures, per node, how long the atomically published
// configuration content takes to include the joining voter, and whether any
// node still showed the old membership while holding the configuration entry
// in its own log store. It deliberately avoids the configuration index
// accessor, which is known to return a constant zero.
func TestAssuranceConfigurationContentConvergence(t *testing.T) {
	const rounds = 25
	const window = 3 * time.Second

	for it := 0; it < rounds; it++ {
		conf := inmemConfig(t)
		conf.ProtocolVersion = 2
		c := MakeCluster(2, t, conf)

		conf3 := inmemConfig(t)
		conf3.ProtocolVersion = 3
		joiner := MakeClusterNoBootstrap(1, t, conf3)
		c.Merge(joiner)
		c.FullyConnect()

		leader := c.Leader()
		if leader == nil {
			t.Fatalf("round %d: no leader", it)
		}
		future := leader.AddVoter(joiner.rafts[0].localID, joiner.rafts[0].localAddr, 0, time.Second)
		if err := future.Error(); err != nil {
			t.Fatalf("round %d: add voter: %v", it, err)
		}
		entryIndex := future.Index()
		start := time.Now()

		caSay(t, map[string]interface{}{
			"event":        "config_round_probe_start",
			"iteration":    it,
			"entry_index":  entryIndex,
			"cluster_size": len(c.rafts),
		})

		for _, r := range c.rafts {
			logLast, _ := r.logs.LastIndex()
			caSay(t, map[string]interface{}{
				"event":                 "config_round_start",
				"iteration":             it,
				"node":                  string(r.localID),
				"entry_index":           entryIndex,
				"content_servers_start": len(r.getLatestConfiguration().Servers),
				"log_store_last_start":  logLast,
			})
		}

		convergedAt := map[ServerID]time.Duration{}
		deadline := start.Add(window)
		for time.Now().Before(deadline) {
			all := true
			for _, r := range c.rafts {
				_, done := convergedAt[r.localID]
				if !done {
					if len(r.getLatestConfiguration().Servers) >= 3 {
						convergedAt[r.localID] = time.Since(start)
					} else {
						all = false
					}
				}
			}
			if all {
				break
			}
			time.Sleep(5 * time.Millisecond)
		}

		anyLagWithEntry := false
		var maxWait int64
		type lagObs struct {
			node    string
			servers int
			present bool
			logLast uint64
			applied uint64
			commit  uint64
		}
		var lagging []lagObs
		for _, r := range c.rafts {
			var entry Log
			present := r.logs.GetLog(entryIndex, &entry) == nil
			logLast, _ := r.logs.LastIndex()
			servers := len(r.getLatestConfiguration().Servers)
			lat, ok := convergedAt[r.localID]
			if !ok && present {
				anyLagWithEntry = true
			}
			if lat.Milliseconds() > maxWait {
				maxWait = lat.Milliseconds()
			}
			caSay(t, map[string]interface{}{
				"event":                "config_node_result",
				"iteration":            it,
				"node":                 string(r.localID),
				"converged":            ok,
				"wait_ms":              lat.Milliseconds(),
				"content_servers":      servers,
				"entry_present_in_log": present,
				"log_store_last":       logLast,
				"applied_index":        r.getLastApplied(),
				"commit_index":         r.getCommitIndex(),
			})
			if !ok {
				lagging = append(lagging, lagObs{node: string(r.localID), servers: servers, present: present, logLast: logLast, applied: r.getLastApplied(), commit: r.getCommitIndex()})
			}
		}

		caSay(t, map[string]interface{}{
			"event":              "config_round_end",
			"iteration":          it,
			"entry_index":        entryIndex,
			"all_converged":      len(convergedAt) == len(c.rafts),
			"any_lag_with_entry": anyLagWithEntry,
			"max_wait_ms":        maxWait,
			"window_ms":          window.Milliseconds(),
			"lagging_nodes":      len(lagging),
		})
		c.Close()
	}
}
