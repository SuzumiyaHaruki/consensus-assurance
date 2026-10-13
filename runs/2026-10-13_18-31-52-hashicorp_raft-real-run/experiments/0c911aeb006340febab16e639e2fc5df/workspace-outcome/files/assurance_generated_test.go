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

// assuranceVote2 sends a real RequestVote RPC over the given transport and
// returns (granted, delivered).
func assuranceVote2(sender Transport, target *Raft, candID ServerID, candAddr ServerAddress, term uint64) (bool, bool) {
	idx, t := target.getLastEntry()
	req := &RequestVoteRequest{
		RPCHeader: RPCHeader{
			ProtocolVersion: 3,
			ID:              []byte(candID),
			Addr:            sender.EncodePeer(candID, candAddr),
		},
		Term:               term,
		Candidate:          sender.EncodePeer(candID, candAddr),
		LastLogIndex:       idx,
		LastLogTerm:        t,
		LeadershipTransfer: true,
	}
	resp := &RequestVoteResponse{}
	if err := sender.RequestVote(target.localID, target.localAddr, req, resp); err != nil {
		return false, false
	}
	return resp.Granted, true
}

// TestAssurance_VoteDurabilityAcrossRestart2 isolates the target from its
// peers and probes with a dedicated transport inside the election-timer window,
// so the same-term duplicate-vote rule is actually applicable after restart.
func TestAssurance_VoteDurabilityAcrossRestart2(t *testing.T) {
	c := MakeCluster(3, t, nil)
	defer c.Close()

	target := c.rafts[2]
	candA := c.rafts[1]
	candB := c.rafts[0]

	// Dedicated probe transport, connected only to the target's transport.
	probeAddr, probeTrans := NewInmemTransport(NewInmemAddr())
	probeTrans.Connect(target.localAddr, c.trans[2])
	c.Disconnect(target.localAddr)

	term := target.getCurrentTerm() + 5
	granted1, delivered1 := assuranceVote2(probeTrans, target, candA.localID, candA.localAddr, term)
	storedTerm, _ := target.stable.GetUint64(keyLastVoteTerm)
	storedCand, _ := target.stable.Get(keyLastVoteCand)
	assuranceEmit(t, map[string]interface{}{
		"event":         "before_restart_vote_a",
		"probe_addr":    string(probeAddr),
		"term":          term,
		"delivered":     delivered1,
		"granted":       granted1,
		"stored_term":   storedTerm,
		"stored_cand":   string(storedCand),
		"candidate_a":   string(candA.localID),
		"target_term":   target.getCurrentTerm(),
	})

	// Restart immediately so no election timer interposes.
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

	restoredTerm := restarted.getCurrentTerm()
	dupTerm, _ := restarted.stable.GetUint64(keyLastVoteTerm)
	dupCand, _ := restarted.stable.Get(keyLastVoteCand)
	applicable := restoredTerm == term && dupTerm == term
	assuranceEmit(t, map[string]interface{}{
		"event":              "after_restart_baseline",
		"restored_term":      restoredTerm,
		"restored_vote_term": dupTerm,
		"restored_vote_cand": string(dupCand),
		"applicable":         applicable,
	})

	// Probe inside the election-timer window.
	startProbe := time.Now()
	sameCand, d1 := assuranceVote2(probeTrans, restarted, candA.localID, candA.localAddr, term)
	otherCand, d2 := assuranceVote2(probeTrans, restarted, candB.localID, candB.localAddr, term)
	olderTerm, d3 := assuranceVote2(probeTrans, restarted, candB.localID, candB.localAddr, term-1)
	assuranceEmit(t, map[string]interface{}{
		"event":              "after_restart_votes",
		"term":               term,
		"probe_elapsed_ms":   time.Since(startProbe).Milliseconds(),
		"term_at_probe_end":  restarted.getCurrentTerm(),
		"applicable":         applicable,
		"same_cand_granted":  sameCand,
		"same_cand_delivered": d1,
		"other_cand_granted": otherCand,
		"other_cand_delivered": d2,
		"older_term_granted": olderTerm,
		"older_term_delivered": d3,
	})
}
