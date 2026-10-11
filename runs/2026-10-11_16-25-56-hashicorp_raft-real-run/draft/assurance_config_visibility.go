package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func caPublish(t *testing.T, ev map[string]interface{}) {
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceConfigurationEntryVisibility repeats the captured upgrade
// scenario (protocol-2 pair plus a protocol-3 joiner) and measures, per node,
// whether the client-visible configuration catches up with the committed
// configuration entry, whether the entry is present in that node's log store
// while the configuration is behind, and how long convergence takes.
func TestAssuranceConfigurationEntryVisibility(t *testing.T) {
	const iterations = 20
	const window = 5 * time.Second

	for it := 0; it < iterations; it++ {
		conf := inmemConfig(t)
		conf.ProtocolVersion = 2
		c := MakeCluster(2, t, conf)

		conf3 := inmemConfig(t)
		conf3.ProtocolVersion = 3
		c1 := MakeClusterNoBootstrap(1, t, conf3)
		c.Merge(c1)
		c.FullyConnect()

		leader := c.Leader()
		if leader == nil {
			t.Fatalf("iteration %d: no leader", it)
		}
		future := leader.AddVoter(c1.rafts[0].localID, c1.rafts[0].localAddr, 0, time.Second)
		if err := future.Error(); err != nil {
			t.Fatalf("iteration %d: add voter: %v", it, err)
		}
		entryIndex := future.Index()
		start := time.Now()

		for _, r := range c.rafts {
			logLast, _ := r.logs.LastIndex()
			caPublish(t, map[string]interface{}{
				"event":                   "config_probe_node_start",
				"iteration":               it,
				"node":                    string(r.localID),
				"entry_index":             entryIndex,
				"applied_at_start":        r.getLastApplied(),
				"log_store_last_at_start": logLast,
			})
		}

		convergedAt := map[ServerID]time.Duration{}
		deadline := start.Add(window)
		for time.Now().Before(deadline) {
			all := true
			for _, r := range c.rafts {
				_, done := convergedAt[r.localID]
				if !done {
					if r.GetConfiguration().Index() >= entryIndex {
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

		for _, r := range c.rafts {
			var entry Log
			entryPresent := r.logs.GetLog(entryIndex, &entry) == nil
			logLast, _ := r.logs.LastIndex()
			cfg := r.GetConfiguration()
			latency, ok := convergedAt[r.localID]
			caPublish(t, map[string]interface{}{
				"event":                      "config_probe_node_result",
				"iteration":                  it,
				"node":                       string(r.localID),
				"entry_index":                entryIndex,
				"converged":                  ok,
				"converged_after_ms":         latency.Milliseconds(),
				"latest_configuration_index": cfg.Index(),
				"visible_servers":            len(cfg.Configuration().Servers),
				"entry_present_in_log":       entryPresent,
				"stale_with_entry":           !ok && entryPresent,
				"log_store_last":             logLast,
				"applied_index":              r.getLastApplied(),
				"commit_index":               r.getCommitIndex(),
				"window_ms":                  window.Milliseconds(),
			})
		}
		c.Close()
	}
}
