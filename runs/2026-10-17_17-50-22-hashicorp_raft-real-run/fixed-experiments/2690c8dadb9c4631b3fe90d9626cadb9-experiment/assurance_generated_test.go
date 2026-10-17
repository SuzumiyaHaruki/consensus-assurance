package raft

// Construction notes:
//   * Each case bootstraps its own four-member cluster, demotes one follower and
//     waits until that member's own configuration view reports the non-voter
//     role, so the target is known to be ineligible before the transfer starts.
//   * The single case issues exactly one explicit transfer, sampling the
//     leader's transfer flag before the call, immediately after the call returns
//     its future, after the future completes and after a short settle.
//   * The retry case reproduces the five-attempt sequence and samples the flag
//     before every attempt, so an in-progress error can be attributed either to
//     a prior request still running or to the request that produced it.

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"
)

func fwEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

type fwSetup struct {
	cluster []*Raft
	leader  *Raft
	target  *Raft
}

func fwPrepare(t *testing.T, name string) (fwSetup, bool) {
	t.Helper()
	conf := inmemConfig(t)
	c := MakeClusterCustom(t, &MakeClusterOpts{Peers: 4, Bootstrap: true, Conf: conf})
	leader := c.Leader()
	if leader == nil {
		c.Close()
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
		c.Close()
		t.Fatalf("no non-leader peer")
	}
	targetID := target.localID
	if err := leader.DemoteVoter(targetID, 0, 5*time.Second).Error(); err != nil {
		c.Close()
		t.Fatalf("demote: %v", err)
	}
	role := func() string {
		fut := target.GetConfiguration()
		if err := fut.Error(); err != nil {
			return "unknown"
		}
		for _, srv := range fut.Configuration().Servers {
			if srv.ID == targetID {
				if srv.Suffrage == Voter {
					return "voter"
				}
				return "nonvoter"
			}
		}
		return "absent"
	}
	convergeStart := time.Now()
	converged := false
	for time.Since(convergeStart) < 2*time.Second {
		if role() == "nonvoter" {
			converged = true
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	x := fwSetup{cluster: c.rafts, leader: leader, target: target}
	fwEmit(t, map[string]interface{}{
		"event":         "fw_case_" + name,
		"case":          name,
		"members":       4,
		"demoted":       string(targetID),
		"role_view":     role(),
		"converged":     converged,
		"converge_ms":   int(time.Since(convergeStart) / time.Millisecond),
		"leader_before": string(leader.localID),
	})
	return x, converged
}

func fwWatchLeader(target *Raft, members []*Raft, window time.Duration) (bool, int, int, string) {
	targetEverLeader := false
	leaderless := 0
	samples := 0
	deadline := time.Now().Add(window)
	for time.Now().Before(deadline) {
		samples++
		found := ""
		for _, r := range members {
			if r.State() == Leader {
				found = string(r.localID)
				if r.localID == target.localID {
					targetEverLeader = true
				}
				break
			}
		}
		if found == "" {
			leaderless++
		}
		time.Sleep(10 * time.Millisecond)
	}
	final := ""
	for _, r := range members {
		if r.State() == Leader {
			final = string(r.localID)
			break
		}
	}
	return targetEverLeader, leaderless, samples, final
}

func TestAssuranceTransferFlagWindow(t *testing.T) {
	t.Run("single_explicit_attempt", func(t *testing.T) {
		x, converged := fwPrepare(t, "single_explicit_attempt")
		if !converged {
			t.Fatalf("demotion did not converge on the target")
		}
		before := x.leader.getLeadershipTransferInProgress()
		fut := x.leader.LeadershipTransferToServer(x.target.localID, x.target.localAddr)
		afterCall := x.leader.getLeadershipTransferInProgress()
		start := time.Now()
		done := make(chan error, 1)
		go func() { done <- fut.Error() }()
		var err error
		completed := false
		select {
		case err = <-done:
			completed = true
		case <-time.After(5 * time.Second):
		}
		elapsed := int(time.Since(start) / time.Millisecond)
		afterFuture := x.leader.getLeadershipTransferInProgress()
		time.Sleep(300 * time.Millisecond)
		settled := x.leader.getLeadershipTransferInProgress()
		errText := ""
		if err != nil {
			errText = err.Error()
		}
		targetLed, leaderless, samples, final := fwWatchLeader(x.target, x.cluster, 3*time.Second)
		fwEmit(t, map[string]interface{}{
			"event":                "fw_result_single_explicit_attempt",
			"case":                 "single_explicit_attempt",
			"flag_before":          before,
			"flag_after_call":      afterCall,
			"flag_after_future":    afterFuture,
			"flag_after_300ms":     settled,
			"future_completed":     completed,
			"future_error":         errText,
			"future_ms":            elapsed,
			"attempts":             1,
			"target_became_leader": targetLed,
			"leaderless_samples":   leaderless,
			"samples":              samples,
			"final_leader":         final,
			"final_is_target":      final != "" && final == string(x.target.localID),
		})
	})

	t.Run("retry_sequence_explicit", func(t *testing.T) {
		x, converged := fwPrepare(t, "retry_sequence_explicit")
		if !converged {
			t.Fatalf("demotion did not converge on the target")
		}
		flagBeforeFirst := x.leader.getLeadershipTransferInProgress()
		attemptErrors := []string{}
		flagsBefore := []bool{}
		attempts := 0
		for attempts < 5 {
			current := x.leader
			for _, r := range x.cluster {
				if r.State() == Leader {
					current = r
					break
				}
			}
			flagsBefore = append(flagsBefore, current.getLeadershipTransferInProgress())
			fut := current.LeadershipTransferToServer(x.target.localID, x.target.localAddr)
			attempts++
			done := make(chan error, 1)
			go func() { done <- fut.Error() }()
			var err error
			select {
			case err = <-done:
			case <-time.After(5 * time.Second):
				err = fmt.Errorf("no completion within five seconds")
			}
			text := ""
			if err != nil {
				text = err.Error()
			}
			attemptErrors = append(attemptErrors, text)
			if err == nil || !strings.Contains(text, "in progress") {
				break
			}
			time.Sleep(100 * time.Millisecond)
		}
		targetLed, leaderless, samples, final := fwWatchLeader(x.target, x.cluster, 3*time.Second)
		fwEmit(t, map[string]interface{}{
			"event":                "fw_result_retry_sequence_explicit",
			"case":                 "retry_sequence_explicit",
			"flag_before_first":    flagBeforeFirst,
			"flags_before_attempt": flagsBefore,
			"attempt_errors":       attemptErrors,
			"attempts":             attempts,
			"target_became_leader": targetLed,
			"leaderless_samples":   leaderless,
			"samples":              samples,
			"final_leader":         final,
			"final_is_target":      final != "" && final == string(x.target.localID),
		})
	})
}
