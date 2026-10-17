package raft

// Construction notes:
//   * Five real members are bootstrapped, two are demoted to non-voters, and the
//     leader's transport is disconnected from the remaining voters only. The
//     trigger asks the leader to verify itself while just one voter (itself) is
//     reachable; the control also cuts the non-voters, leaving no supporter.

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func vfEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

func TestAssuranceVerifyLeaderSupporters(t *testing.T) {
	run := func(name string, alsoCutNonvoters bool) {
		conf := inmemConfig(t)
		conf.HeartbeatTimeout = time.Second
		conf.ElectionTimeout = time.Second
		conf.LeaderLeaseTimeout = time.Second
		c := MakeClusterCustom(t, &MakeClusterOpts{Peers: 5, Bootstrap: true, Conf: conf})
		defer c.Close()

		leader := c.Leader()
		if leader == nil {
			t.Fatalf("no leader")
		}
		var others []*Raft
		for _, r := range c.rafts {
			if r != leader {
				others = append(others, r)
			}
		}
		// Demote two peers so the cluster has 3 voters and 2 non-voters.
		for _, r := range others[:2] {
			if err := leader.DemoteVoter(r.localID, 0, 5*time.Second).Error(); err != nil {
				t.Fatalf("demote: %v", err)
			}
		}
		time.Sleep(300 * time.Millisecond)

		// Cut the leader from the two remaining voters.
		leaderTrans := leader.trans.(*InmemTransport)
		for _, r := range others[2:] {
			leaderTrans.Disconnect(r.localAddr)
			r.trans.(*InmemTransport).Disconnect(leader.localAddr)
		}
		if alsoCutNonvoters {
			for _, r := range others[:2] {
				leaderTrans.Disconnect(r.localAddr)
				r.trans.(*InmemTransport).Disconnect(leader.localAddr)
			}
		}

		vfEmit(t, map[string]interface{}{
			"event":               "verify_case_" + name,
			"case":                name,
			"members":             5,
			"voters":              3,
			"nonvoters":           2,
			"voters_reachable":    1,
			"nonvoters_reachable": map[bool]int{true: 0, false: 2}[alsoCutNonvoters],
			"quorum_voters":       2,
			"window_ms":           2000,
		})
		fut := leader.VerifyLeader()
		ok := false
		errText := ""
		completed := false
		done := make(chan error, 1)
		go func() { done <- fut.Error() }()
		select {
		case err := <-done:
			completed = true
			ok = err == nil
			if err != nil {
				errText = err.Error()
			}
		case <-time.After(2 * time.Second):
		}
		vfEmit(t, map[string]interface{}{
			"event":            "verify_result_" + name,
			"case":             name,
			"completed":        completed,
			"verify_ok":        ok,
			"verify_error":     errText,
			"state_after":      leader.State().String(),
		})

		// Repeat the verification until it fails, to bound how long a false
		// success can be obtained from the same partitioned leader.
		loopSuccesses := 0
		msUntilFailure := -1
		loopStart := time.Now()
		for time.Since(loopStart) < 3*time.Second {
			f := leader.VerifyLeader()
			done2 := make(chan error, 1)
			go func() { done2 <- f.Error() }()
			var err error
			select {
			case err = <-done2:
				if err == nil {
					loopSuccesses++
					time.Sleep(50 * time.Millisecond)
					continue
				}
			case <-time.After(300 * time.Millisecond):
				err = fmt.Errorf("no completion")
			}
			msUntilFailure = int(time.Since(loopStart) / time.Millisecond)
			_ = err
			break
		}
		vfEmit(t, map[string]interface{}{
			"event":             "verify_loop_" + name,
			"case":              name,
			"loop_successes":    loopSuccesses,
			"ms_until_failure":  msUntilFailure,
			"state_after_loop":  leader.State().String(),
		})
	}
	t.Run("trigger_nonvoters_connected", func(t *testing.T) { run("trigger_nonvoters_connected", false) })
	t.Run("control_all_cut", func(t *testing.T) { run("control_all_cut", true) })
}
