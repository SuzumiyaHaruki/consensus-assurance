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

func caErrString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

// caVerify issues one verification through the same channel the exported
// VerifyLeader API uses and reports whether it was confirmed, its error, and
// the tally and quorum the future ended with.
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
		return err == nil, caErrString(err), vf.votes, quorum, true
	case <-time.After(wait):
		return false, "verification did not resolve", vf.votes, quorum, false
	}
}

func caPeerLeader(c *cluster, leader, nonvoter *Raft) *Raft {
	for _, r := range c.rafts {
		if r == leader || r == nonvoter {
			continue
		}
		if r.getState() == Leader {
			return r
		}
	}
	return nil
}

// TestAssurance_VerifyLeaderConfirmationWindow measures how long a leader that
// has lost contact with every other voter but can still reach a nonvoter keeps
// obtaining successful verifications, and whether those confirmations continue
// after the voters it cannot reach have elected their own leader.
//
// The cluster is four voters with one demoted to nonvoter, so three voters and
// a voter quorum of two. In the interrupted trial the leader is partitioned
// together with the nonvoter; in the control the leader is partitioned alone.
// After the partition the leader is verified repeatedly until it stops being
// confirmed or the bounded loop ends, and each poll records whether a peer
// leader existed at that moment.
func TestAssurance_VerifyLeaderConfirmationWindow(t *testing.T) {
	conf := inmemConfig(t)
	conf.Logger = hclog.NewNullLogger()

	// The partition lands at whatever phase the peers' randomized election
	// timers happen to be in, so the relation between the last confirmation and
	// the competing leader is measured over repeated trials rather than once.
	for i := 0; i < 12; i++ {
		caRunWindowTrial(t, conf, i, true)
	}
	for i := 12; i < 14; i++ {
		caRunWindowTrial(t, conf, i, false)
	}
}

func caRunWindowTrial(t *testing.T, conf *Config, trial int, withNonvoter bool) {
	t.Helper()

	c := MakeCluster(4, t, conf)
	defer c.Close()

	leader := c.Leader()
	followers := c.Followers()
	nonvoter := followers[0]

	if err := leader.DemoteVoter(nonvoter.localID, 0, 0).Error(); err != nil {
		t.Fatalf("trial %d: demote: %v", trial, err)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if !hasVote(leader.GetConfiguration().Configuration(), nonvoter.localID) {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if hasVote(leader.GetConfiguration().Configuration(), nonvoter.localID) {
		t.Fatalf("trial %d: nonvoter still has a vote", trial)
	}

	baseVerified, baseErr, baseVotes, baseQuorum, baseReturned := caVerify(leader, 2*time.Second)
	caEmit(t, map[string]interface{}{
		"event":                    "verify_baseline",
		"trial":                    trial,
		"nonvoter_reachable_only":  withNonvoter,
		"verified":                 baseVerified,
		"error":                    baseErr,
		"votes":                    baseVotes,
		"quorum_size":              baseQuorum,
		"returned":                 baseReturned,
		"leader_term":              leader.getCurrentTerm(),
		"nonvoter_term":            nonvoter.getCurrentTerm(),
	})

	if err := leader.Apply([]byte("pre-partition"), 0).Error(); err != nil {
		t.Fatalf("trial %d: pre-partition apply: %v", trial, err)
	}

	if withNonvoter {
		c.Partition([]ServerAddress{leader.localAddr, nonvoter.localAddr})
	} else {
		c.Partition([]ServerAddress{leader.localAddr})
	}
	partitionedAt := time.Now()

	var polls, confirmed, confirmedAfterLeader int
	var maxConfirmedAfterLeaderMs int64
	var firstPeerLeaderMs int64 = -1
	var lastConfirmedMs int64 = -1
	var peerLeaderSeen, leaderSteppedDown bool
	var peerWriteIndex, peerCommitIndex uint64

	for i := 0; i < 500; i++ {
		stateBefore := leader.getState()
		peerLeader := caPeerLeader(c, leader, nonvoter)
		if peerLeader != nil {
			if !peerLeaderSeen {
				firstPeerLeaderMs = time.Since(partitionedAt).Milliseconds()
			}
			peerLeaderSeen = true
		}
		if stateBefore != Leader {
			leaderSteppedDown = true
			break
		}

		verified, _, _, _, returned := caVerify(leader, 500*time.Millisecond)
		elapsed := time.Since(partitionedAt).Milliseconds()
		polls++
		if returned && verified {
			confirmed++
			lastConfirmedMs = elapsed
			if peerLeaderSeen {
				confirmedAfterLeader++
				if elapsed > maxConfirmedAfterLeaderMs {
					maxConfirmedAfterLeaderMs = elapsed
				}
			}
		}
		if leader.getState() != Leader {
			leaderSteppedDown = true
			break
		}
		if peerLeaderSeen && confirmedAfterLeader == 0 && elapsed > firstPeerLeaderMs+500 {
			// Enough time after the peer leader appeared with no confirmation.
			break
		}
		time.Sleep(5 * time.Millisecond)
	}

	// Keep watching after the confirmed leader stopped being confirmable, so the
	// relation between the last confirmation and the appearance of a competing
	// leader is observed rather than left unmeasured.
	watchDeadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(watchDeadline) {
		if peerLeader := caPeerLeader(c, leader, nonvoter); peerLeader != nil {
			if firstPeerLeaderMs < 0 {
				firstPeerLeaderMs = time.Since(partitionedAt).Milliseconds()
			}
			break
		}
		time.Sleep(5 * time.Millisecond)
	}

	// What the detached majority did, for context on the timeline above.
	if peerLeader := caPeerLeader(c, leader, nonvoter); peerLeader != nil {
		future := peerLeader.Apply([]byte("committed-after-partition"), 0)
		if err := future.Error(); err == nil {
			peerWriteIndex = future.Index()
		}
		peerCommitIndex = peerLeader.getCommitIndex()
	}

	caEmit(t, map[string]interface{}{
		"event":                        "verify_exposure",
		"trial":                        trial,
		"nonvoter_reachable_only":      withNonvoter,
		"polls":                        polls,
		"confirmations":                confirmed,
		"confirmations_after_peer_leader": confirmedAfterLeader,
		"max_confirmation_after_peer_leader_ms": maxConfirmedAfterLeaderMs,
		"first_peer_leader_ms":         firstPeerLeaderMs,
		"last_confirmation_ms":         lastConfirmedMs,
		"confirmation_precedes_peer_leader": lastConfirmedMs >= 0 && (firstPeerLeaderMs < 0 || lastConfirmedMs < firstPeerLeaderMs),
		"leader_stepped_down":          leaderSteppedDown,
		"leader_term":                  leader.getCurrentTerm(),
		"nonvoter_term":                nonvoter.getCurrentTerm(),
		"leader_applied_index":         leader.getLastApplied(),
		"peer_write_index":             peerWriteIndex,
		"peer_commit_index":            peerCommitIndex,
	})
}
