package raft

// Construction notes:
//   * One real four-member cluster is bootstrapped, one non-leader member is
//     demoted with DemoteVoter, and the harness waits until that member's own
//     configuration view reports the non-voter role.
//   * The control then calls LeadershipTransfer(), the automatic form that has no
//     target, and records whether a leader exists afterwards and whether it is a
//     voter.
//   * The trigger calls LeadershipTransferToServer for the demoted member and
//     records the future result, whether that member ever reports Leader, and the
//     sampled interval without a leader.
//   * The point of the pair is the asymmetry between the two entry points on the
//     same cluster state.

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"
)

func xgEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

func xgRun(t *testing.T, name string, explicit bool) {
	t.Helper()
	const sampleEvery = 10 * time.Millisecond
	const watchWindow = 3 * time.Second

	conf := inmemConfig(t)
	c := MakeClusterCustom(t, &MakeClusterOpts{Peers: 4, Bootstrap: true, Conf: conf})
	defer c.Close()

	// Choose the member to demote at the moment of the demotion, so the target is
	// definitely a follower then: demoting the sitting leader starts a transfer of
	// its own and would contaminate the case.
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
	demotedWasLeader := leader.localID == targetID

	if err := leader.DemoteVoter(targetID, 0, 5*time.Second).Error(); err != nil {
		t.Fatalf("demote: %v", err)
	}
	roleOf := func() string {
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
		if roleOf() == "nonvoter" {
			converged = true
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	convergeMS := int(time.Since(convergeStart) / time.Millisecond)

	mode := "automatic"
	if explicit {
		mode = "explicit_to_demoted_member"
	}
	xgEmit(t, map[string]interface{}{
		"event":              "xg_case_" + name,
		"case":               name,
		"mode":               mode,
		"members":            4,
		"voters":             3,
		"nonvoters":          1,
		"demoted_member":     string(targetID),
		"role_view":          roleOf(),
		"converged":          converged,
		"converge_ms":        convergeMS,
		"leader_before":      string(leader.localID),
		"demoted_was_leader": demotedWasLeader,
	})

	flagBefore := false
	if l := c.Leader(); l != nil {
		flagBefore = l.getLeadershipTransferInProgress()
	}
	futureOK := false
	futureErr := ""
	futureDone := false
	attempts := 0
	start := time.Now()
	attemptErrors := []string{}
	firstAttemptOK := false
	firstAttemptErr := ""
	for attempts < 5 {
		transferLeader := c.Leader()
		if transferLeader == nil {
			futureErr = "no leader at transfer time"
			attemptErrors = append(attemptErrors, futureErr)
			break
		}
		fut := transferLeader.LeadershipTransfer()
		if explicit {
			fut = transferLeader.LeadershipTransferToServer(targetID, target.localAddr)
		}
		attempts++
		done := make(chan error, 1)
		go func() { done <- fut.Error() }()
		var err error
		select {
		case err = <-done:
			futureDone = true
		case <-time.After(5 * time.Second):
			err = fmt.Errorf("no completion within five seconds")
		}
		attemptErrText := ""
		if err != nil {
			attemptErrText = err.Error()
		}
		attemptErrors = append(attemptErrors, attemptErrText)
		if attempts == 1 {
			firstAttemptOK = err == nil
			firstAttemptErr = attemptErrText
		}
		if err == nil {
			futureOK = true
			futureErr = ""
			break
		}
		futureErr = err.Error()
		if !strings.Contains(futureErr, "in progress") {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	futureMS := int(time.Since(start) / time.Millisecond)
	flagAfter := false
	if l := c.Leader(); l != nil {
		flagAfter = l.getLeadershipTransferInProgress()
	}

	samples := 0
	leaderless := 0
	targetEverLeader := false
	watchStart := time.Now()
	for time.Since(watchStart) < watchWindow {
		l := c.Leader()
		samples++
		if l == nil {
			leaderless++
		} else if l.localID == targetID {
			targetEverLeader = true
		}
		time.Sleep(sampleEvery)
	}
	finalLeader := ""
	finalIsTarget := false
	if l := c.Leader(); l != nil {
		finalLeader = string(l.localID)
		finalIsTarget = l.localID == targetID
	}

	// Whatever the transfer did to the leader's transfer state, a client write
	// submitted afterwards shows whether the leader still serves requests.
	applyErr := ""
	applyMs := 0
	configErr := ""
	if l := c.Leader(); l == nil {
		applyErr = "no leader"
		configErr = "no leader"
	} else {
		applyStart := time.Now()
		if err := l.Apply([]byte("post-transfer"), 2*time.Second).Error(); err != nil {
			applyErr = err.Error()
		}
		applyMs = int(time.Since(applyStart) / time.Millisecond)
		if err := l.GetConfiguration().Error(); err != nil {
			configErr = err.Error()
		}
	}

	xgEmit(t, map[string]interface{}{
		"event":                  "xg_result_" + name,
		"case":                   name,
		"mode":                   mode,
		"future_done":            futureDone,
		"future_ok":              futureOK,
		"future_error":           futureErr,
		"future_ms":              futureMS,
		"attempts":               attempts,
		"attempt_errors":         attemptErrors,
		"first_attempt_ok":       firstAttemptOK,
		"first_attempt_error":    firstAttemptErr,
		"flag_before":            flagBefore,
		"target_became_leader":   targetEverLeader,
		"samples":                samples,
		"leaderless_samples":     leaderless,
		"leaderless_ms_at_least": leaderless * int(sampleEvery/time.Millisecond),
		"final_leader":           finalLeader,
		"final_leader_is_target": finalIsTarget,
		"final_leader_is_voter":  finalLeader != "" && !finalIsTarget,
		"post_apply_error":       applyErr,
		"post_apply_ms":          applyMs,
		"post_config_error":      configErr,
		"flag_after":             flagAfter,
	})
	t.Logf("case=%s mode=%s futureOK=%v err=%q targetLeader=%v leaderless=%d final=%q",
		name, mode, futureOK, futureErr, targetEverLeader, leaderless, finalLeader)
}

func TestAssuranceTransferAutomaticVsExplicit(t *testing.T) {
	t.Run("control_automatic_transfer", func(t *testing.T) {
		xgRun(t, "control_automatic_transfer", false)
	})
	t.Run("trigger_explicit_to_demoted", func(t *testing.T) {
		xgRun(t, "trigger_explicit_to_demoted", true)
	})
}
