package raft

// Construction notes:
//   * Four real members are bootstrapped, one non-leader member is demoted, so
//     the configuration has three voters and exactly one non-voter.
//   * The trigger cuts the leader from the two other voters and leaves the single
//     non-voter reachable, so the voter quorum is 2 and only the leader itself
//     can answer for the voters.
//   * The control cuts the non-voter as well, leaving no possible supporter.
//   * Earlier receipts used five members with two non-voters; this one tests
//     whether a single non-voter is enough for the same false success.

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func vxEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

func vxRun(t *testing.T, name string, cutNonvoter bool) {
	t.Helper()
	conf := inmemConfig(t)
	c := MakeClusterCustom(t, &MakeClusterOpts{Peers: 4, Bootstrap: true, Conf: conf})
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
	if len(others) != 3 {
		t.Fatalf("expected three non-leader members, got %d", len(others))
	}
	nonvoter := others[0]
	if err := leader.DemoteVoter(nonvoter.localID, 0, 5*time.Second).Error(); err != nil {
		t.Fatalf("demote: %v", err)
	}
	// Wait until the demoted member's own view reports the new role.
	converged := false
	convergeStart := time.Now()
	for time.Since(convergeStart) < 2*time.Second {
		fut := nonvoter.GetConfiguration()
		if err := fut.Error(); err == nil {
			for _, srv := range fut.Configuration().Servers {
				if srv.ID == nonvoter.localID && srv.Suffrage != Voter {
					converged = true
				}
			}
		}
		if converged {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	convergeMS := int(time.Since(convergeStart) / time.Millisecond)

	leaderTrans := leader.trans.(*InmemTransport)
	for _, r := range others[1:] {
		leaderTrans.Disconnect(r.localAddr)
		r.trans.(*InmemTransport).Disconnect(leader.localAddr)
	}
	if cutNonvoter {
		leaderTrans.Disconnect(nonvoter.localAddr)
		nonvoter.trans.(*InmemTransport).Disconnect(leader.localAddr)
	}

	vxEmit(t, map[string]interface{}{
		"event":               "vx_case_" + name,
		"case":                name,
		"members":             4,
		"voters":              3,
		"nonvoters":           1,
		"voters_reachable":    1,
		"nonvoters_reachable": map[bool]int{true: 0, false: 1}[cutNonvoter],
		"quorum_voters":       2,
		"demotion_converged":  converged,
		"demotion_converge_ms": convergeMS,
	})

	fut := leader.VerifyLeader()
	done := make(chan error, 1)
	start := time.Now()
	go func() { done <- fut.Error() }()
	verifyOK := false
	verifyErr := ""
	completed := false
	select {
	case err := <-done:
		completed = true
		if err != nil {
			verifyErr = err.Error()
		} else {
			verifyOK = true
		}
	case <-time.After(2 * time.Second):
		verifyErr = "no completion within two seconds"
	}
	vxEmit(t, map[string]interface{}{
		"event":          "vx_result_" + name,
		"case":           name,
		"completed":      completed,
		"verify_ok":      verifyOK,
		"verify_error":   verifyErr,
		"elapsed_ms":     int(time.Since(start) / time.Millisecond),
		"state_after":    leader.State().String(),
	})
	t.Logf("case=%s verifyOK=%v err=%q state=%s", name, verifyOK, verifyErr, leader.State())
}

func TestAssuranceVerifySingleNonvoter(t *testing.T) {
	t.Run("trigger_one_nonvoter_connected", func(t *testing.T) {
		vxRun(t, "trigger_one_nonvoter_connected", false)
	})
	t.Run("control_all_cut", func(t *testing.T) {
		vxRun(t, "control_all_cut", true)
	})
}
