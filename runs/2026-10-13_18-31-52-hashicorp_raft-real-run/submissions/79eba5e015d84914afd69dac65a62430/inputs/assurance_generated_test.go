package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func assuranceEmit(t *testing.T, fields map[string]interface{}) {
	b, err := json.Marshal(fields)
	if err != nil {
		return
	}
	fmt.Println("CA_EVENT " + string(b))
}

// assuranceVote sends a real RequestVote RPC to target from sender and returns
// the granted flag actually reported by the target.
func assuranceVote(sender, target *Raft, candidate *Raft, term uint64) bool {
	idx, t := target.getLastEntry()
	req := &RequestVoteRequest{
		RPCHeader: RPCHeader{
			ProtocolVersion: 3,
			ID:              []byte(candidate.localID),
			Addr:            sender.trans.EncodePeer(candidate.localID, candidate.localAddr),
		},
		Term:               term,
		Candidate:          sender.trans.EncodePeer(candidate.localID, candidate.localAddr),
		LastLogIndex:       idx,
		LastLogTerm:        t,
		LeadershipTransfer: true,
	}
	resp := &RequestVoteResponse{}
	if err := sender.trans.RequestVote(target.localID, target.localAddr, req, resp); err != nil {
		return false
	}
	return resp.Granted
}

// TestAssurance_VoteDurabilityAcrossRestart checks that a node reuses its
// durable last vote after a restart: a second, different candidate in the same
// term must be denied while the original candidate is still granted.
func TestAssurance_VoteDurabilityAcrossRestart(t *testing.T) {
	c := MakeCluster(3, t, nil)
	defer c.Close()

	sender := c.rafts[0]
	target := c.rafts[2]
	candA := c.rafts[1]
	candB := c.rafts[0]

	term := target.getCurrentTerm() + 5

	grantedA1 := assuranceVote(sender, target, candA, term)
	storedTerm, _ := target.stable.GetUint64(keyLastVoteTerm)
	storedCand, _ := target.stable.Get(keyLastVoteCand)
	assuranceEmit(t, map[string]interface{}{
		"event":            "before_restart_vote_a",
		"term":             term,
		"granted":          grantedA1,
		"stored_term":      storedTerm,
		"stored_cand":      string(storedCand),
		"candidate_a":      string(candA.localID),
		"target_term_after": target.getCurrentTerm(),
	})

	// Restart the target over the same stores and transport.
	if err := target.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown: %v", err)
	}
	confCopy := *c.conf
	confCopy.LocalID = target.localID
	restarted, err := NewRaft(&confCopy, c.fsms[2], c.stores[2], c.stores[2], c.snaps[2], c.trans[2])
	if err != nil {
		t.Fatalf("restart: %v", err)
	}
	defer restarted.Shutdown()
	time.Sleep(200 * time.Millisecond)

	dupTerm, _ := restarted.stable.GetUint64(keyLastVoteTerm)
	dupCand, _ := restarted.stable.Get(keyLastVoteCand)
	assuranceEmit(t, map[string]interface{}{
		"event":              "after_restart_baseline",
		"restored_term":      restarted.getCurrentTerm(),
		"restored_vote_term": dupTerm,
		"restored_vote_cand": string(dupCand),
	})

	grantedA2 := assuranceVote(sender, restarted, candA, term)
	grantedB := assuranceVote(sender, restarted, candB, term)
	grantedOld := assuranceVote(sender, restarted, candB, term-1)

	assuranceEmit(t, map[string]interface{}{
		"event":             "after_restart_votes",
		"term":              term,
		"granted_same_cand": grantedA2,
		"granted_other_cand": grantedB,
		"granted_older_term": grantedOld,
	})
}
