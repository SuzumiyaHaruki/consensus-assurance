package raft

// Construction notes:
//   * Each attempt builds a fresh four-voter cluster, picks the leader and one
//     follower, starts DemoteVoter for that follower on a goroutine, and issues
//     LeadershipTransferToServer for the same member immediately afterwards,
//     without waiting for the demotion to commit or for any voter to apply it.
//   * The question is whether the transfer can install a member as leader while
//     the configuration change that removes its vote is still in flight.
//   * Every attempt records the demotion and transfer futures, whether the target
//     ever reported Leader, and the target's own role at the end.

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func cvEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

type cvOutcome struct {
	demoteOK        bool
	transferOK      bool
	transferErr     string
	targetEverLeader bool
	finalIsTarget   bool
	endRole         string
}

func cvAttempt(t *testing.T) cvOutcome {
	t.Helper()
	conf := inmemConfig(t)
	c := MakeClusterCustom(t, &MakeClusterOpts{Peers: 4, Bootstrap: true, Conf: conf})
	defer c.Close()

	out := cvOutcome{}
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
		t.Fatalf("no follower")
	}
	targetID := target.localID
	targetAddr := target.localAddr

	demoteDone := make(chan error, 1)
	go func() { demoteDone <- leader.DemoteVoter(targetID, 0, 5*time.Second).Error() }()

	transferLeader := c.Leader()
	if transferLeader == nil {
		out.transferErr = "no leader at transfer time"
		<-demoteDone
		return out
	}
	transferDone := make(chan error, 1)
	go func() { transferDone <- transferLeader.LeadershipTransferToServer(targetID, targetAddr).Error() }()

	select {
	case err := <-demoteDone:
		out.demoteOK = err == nil
	case <-time.After(5 * time.Second):
	}
	select {
	case err := <-transferDone:
		if err != nil {
			out.transferErr = err.Error()
		} else {
			out.transferOK = true
		}
	case <-time.After(3 * time.Second):
		out.transferErr = "no completion within three seconds"
	}

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if target.State() == Leader {
			out.targetEverLeader = true
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if l := c.Leader(); l != nil {
		out.finalIsTarget = l.localID == targetID
	}
	if fut := target.GetConfiguration(); fut.Error() == nil {
		for _, srv := range fut.Configuration().Servers {
			if srv.ID == targetID {
				if srv.Suffrage == Voter {
					out.endRole = "voter"
				} else {
					out.endRole = "nonvoter"
				}
			}
		}
	}
	return out
}

func TestAssuranceTransferDemotionRace(t *testing.T) {
	const attempts = 20
	cvEmit(t, map[string]interface{}{
		"event":    "cv_case_demotion_race",
		"case":     "demotion_race",
		"attempts": attempts,
		"members":  4,
	})
	demoteOK, transferOK, targetLed, finalTarget, endNonvoter := 0, 0, 0, 0, 0
	lastErr := ""
	for i := 0; i < attempts; i++ {
		out := cvAttempt(t)
		if out.demoteOK {
			demoteOK++
		}
		if out.transferOK {
			transferOK++
		}
		if out.targetEverLeader {
			targetLed++
		}
		if out.finalIsTarget {
			finalTarget++
		}
		if out.endRole == "nonvoter" {
			endNonvoter++
		}
		if out.transferErr != "" {
			lastErr = out.transferErr
		}
	}
	cvEmit(t, map[string]interface{}{
		"event":                   "cv_result_demotion_race",
		"case":                    "demotion_race",
		"attempts":                attempts,
		"demote_ok_count":         demoteOK,
		"transfer_ok_count":       transferOK,
		"target_led_count":        targetLed,
		"final_target_count":      finalTarget,
		"target_ended_nonvoter":   endNonvoter,
		"last_transfer_error":     lastErr,
	})
	t.Logf("attempts=%d demoteOK=%d transferOK=%d targetLed=%d finalTarget=%d endNonvoter=%d lastErr=%q",
		attempts, demoteOK, transferOK, targetLed, finalTarget, endNonvoter, lastErr)
}
