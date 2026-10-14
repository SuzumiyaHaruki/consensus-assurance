// Copyright (c) 2026. Assurance harness artifact (draft, not part of the target source).
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"encoding/json"
	"fmt"
	"runtime"
	"strings"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

type caTransferTrial struct {
	Event                    string   `json:"event"`
	Trial                    int      `json:"trial"`
	Mode                     string   `json:"mode"`
	LeaderID                 string   `json:"leader_id"`
	TargetID                 string   `json:"target_id"`
	TransferError            string   `json:"transfer_error"`
	FlagAfter                bool     `json:"transfer_in_progress_after"`
	NewLeaderFound           bool     `json:"new_leader_found"`
	ReElected                bool     `json:"re_elected"`
	ApplyError               string   `json:"apply_error"`
	GetConfigurationError    string   `json:"get_configuration_error"`
	StrandedTransferFrames   []string `json:"stranded_transfer_frames"`
	OldLeaderStateAtEnd      string   `json:"old_leader_state_at_end"`
	ReturnTransferError      string   `json:"return_transfer_error"`
	LeaderLastIndex          uint64   `json:"leader_last_index_at_transfer"`
	TargetLastIndex          uint64   `json:"target_last_index_at_transfer"`
	AppliedWhilePartitioned  int      `json:"applied_while_target_partitioned"`
}

func caEmit(t *testing.T, payload interface{}) {
	t.Helper()
	blob, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(blob))
}

// TestAssurance_LeadershipTransferInterrupted observes what an interrupted
// leadership transfer leaves behind on the node that started it.
//
// Each trial runs a real three-voter cluster with the in-memory transport,
// starts a leadership transfer from the leader to a follower, and (in the
// interrupted mode) partitions the leader away from the rest so that it can no
// longer reach the target and stops being able to contact a quorum. The
// partition is then healed, the old leader is made leader again through a
// normal transfer from the current leader, and its client entry points are
// exercised. The control mode runs the same transfer without any interruption.
func TestAssurance_LeadershipTransferInterrupted(t *testing.T) {
	conf := inmemConfig(t)
	conf.Logger = hclog.NewNullLogger()

	const interrupted = 10
	const controls = 2
	trial := 0
	for i := 0; i < interrupted+controls; i++ {
		caRunTransferTrial(t, conf, trial, i >= interrupted)
		trial++
	}
}

func caRunTransferTrial(t *testing.T, conf *Config, idx int, control bool) {
	t.Helper()

	ev := caTransferTrial{
		Event: "transfer_trial",
		Trial: idx,
		Mode:  "interrupted",
	}
	if control {
		ev.Mode = "control_completed"
	}

	c := MakeCluster(3, t, conf)
	defer c.Close()

	leader := c.Leader()
	followers := c.Followers()
	target := followers[0]
	ev.LeaderID = string(leader.localID)
	ev.TargetID = string(target.localID)

	if control {
		future := leader.LeadershipTransferToServer(target.localID, target.localAddr)
		if err := future.Error(); err != nil {
			ev.TransferError = err.Error()
		}
		time.Sleep(200 * time.Millisecond)
		ev.FlagAfter = leader.getLeadershipTransferInProgress()
		ev.OldLeaderStateAtEnd = leader.getState().String()
		caEmit(t, ev)
		return
	}

	// Isolate the target first so the leader accumulates committed entries that
	// the target never receives. A transfer then has real replication work, so
	// its drain loop runs instead of completing immediately.
	c.Partition([]ServerAddress{target.localAddr})
	const backlog = 200
	var last Future
	for i := 0; i < backlog; i++ {
		last = leader.Apply([]byte(fmt.Sprintf("backlog%d", i)), 0)
	}
	if err := last.Error(); err != nil {
		t.Fatalf("trial %d: backlog apply: %v", idx, err)
	}
	ev.AppliedWhilePartitioned = backlog
	ev.LeaderLastIndex = leader.getLastIndex()
	ev.TargetLastIndex = target.getLastIndex()

	future := leader.LeadershipTransferToServer(target.localID, target.localAddr)

	// Let the transfer enter its replication drain, then cut the old leader off
	// from the rest so it can no longer reach the target and stops being able
	// to contact a quorum.
	time.Sleep(30 * time.Millisecond)
	c.Partition([]ServerAddress{leader.localAddr})
	time.Sleep(300 * time.Millisecond)
	if err := future.Error(); err != nil {
		ev.TransferError = err.Error()
	}

	c.FullyConnect()

	// Wait for the rest of the cluster to settle on a leader that is not the
	// node whose transfer was interrupted.
	deadline := time.Now().Add(3 * time.Second)
	var newLeader *Raft
	for time.Now().Before(deadline) {
		leaders := c.GetInState(Leader)
		if len(leaders) == 1 && leaders[0] != leader {
			newLeader = leaders[0]
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	ev.NewLeaderFound = newLeader != nil
	ev.FlagAfter = leader.getLeadershipTransferInProgress()
	ev.StrandedTransferFrames = caStrandedTransferFrames()

	// Make the interrupted node leader again through a normal transfer and use
	// its client entry points.
	if newLeader != nil {
		if err := newLeader.LeadershipTransferToServer(leader.localID, leader.localAddr).Error(); err != nil {
			ev.ReturnTransferError = err.Error()
		}
		if caWaitForLeader(t, leader, 2*time.Second) {
			ev.ReElected = true
			ev.ApplyError = caErrString(leader.Apply([]byte("after-interrupt"), 0).Error())
			ev.GetConfigurationError = caErrString(leader.GetConfiguration().Error())
		}
	}
	ev.OldLeaderStateAtEnd = leader.getState().String()
	caEmit(t, ev)
}

func caWaitForLeader(t *testing.T, r *Raft, d time.Duration) bool {
	t.Helper()
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		if r.getState() == Leader {
			return true
		}
		time.Sleep(10 * time.Millisecond)
	}
	return false
}

func caErrString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

// caStrandedTransferFrames samples the goroutine dump and returns the stack of
// a goroutine left inside the leadership transfer path, so the stranded send is
// inspectable rather than inferred.
func caStrandedTransferFrames() []string {
	buf := make([]byte, 1<<20)
	n := runtime.Stack(buf, true)
	lines := strings.Split(string(buf[:n]), "\n")

	var frames []string
	for i := 0; i < len(lines); i++ {
		if !strings.HasPrefix(lines[i], "goroutine ") {
			continue
		}
		var block []string
		for j := i; j < len(lines) && strings.TrimSpace(lines[j]) != ""; j++ {
			block = append(block, strings.TrimSpace(lines[j]))
		}
		joined := strings.Join(block, "\n")
		if strings.Contains(joined, "leadershipTransfer") && strings.Contains(joined, "triggerDeferErrorCh") {
			for _, f := range block {
				if strings.HasPrefix(f, "goroutine ") || strings.Contains(f, ".go:") {
					frames = append(frames, f)
					if len(frames) >= 8 {
						break
					}
				}
			}
			if len(frames) > 0 {
				break
			}
		}
	}
	return frames
}
