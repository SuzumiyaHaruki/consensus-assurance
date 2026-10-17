package raft

// Construction notes:
//   * Each case bootstraps five members, demotes two to non-voters, and cuts the
//     leader from the two remaining voters while leaving the non-voters
//     reachable, so the leader can reach only itself among voters.
//   * The case then repeats VerifyLeader every 50 ms and records how many
//     consecutive verifications succeeded and how long the first failure took.
//   * The two cases differ only in the configured lease and the timeouts above
//     it, so the measured window can be compared across settings.

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func vlEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

func vlRun(t *testing.T, name string, lease, heartbeat, election, window time.Duration) {
	t.Helper()
	conf := inmemConfig(t)
	conf.LeaderLeaseTimeout = lease
	conf.HeartbeatTimeout = heartbeat
	conf.ElectionTimeout = election
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
	for _, r := range others[:2] {
		if err := leader.DemoteVoter(r.localID, 0, 5*time.Second).Error(); err != nil {
			t.Fatalf("demote: %v", err)
		}
	}
	time.Sleep(heartbeat / 2)

	leaderTrans := leader.trans.(*InmemTransport)
	for _, r := range others[2:] {
		leaderTrans.Disconnect(r.localAddr)
		r.trans.(*InmemTransport).Disconnect(leader.localAddr)
	}
	vlEmit(t, map[string]interface{}{
		"event":               "vl_case_" + name,
		"case":                name,
		"lease_ms":            int(lease / time.Millisecond),
		"heartbeat_ms":        int(heartbeat / time.Millisecond),
		"election_ms":         int(election / time.Millisecond),
		"members":             5,
		"nonvoters":           2,
		"voters":              3,
		"nonvoters_reachable": 2,
		"voters_reachable":    1,
	})

	firstStart := time.Now()
	firstErr := leader.VerifyLeader().Error()
	firstOK := firstErr == nil
	firstMS := int(time.Since(firstStart) / time.Millisecond)

	successes := 0
	msUntilFailure := -1
	loopStart := time.Now()
	for time.Since(loopStart) < window {
		f := leader.VerifyLeader()
		done := make(chan error, 1)
		go func() { done <- f.Error() }()
		var err error
		select {
		case err = <-done:
		case <-time.After(lease):
			err = fmt.Errorf("no completion")
		}
		if err == nil {
			successes++
			time.Sleep(50 * time.Millisecond)
			continue
		}
		msUntilFailure = int(time.Since(loopStart) / time.Millisecond)
		break
	}
	vlEmit(t, map[string]interface{}{
		"event":            "vl_result_" + name,
		"case":             name,
		"lease_ms":         int(lease / time.Millisecond),
		"heartbeat_ms":     int(heartbeat / time.Millisecond),
		"election_ms":      int(election / time.Millisecond),
		"members":          5,
		"nonvoters":        2,
		"first_verify_ok":  firstOK,
		"first_verify_ms":  firstMS,
		"loop_successes":   successes,
		"ms_until_failure": msUntilFailure,
		"window_ms":        int(window / time.Millisecond),
		"state_after":      leader.State().String(),
	})
	t.Logf("case=%s lease=%v firstOK=%v successes=%d msUntilFailure=%d",
		name, lease, firstOK, successes, msUntilFailure)
}

func TestAssuranceVerifyLeaseWindow(t *testing.T) {
	t.Run("lease_500ms", func(t *testing.T) {
		vlRun(t, "lease_500ms", 500*time.Millisecond, 500*time.Millisecond, 600*time.Millisecond, 2*time.Second)
	})
	t.Run("lease_1s", func(t *testing.T) {
		vlRun(t, "lease_1s", time.Second, time.Second, time.Second, 2500*time.Millisecond)
	})
}
