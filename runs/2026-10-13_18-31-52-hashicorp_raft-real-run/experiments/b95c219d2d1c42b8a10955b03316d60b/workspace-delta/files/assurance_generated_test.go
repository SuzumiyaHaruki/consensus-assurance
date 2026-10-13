package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func assuranceEmit(t *testing.T, fields map[string]interface{}) {
	b, err := json.Marshal(fields)
	if err != nil {
		return
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssurance_AddVoterConfigVisibility observes, for a stable two-voter
// cluster, whether the configuration entry appended by AddVoter becomes
// visible in the configuration reported by the pre-existing voters, and how
// long any disagreement lasts. The new server is a real, unbootstrapped
// raft instance merged into the same in-process network.
func TestAssurance_AddVoterConfigVisibility(t *testing.T) {
	c := MakeCluster(2, t, nil)
	defer c.Close()

	c1 := MakeClusterNoBootstrap(1, t, nil)
	defer c1.Close()

	c.Merge(c1)
	c.FullyConnect()

	leader := c.Leader()
	newNode := c1.rafts[0]

	assuranceEmit(t, map[string]interface{}{
		"event":     "setup",
		"leader_id": string(leader.localID),
		"new_id":    string(newNode.localID),
	})

	start := time.Now()
	future := leader.AddVoter(newNode.localID, newNode.localAddr, 0, 0)
	err := future.Error()
	assuranceEmit(t, map[string]interface{}{
		"event":      "addvoter_result",
		"elapsed_ms": time.Since(start).Milliseconds(),
		"err":        fmt.Sprintf("%v", err),
		"index":      future.Index(),
	})

	deadline := time.Now().Add(3 * time.Second)
	probe := 0
	for time.Now().Before(deadline) {
		for _, r := range c.rafts {
			cfg := c.getConfiguration(r)
			voters := 0
			for _, s := range cfg.Servers {
				if s.Suffrage == Voter {
					voters++
				}
			}
			assuranceEmit(t, map[string]interface{}{
				"event":          "config_sample",
				"probe":          probe,
				"elapsed_ms":     time.Since(start).Milliseconds(),
				"peer_id":        string(r.localID),
				"is_new_node":    string(r.localID) == string(newNode.localID),
				"num_servers":    len(cfg.Servers),
				"num_voters":     voters,
				"has_new_member": inConfiguration(cfg, newNode.localID),
			})
		}
		probe++
		time.Sleep(100 * time.Millisecond)
	}
}
