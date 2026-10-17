package raft

// Construction notes:
//   * A real in-memory cluster is bootstrapped with four voters, then one
//     non-leader member is demoted with DemoteVoter so the configuration itself
//     (not a hand-built state) makes the target a non-voter.
//   * The transfer case calls LeadershipTransferToServer for that demoted
//     member; the control case calls it for a voter in an otherwise identical
//     cluster. Both record the future result, whether the named target ever
//     reported Leader, the sampled interval without a leader, and terms.

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func xfEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

type xfObservation struct {
	futureOK           bool
	futureErr          string
	futureMillis       int
	targetEverLeader   bool
	finalLeaderIsTargt bool
	noLeaderMillis     int
	samples            int
	targetTerm         uint64
	voterTermMax       uint64
	candidateSamples   int
	leaderlessSamples  int
}

func xfRunTransfer(t *testing.T, name string, demote bool) {
	t.Helper()
	const sampleEvery = 10 * time.Millisecond
	const watchWindow = 5 * time.Second
	conf := inmemConfig(t)
	c := MakeClusterCustom(t, &MakeClusterOpts{Peers: 4, Bootstrap: true, Conf: conf})
	defer c.Close()

	leader := c.Leader()
	if leader == nil {
		t.Fatalf("no leader")
	}
	var target *Raft
	for _, r := range c.rafts {
		if r != leader {
			target = r
			break
		}
	}
	if target == nil {
		t.Fatalf("no non-leader peer")
	}
	targetID := target.localID
	termBefore := target.CurrentTerm()
	// What the target itself believes about its suffrage, read through its own
	// configuration future before any transfer is requested.
	ownRole := "absent"
	if cfgFut := target.GetConfiguration(); cfgFut.Error() == nil {
		for _, srv := range cfgFut.Configuration().Servers {
			if srv.ID == targetID {
				if srv.Suffrage == Voter {
					ownRole = "voter"
				} else {
					ownRole = "nonvoter"
				}
			}
		}
	} else {
		ownRole = "unknown"
	}

	if demote {
		if err := leader.DemoteVoter(targetID, 0, 5*time.Second).Error(); err != nil {
			t.Fatalf("demote: %v", err)
		}
		// Let the committed configuration reach the demoted member before the
		// transfer is requested.
		time.Sleep(200 * time.Millisecond)
	}

	xfEmit(t, map[string]interface{}{
		"event":                "case_" + name,
		"case":                 name,
		"peers":                4,
		"target_demoted":       demote,
		"target_term_before":   termBefore,
		"watch_window_ms":      int(watchWindow / time.Millisecond),
		"sample_interval_ms":   int(sampleEvery / time.Millisecond),
		"transfer_target_role": map[bool]string{true: "nonvoter", false: "voter"}[demote],
		"target_role_in_own_config": ownRole,
	})

	start := time.Now()
	fut := leader.LeadershipTransferToServer(targetID, target.localAddr)
	err := fut.Error()
	obs := xfObservation{futureOK: err == nil, futureMillis: int(time.Since(start) / time.Millisecond)}
	if err != nil {
		obs.futureErr = err.Error()
	}

	deadline := time.Now().Add(watchWindow)
	for time.Now().Before(deadline) {
		obs.samples++
		if target.State() == Leader {
			obs.targetEverLeader = true
		}
		if target.State() == Candidate {
			obs.candidateSamples++
		}
		anyLeader := false
		for _, r := range c.rafts {
			if r.State() == Leader {
				anyLeader = true
			}
		}
		if !anyLeader {
			obs.leaderlessSamples++
			obs.noLeaderMillis += int(sampleEvery / time.Millisecond)
		}
		time.Sleep(sampleEvery)
	}
	if final := c.Leader(); final != nil {
		obs.finalLeaderIsTargt = final.localID == targetID
	}
	obs.targetTerm = target.CurrentTerm()
	for _, r := range c.rafts {
		if r != target && r.CurrentTerm() > obs.voterTermMax {
			obs.voterTermMax = r.CurrentTerm()
		}
	}

	xfEmit(t, map[string]interface{}{
		"event":                       "result_" + name,
		"case":                        name,
		"future_ok":                   obs.futureOK,
		"future_error":                obs.futureErr,
		"future_ms":                   obs.futureMillis,
		"target_ever_leader":          obs.targetEverLeader,
		"final_leader_is_target":      obs.finalLeaderIsTargt,
		"no_leader_ms_sampled":        obs.noLeaderMillis,
		"samples":                     obs.samples,
		"target_term_after":           obs.targetTerm,
		"other_member_term_max_after": obs.voterTermMax,
		"candidate_samples":           obs.candidateSamples,
		"leaderless_samples":          obs.leaderlessSamples,
	})
}

func TestAssuranceLeadershipTransferTargetEligibility(t *testing.T) {
	t.Run("control_transfer_to_voter", func(t *testing.T) {
		xfRunTransfer(t, "control_transfer_to_voter", false)
	})
	t.Run("trigger_transfer_to_nonvoter", func(t *testing.T) {
		xfRunTransfer(t, "trigger_transfer_to_nonvoter", true)
	})
}
