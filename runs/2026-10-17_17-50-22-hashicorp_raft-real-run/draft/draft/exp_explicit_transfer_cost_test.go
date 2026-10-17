package raft

// Construction notes:
//   * Each case bootstraps its own four-member in-memory cluster and demotes one
//     non-leader member only in the trigger case, waiting until that member's own
//     configuration view reports the non-voter role.
//   * Exactly one leader transfer request is issued per case, and the automatic
//     LeadershipTransfer() form is never called, so any leader change or term
//     advance observed afterwards belongs to the explicitly named target alone.
//   * Leader state and every member's current term are sampled every 10 ms for
//     five seconds, before and after the request.

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func etEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

func etRole(r *Raft, id ServerID) string {
	fut := r.GetConfiguration()
	if err := fut.Error(); err != nil {
		return "unknown"
	}
	for _, srv := range fut.Configuration().Servers {
		if srv.ID == id {
			if srv.Suffrage == Voter {
				return "voter"
			}
			return "nonvoter"
		}
	}
	return "absent"
}

func etTermMax(rafts []*Raft) uint64 {
	var max uint64
	for _, r := range rafts {
		if term := r.CurrentTerm(); term > max {
			max = term
		}
	}
	return max
}

func etRun(t *testing.T, name string, demoteTarget bool) {
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
		if r.localID != leader.localID {
			target = r
			break
		}
	}
	if target == nil {
		t.Fatalf("no non-leader peer")
	}
	targetID := target.localID

	converged := true
	if demoteTarget {
		if err := leader.DemoteVoter(targetID, 0, 5*time.Second).Error(); err != nil {
			t.Fatalf("demote: %v", err)
		}
		converged = false
		deadline := time.Now().Add(2 * time.Second)
		for time.Now().Before(deadline) {
			if etRole(target, targetID) == "nonvoter" {
				converged = true
				break
			}
			time.Sleep(5 * time.Millisecond)
		}
	}

	termMaxBefore := etTermMax(c.rafts)
	etEmit(t, map[string]interface{}{
		"event":              "et_case_" + name,
		"case":               name,
		"members":            4,
		"target_demoted":     demoteTarget,
		"role_view":          etRole(target, targetID),
		"converged":          converged,
		"leader_before":      string(leader.localID),
		"target_term_before": target.CurrentTerm(),
		"term_max_before":    termMaxBefore,
		"watch_window_ms":    int(watchWindow / time.Millisecond),
		"sample_interval_ms": int(sampleEvery / time.Millisecond),
	})

	start := time.Now()
	fut := leader.LeadershipTransferToServer(targetID, target.localAddr)
	err := fut.Error()
	futureMillis := int(time.Since(start) / time.Millisecond)
	futureErr := ""
	if err != nil {
		futureErr = err.Error()
	}

	samples := 0
	leaderless := 0
	targetEverLeader := false
	termMaxAfter := termMaxBefore
	deadline := time.Now().Add(watchWindow)
	for time.Now().Before(deadline) {
		samples++
		if target.State() == Leader {
			targetEverLeader = true
		}
		sawLeader := false
		for _, r := range c.rafts {
			if r.State() == Leader {
				sawLeader = true
				break
			}
		}
		if !sawLeader {
			leaderless++
		}
		for _, r := range c.rafts {
			if term := r.CurrentTerm(); term > termMaxAfter {
				termMaxAfter = term
			}
		}
		time.Sleep(sampleEvery)
	}

	finalLeader := c.Leader()
	finalLeaderID := ""
	finalIsTarget := false
	if finalLeader != nil {
		finalLeaderID = string(finalLeader.localID)
		finalIsTarget = finalLeader.localID == targetID
	}

	etEmit(t, map[string]interface{}{
		"event":                    "et_result_" + name,
		"case":                     name,
		"future_error":             futureErr,
		"future_ms":                futureMillis,
		"target_became_leader":     targetEverLeader,
		"final_leader":             finalLeaderID,
		"final_is_target":          finalIsTarget,
		"leaderless_samples":       leaderless,
		"samples":                  samples,
		"term_max_before":          termMaxBefore,
		"term_max_after":           termMaxAfter,
		"terms_advanced":           termMaxAfter > termMaxBefore,
		"target_term_after":        target.CurrentTerm(),
		"target_role_after":        etRole(target, targetID),
	})
}

func TestAssuranceExplicitTransferCost(t *testing.T) {
	t.Run("demoted_target_only_request", func(t *testing.T) {
		etRun(t, "demoted_target_only_request", true)
	})
	t.Run("voter_target_control", func(t *testing.T) {
		etRun(t, "voter_target_control", false)
	})
}
