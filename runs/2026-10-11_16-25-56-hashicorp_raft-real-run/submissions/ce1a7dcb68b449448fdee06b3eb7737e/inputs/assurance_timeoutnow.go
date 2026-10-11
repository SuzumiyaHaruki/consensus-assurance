package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func caEvent(t *testing.T, ev map[string]interface{}) {
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceTimeoutNowNonLeaderAuthority observes the receiving side of a
// leadership-transfer order (TimeoutNow) in a fault-free, normally bootstrapped
// in-memory cluster. The RPC header is filled with a sender identity that is not
// the current leader and not part of the configuration; TimeoutNowRequest has no
// term field at all, so no freshness value can be supplied or checked.
func TestAssuranceTimeoutNowNonLeaderAuthority(t *testing.T) {
	c := MakeCluster(3, t, nil)
	defer c.Close()

	leader := c.Leader()
	if leader == nil {
		t.Fatalf("no leader elected")
	}
	leaderID, leaderAddr := leader.LeaderWithID()
	leaderTermBefore := leader.getCurrentTerm()

	var target *Raft
	for _, r := range c.rafts {
		if r != leader {
			target = r
			break
		}
	}
	if target == nil {
		t.Fatalf("no follower available")
	}

	targetStateBefore := target.getState()
	targetTermBefore := target.getCurrentTerm()

	caEvent(t, map[string]interface{}{
		"event":             "steady_state",
		"leader_id":         string(leaderID),
		"leader_addr":       string(leaderAddr),
		"leader_state":      leader.getState().String(),
		"leader_term":       leaderTermBefore,
		"target_id":         string(target.localID),
		"target_state":      targetStateBefore.String(),
		"target_term":       targetTermBefore,
		"target_protocol":   int64(target.protocolVersion),
		"cluster_size":      len(c.rafts),
		"claimed_sender_id": "ghost-not-in-config",
	})

	sender := c.trans[(c.IndexOf(target)+1)%len(c.trans)]
	ghostHeader := RPCHeader{
		ProtocolVersion: target.protocolVersion,
		ID:              []byte("ghost-not-in-config"),
		Addr:            []byte("ghost-not-in-config"),
	}

	// Control: the same non-member sender, with a request that does carry a term,
	// but an older one. A stale request must not move the target.
	voteReq := &RequestVoteRequest{
		RPCHeader:    ghostHeader,
		Term:         targetTermBefore - 1,
		LastLogIndex: 0,
		LastLogTerm:  0,
	}
	voteResp := &RequestVoteResponse{}
	caEvent(t, map[string]interface{}{
		"event":             "control_vote_sent",
		"claimed_sender_id": "ghost-not-in-config",
		"target_id":         string(target.localID),
		"request_term":      targetTermBefore - 1,
		"target_state":      targetStateBefore.String(),
		"target_term":       targetTermBefore,
	})
	voteErr := sender.RequestVote(target.localID, target.localAddr, voteReq, voteResp)
	caEvent(t, map[string]interface{}{
		"event":              "control_stale_request_vote",
		"claimed_sender_id":  "ghost-not-in-config",
		"request_term":       targetTermBefore - 1,
		"rpc_error":          errString(voteErr),
		"granted":            voteResp.Granted,
		"target_state_after": target.getState().String(),
		"target_term_after":  target.getCurrentTerm(),
		"target_moved":       target.getState() != targetStateBefore || target.getCurrentTerm() != targetTermBefore,
	})

	// Authority probe: leadership-transfer order from the same non-member sender.
	nowReq := &TimeoutNowRequest{RPCHeader: ghostHeader}
	nowResp := &TimeoutNowResponse{}
	caEvent(t, map[string]interface{}{
		"event":             "authority_probe_sent",
		"claimed_sender_id": "ghost-not-in-config",
		"target_id":         string(target.localID),
		"leader_id":         string(leaderID),
		"target_state":      targetStateBefore.String(),
		"target_term":       targetTermBefore,
		"leader_state":      leader.getState().String(),
		"leader_term":       leader.getCurrentTerm(),
	})
	nowErr := sender.TimeoutNow(target.localID, target.localAddr, nowReq, nowResp)

	targetMoved := false
	leaderDeposed := false
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if target.getState() != targetStateBefore || target.getCurrentTerm() != targetTermBefore {
			targetMoved = true
		}
		if leader.getState() != Leader || leader.getCurrentTerm() != leaderTermBefore {
			leaderDeposed = true
		}
		if targetMoved && leaderDeposed {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}

	caEvent(t, map[string]interface{}{
		"event":                  "after_timeout_now",
		"claimed_sender_id":      "ghost-not-in-config",
		"rpc_error":              errString(nowErr),
		"target_id":              string(target.localID),
		"target_state_before":    targetStateBefore.String(),
		"target_term_before":     targetTermBefore,
		"target_state_after":     target.getState().String(),
		"target_term_after":      target.getCurrentTerm(),
		"target_moved":           targetMoved,
		"leader_id":              string(leaderID),
		"leader_state_before":    "Leader",
		"leader_term_before":     leaderTermBefore,
		"leader_state_after":     leader.getState().String(),
		"leader_term_after":      leader.getCurrentTerm(),
		"leader_deposed":         leaderDeposed,
		"observation_interval_s": 2,
	})
}

func errString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
