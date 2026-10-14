// Copyright (c) 2026. Assurance harness artifact (draft, not part of the target source).
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

func caEmit(t *testing.T, payload interface{}) {
	t.Helper()
	blob, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(blob))
}

func caErrString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

// caWaitFuture reports whether a future resolved within the bound and its error.
func caWaitFuture(f Future, wait time.Duration) (bool, string) {
	ch := make(chan error, 1)
	go func() { ch <- f.Error() }()
	select {
	case err := <-ch:
		return true, caErrString(err)
	case <-time.After(wait):
		return false, "future did not resolve within the bound"
	}
}

func caQuorum(cfg Configuration) (voters int) {
	for _, s := range cfg.Servers {
		if s.Suffrage == Voter {
			voters++
		}
	}
	return voters
}

// TestAssurance_AddVoterUnreachableServer observes what adding a server that is
// not running does to a cluster's ability to make progress, and whether the
// cluster can undo it through the API.
//
// The AddVoter documentation in the captured snapshot says the given server is
// added as a staging server that the leader promotes once it is ready. This
// probe adds an address no transport answers, on a single-voter cluster and on
// a three-voter cluster, records the resulting configuration and quorum,
// whether a subsequent apply can complete, whether the cluster can still elect,
// and whether the added server can be removed again through the API.
func TestAssurance_AddVoterUnreachableServer(t *testing.T) {
	conf := inmemConfig(t)
	conf.Logger = hclog.NewNullLogger()

	caRunAddDeadVoter(t, conf, 0, 1)
	caRunAddDeadVoter(t, conf, 1, 3)
}

func caRunAddDeadVoter(t *testing.T, conf *Config, trial, peers int) {
	t.Helper()

	c := MakeCluster(peers, t, conf)
	defer c.Close()

	leader := c.Leader()

	// A server that exists only as an address: no transport answers it.
	deadAddr, deadTrans := NewInmemTransport("")
	deadID := ServerID("dead-" + string(deadAddr))
	_ = deadTrans

	// Baseline: the cluster can commit before the new server is added.
	baseCompleted, baseErr := caWaitFuture(leader.Apply([]byte("before-add"), 0), 2*time.Second)
	baseCfg := leader.GetConfiguration().Configuration()
	caEmit(t, map[string]interface{}{
		"event":             "add_dead_voter_baseline",
		"trial":             trial,
		"configured_voters": peers,
		"voters_in_config":  caQuorum(baseCfg),
		"apply_completed":   baseCompleted,
		"apply_error":       baseErr,
		"leader_state":      leader.getState().String(),
	})

	// Add the unreachable server through the documented API.
	addCompleted, addErr := caWaitFuture(leader.AddVoter(deadID, deadAddr, 0, 0), 3*time.Second)
	cfgAfterAdd := leader.GetConfiguration().Configuration()
	deadSuffrage := "absent"
	livingVoters := 0
	for _, s := range cfgAfterAdd.Servers {
		if s.ID == deadID {
			deadSuffrage = s.Suffrage.String()
		} else if s.Suffrage == Voter {
			livingVoters++
		}
	}
	votersAfterAdd := caQuorum(cfgAfterAdd)
	quorumSizeAfterAdd := votersAfterAdd/2 + 1
	quorumNeedsDead := quorumSizeAfterAdd > livingVoters
	caEmit(t, map[string]interface{}{
		"event":                        "add_dead_voter_config",
		"trial":                        trial,
		"added_server_id":              string(deadID),
		"add_completed":                addCompleted,
		"add_error":                    addErr,
		"dead_server_suffrage":         deadSuffrage,
		"voters_in_config":             votersAfterAdd,
		"living_voters_in_config":      livingVoters,
		"quorum_size":                  quorumSizeAfterAdd,
		"quorum_requires_dead_server":  quorumNeedsDead,
		"leader_state":                 leader.getState().String(),
	})

	// Can the cluster still make progress, and can it elect a leader?
	time.Sleep(150 * time.Millisecond)
	stateAfter := leader.getState().String()
	applyCompleted, applyErr := caWaitFuture(leader.Apply([]byte("after-add"), 0), 1500*time.Millisecond)
	leaders := 0
	for _, r := range c.rafts {
		if r.getState() == Leader {
			leaders++
		}
	}
	caEmit(t, map[string]interface{}{
		"event":                      "add_dead_voter_apply",
		"trial":                      trial,
		"voters_in_config":           votersAfterAdd,
		"living_voters_in_config":    livingVoters,
		"quorum_size":                quorumSizeAfterAdd,
		"quorum_requires_dead_server": quorumNeedsDead,
		"apply_completed":            applyCompleted,
		"apply_succeeded":            applyCompleted && applyErr == "",
		"apply_error":                applyErr,
		"leader_state":               stateAfter,
		"leaders_in_cluster":         leaders,
	})

	// Can the operator undo it through the same API?
	removeCompleted, removeErr := caWaitFuture(leader.RemoveServer(deadID, 0, 0), 2*time.Second)
	cfgAfterRemove := leader.GetConfiguration().Configuration()
	caEmit(t, map[string]interface{}{
		"event":                       "add_dead_voter_remove",
		"trial":                       trial,
		"quorum_requires_dead_server": quorumNeedsDead,
		"remove_completed":            removeCompleted,
		"remove_succeeded":            removeCompleted && removeErr == "",
		"remove_error":                removeErr,
		"voters_in_config_after":      caQuorum(cfgAfterRemove),
	})
}
