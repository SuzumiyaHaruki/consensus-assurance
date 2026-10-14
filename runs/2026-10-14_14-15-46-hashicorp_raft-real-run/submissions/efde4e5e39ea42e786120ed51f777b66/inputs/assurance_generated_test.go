// Copyright (c) 2026. Assurance harness artifact (draft, not part of the target source).
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

func caEmit(t *testing.T, payload interface{}) {
	t.Helper()
	blob, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(blob))
}

func caVerify(leader *Raft, wait time.Duration) (verified bool, errText string, votes, quorum int, returned bool) {
	done := make(chan struct{})
	vf := &verifyFuture{}
	vf.init()
	go func() {
		defer close(done)
		leader.verifyCh <- vf
	}()
	<-done
	quorum = leader.quorumSize()
	waitCh := make(chan error, 1)
	go func() { waitCh <- vf.Error() }()
	select {
	case err := <-waitCh:
		if err != nil {
			return false, err.Error(), vf.votes, quorum, true
		}
		return true, "", vf.votes, quorum, true
	case <-time.After(wait):
		return false, "verification did not resolve", vf.votes, quorum, false
	}
}

// caManualCluster builds a cluster whose nodes may carry different timer
// settings, which MakeCluster does not allow. Every node is bootstrapped with
// the same configuration, as the target's own multi-node tests do.
func caManualCluster(t *testing.T, confs []*Config) ([]*Raft, []*InmemTransport, []ServerAddress, Configuration) {
	t.Helper()
	n := len(confs)
	var trans []*InmemTransport
	var addrs []ServerAddress
	var configuration Configuration
	for i := 0; i < n; i++ {
		addr, tr := NewInmemTransport("")
		addrs = append(addrs, addr)
		trans = append(trans, tr)
		configuration.Servers = append(configuration.Servers, Server{
			Suffrage: Voter,
			ID:       ServerID(fmt.Sprintf("node-%d-%s", i, addr)),
			Address:  addr,
		})
	}
	for i := 0; i < n; i++ {
		for j := 0; j < n; j++ {
			if i != j {
				trans[i].Connect(addrs[j], trans[j])
			}
		}
	}

	var rafts []*Raft
	for i := 0; i < n; i++ {
		conf := confs[i]
		conf.LocalID = configuration.Servers[i].ID
		conf.Logger = hclog.NewNullLogger()
		store := NewInmemStore()
		snap := NewInmemSnapshotStore()
		if err := BootstrapCluster(conf, store, store, snap, trans[i], configuration); err != nil {
			t.Fatalf("bootstrap node %d: %v", i, err)
		}
		r, err := NewRaft(conf, &MockFSM{}, store, store, snap, trans[i])
		if err != nil {
			t.Fatalf("NewRaft node %d: %v", i, err)
		}
		rafts = append(rafts, r)
	}
	return rafts, trans, addrs, configuration
}

// TestAssurance_VerifyLeaderMixedTimers tests whether the separation between a
// cut-off leader's confirmation window and a competing leader survives when the
// cluster's nodes do not share timer settings.
//
// ValidateConfig enforces LeaderLeaseTimeout <= HeartbeatTimeout <=
// ElectionTimeout per node, not across the cluster, so a member may be
// configured to campaign sooner than the leader's lease expires. In the mixed
// case the leader carries the slow settings and the two other voters the fast
// ones; the uniform case keeps every node on the leader's settings. The leader
// is always the slow node, forced by a normal leadership transfer, and a
// nonvoter stays with it so that its verifications have an acknowledgement to
// count.
func TestAssurance_VerifyLeaderMixedTimers(t *testing.T) {
	// Phase varies between trials, so the mixed case is repeated rather than
	// sampled once.
	for i := 0; i < 12; i++ {
		caRunMixedTimerTrial(t, i, true)
	}
	for i := 12; i < 14; i++ {
		caRunMixedTimerTrial(t, i, false)
	}
}

func caRunMixedTimerTrial(t *testing.T, trial int, mixed bool) {
	t.Helper()

	slow := DefaultConfig()
	slow.HeartbeatTimeout = 50 * time.Millisecond
	slow.ElectionTimeout = 50 * time.Millisecond
	slow.LeaderLeaseTimeout = 50 * time.Millisecond
	slow.CommitTimeout = 5 * time.Millisecond

	fast := DefaultConfig()
	fast.HeartbeatTimeout = 10 * time.Millisecond
	fast.ElectionTimeout = 20 * time.Millisecond
	fast.LeaderLeaseTimeout = 5 * time.Millisecond
	fast.CommitTimeout = 5 * time.Millisecond

	confs := []*Config{slow, slow, slow, slow}
	if mixed {
		confs = []*Config{slow, fast, fast, fast}
	}

	rafts, trans, addrs, configuration := caManualCluster(t, confs)
	defer func() {
		for _, r := range rafts {
			_ = r.Shutdown().Error()
		}
	}()

	// Wait for any leader, then force leadership onto the slow node 0.
	var leader *Raft
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		for _, r := range rafts {
			if r.getState() == Leader {
				leader = r
			}
		}
		if leader != nil {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if leader == nil {
		t.Fatalf("trial %d: no leader elected", trial)
	}
	if leader != rafts[0] {
		if err := leader.LeadershipTransferToServer(rafts[0].localID, rafts[0].localAddr).Error(); err != nil {
			t.Fatalf("trial %d: transfer to slow node: %v", trial, err)
		}
		deadline = time.Now().Add(5 * time.Second)
		for time.Now().Before(deadline) {
			if rafts[0].getState() == Leader {
				break
			}
			time.Sleep(5 * time.Millisecond)
		}
	}
	leader = rafts[0]
	if leader.getState() != Leader {
		t.Fatalf("trial %d: slow node is %s, not leader", trial, leader.getState())
	}

	// Node 3 becomes a nonvoter so the cut-off leader has a peer to count.
	nonvoter := rafts[3]
	if err := leader.DemoteVoter(nonvoter.localID, 0, 0).Error(); err != nil {
		t.Fatalf("trial %d: demote: %v", trial, err)
	}
	time.Sleep(100 * time.Millisecond)

	baseVerified, baseErr, baseVotes, baseQuorum, baseReturned := caVerify(leader, 2*time.Second)
	caEmit(t, map[string]interface{}{
		"event":                             "verify_baseline",
		"trial":                             trial,
		"mixed_timers":                      mixed,
		"leader_lease_ms":                   leader.config().LeaderLeaseTimeout.Milliseconds(),
		"leader_election_ms":                leader.config().ElectionTimeout.Milliseconds(),
		"voter_election_ms":                 rafts[1].config().ElectionTimeout.Milliseconds(),
		"voter_election_shorter_than_lease": rafts[1].config().ElectionTimeout < leader.config().LeaderLeaseTimeout,
		"verified":                          baseVerified,
		"error":                             baseErr,
		"votes":                             baseVotes,
		"quorum_size":                       baseQuorum,
		"returned":                          baseReturned,
	})

	if err := leader.Apply([]byte("pre-partition"), 0).Error(); err != nil {
		t.Fatalf("trial %d: apply: %v", trial, err)
	}

	// Isolate the leader and the nonvoter from the two remaining voters in both
	// directions.
	isolate := [][2]int{{0, 1}, {0, 2}, {3, 1}, {3, 2}, {1, 0}, {2, 0}, {1, 3}, {2, 3}}
	for _, pair := range isolate {
		trans[pair[0]].Disconnect(addrs[pair[1]])
	}
	partitionedAt := time.Now()

	var polls, confirmed, confirmedAfterLeader int
	var lastConfirmedMs int64 = -1
	var firstPeerLeaderMs int64 = -1
	var leaderSteppedDown bool
	var wrote bool
	var commitAheadWhileConfirming bool
	var peerCommitIndex, leaderAppliedAtCommitAhead uint64
	var commitAheadMs int64 = -1
	for i := 0; i < 400; i++ {
		if leader.getState() != Leader {
			leaderSteppedDown = true
			break
		}
		var peer *Raft
		if rafts[1].getState() == Leader {
			peer = rafts[1]
		} else if rafts[2].getState() == Leader {
			peer = rafts[2]
		}
		elapsed := time.Since(partitionedAt).Milliseconds()
		if peer != nil && firstPeerLeaderMs < 0 {
			firstPeerLeaderMs = elapsed
		}
		if peer != nil && !wrote {
			// Have the new leader commit something the cut-off leader cannot have.
			wrote = true
			_ = caWait(peer.Apply([]byte("committed-after-partition"), 0), 500*time.Millisecond)
		}
		verified, _, _, _, returned := caVerify(leader, 500*time.Millisecond)
		elapsed = time.Since(partitionedAt).Milliseconds()
		polls++
		if returned && verified {
			confirmed++
			lastConfirmedMs = elapsed
			if peer != nil {
				confirmedAfterLeader++
				if c := peer.getCommitIndex(); c > leader.getLastApplied() {
					commitAheadWhileConfirming = true
					peerCommitIndex = c
					leaderAppliedAtCommitAhead = leader.getLastApplied()
					if commitAheadMs < 0 {
						commitAheadMs = elapsed
					}
				}
			}
		}
		time.Sleep(2 * time.Millisecond)
	}

	caEmit(t, map[string]interface{}{
		"event":                             "verify_exposure",
		"trial":                             trial,
		"mixed_timers":                      mixed,
		"leader_lease_ms":                   leader.config().LeaderLeaseTimeout.Milliseconds(),
		"voter_election_ms":                 rafts[1].config().ElectionTimeout.Milliseconds(),
		"voter_election_shorter_than_lease": rafts[1].config().ElectionTimeout < leader.config().LeaderLeaseTimeout,
		"polls":                             polls,
		"confirmations":                     confirmed,
		"last_confirmation_ms":              lastConfirmedMs,
		"first_peer_leader_ms":              firstPeerLeaderMs,
		"confirmations_after_peer_leader":   confirmedAfterLeader,
		"confirmation_after_peer_leader":    confirmedAfterLeader > 0,
		"leader_stepped_down":               leaderSteppedDown,
		"leader_term":                       leader.getCurrentTerm(),
		"peer_term":                         rafts[1].getCurrentTerm(),
		"leader_applied_index":              leader.getLastApplied(),
		"peer_write_committed":              wrote,
		"commit_ahead_while_confirming":     commitAheadWhileConfirming,
		"peer_commit_index_at_overlap":      peerCommitIndex,
		"leader_applied_at_overlap":         leaderAppliedAtCommitAhead,
		"commit_ahead_ms":                   commitAheadMs,
	})
	_ = configuration
}

// caWait reports whether a future resolved within the bound.
func caWait(f Future, wait time.Duration) error {
	ch := make(chan error, 1)
	go func() { ch <- f.Error() }()
	select {
	case err := <-ch:
		return err
	case <-time.After(wait):
		return fmt.Errorf("future did not resolve")
	}
}
