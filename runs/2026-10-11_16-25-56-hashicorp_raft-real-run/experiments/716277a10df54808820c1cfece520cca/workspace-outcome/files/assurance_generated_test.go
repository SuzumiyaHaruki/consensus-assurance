package raft

import (
	"encoding/json"
	"fmt"
	"testing"
)

func caPost(t *testing.T, ev map[string]interface{}) {
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceGetConfigurationIndex checks the client-visible configuration
// index against a configuration entry whose index the caller learned from the
// AddVoter future, and then uses the returned index as the prevIndex of a later
// change, with a genuine index as the control.
func TestAssuranceGetConfigurationIndexWithLeaderScope(t *testing.T) {
	c := MakeCluster(3, t, nil)
	defer c.Close()

	leader := c.Leader()
	if leader == nil {
		t.Fatalf("no leader elected")
	}

	conf := inmemConfig(t)
	joiner := MakeClusterNoBootstrap(1, t, conf)
	c.Merge(joiner)
	c.FullyConnect()

	future := leader.AddVoter(joiner.rafts[0].localID, joiner.rafts[0].localAddr, 0, 0)
	if err := future.Error(); err != nil {
		t.Fatalf("add voter: %v", err)
	}
	entryIndex := future.Index()

	for _, r := range c.rafts {
		caPost(t, map[string]interface{}{
			"event":             "config_guard_start",
			"node":              string(r.localID),
			"is_leader":         r == leader,
			"known_entry_index": entryIndex,
		})
	}

	for _, r := range c.rafts {
		cfg := r.GetConfiguration()
		caPost(t, map[string]interface{}{
			"event":                       "config_read",
			"node":                        string(r.localID),
			"returned_index":              cfg.Index(),
			"returned_servers":            len(cfg.Configuration().Servers),
			"known_entry_index":           entryIndex,
			"is_leader":                   r == leader,
			"index_matches_configuration": cfg.Index() == entryIndex,
		})
	}

	// Use the index the API handed back as the optimistic-concurrency guard.
	readCfg := leader.GetConfiguration()
	prevIndexFromAPI := readCfg.Index()

	caPost(t, map[string]interface{}{
		"event":               "leader_change_window_start",
		"node":                string(leader.localID),
		"is_leader":           true,
		"read_against_index":  entryIndex,
		"prev_index_from_api": prevIndexFromAPI,
	})

	// Intervening configuration change: the configuration the value above was
	// read from is no longer the latest one.
	conf5 := inmemConfig(t)
	joiner2 := MakeClusterNoBootstrap(1, t, conf5)
	c.Merge(joiner2)
	c.FullyConnect()
	inter := leader.AddVoter(joiner2.rafts[0].localID, joiner2.rafts[0].localAddr, 0, 0)
	if err := inter.Error(); err != nil {
		t.Fatalf("intervening add voter: %v", err)
	}
	caPost(t, map[string]interface{}{
		"event":                 "intervening_change",
		"node":                  string(leader.localID),
		"prev_index_used":       0,
		"succeeded":             true,
		"resulting_entry_index": inter.Index(),
		"read_against_index":    entryIndex,
	})

	second := leader.DemoteVoter(joiner.rafts[0].localID, prevIndexFromAPI, 0)
	secondErr := second.Error()
	caPost(t, map[string]interface{}{
		"event":                 "change_with_returned_index",
		"node":                  string(leader.localID),
		"prev_index_used":       prevIndexFromAPI,
		"prev_index_from_api":   prevIndexFromAPI,
		"succeeded":             secondErr == nil,
		"rpc_error":             errText(secondErr),
		"resulting_entry_index": second.Index(),
	})

	// Control: the same kind of change guarded by the genuine index of the
	// configuration that was current when the read was taken.
	third := leader.AddVoter(joiner.rafts[0].localID, joiner.rafts[0].localAddr, entryIndex, 0)
	thirdErr := third.Error()
	caPost(t, map[string]interface{}{
		"event":                 "control_change_with_true_index",
		"node":                  string(leader.localID),
		"prev_index_used":       entryIndex,
		"succeeded":             thirdErr == nil,
		"rpc_error":             errText(thirdErr),
		"resulting_entry_index": third.Index(),
	})
}

func errText(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
