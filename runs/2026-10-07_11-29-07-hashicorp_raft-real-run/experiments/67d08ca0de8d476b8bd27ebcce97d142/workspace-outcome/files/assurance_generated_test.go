// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0
//
// Generated assurance harness. A single-voter leader is parked inside its own
// dispatch path while more client requests are queued than the buffered apply
// channel can hold, and the node is then shut down; the harness counts how many
// requests were accepted while the node was leading and how many of their
// futures still had not completed after the shutdown joined. It reports raw
// counts only.

package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"sync/atomic"
	"testing"
	"time"
)

func assuranceRaceEvent(v map[string]interface{}) {
	payload, err := json.Marshal(v)
	if err != nil {
		fmt.Println("assurance: event marshal failed:", err)
		return
	}
	fmt.Println("CA_EVENT " + string(payload))
}

type assuranceRaceFSM struct{}

func (assuranceRaceFSM) Apply(*Log) interface{}         { return nil }
func (assuranceRaceFSM) Snapshot() (FSMSnapshot, error) { return assuranceRaceSnapshot{}, nil }
func (assuranceRaceFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceRaceSnapshot struct{}

func (assuranceRaceSnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceRaceSnapshot) Release()                     {}

// assuranceGateLogs holds exactly one StoreLogs call after it is armed, which
// parks the main goroutine inside the leader's dispatch path.
type assuranceGateLogs struct {
	*InmemStore
	arm     atomic.Bool
	blocked atomic.Bool
	entered chan struct{}
	release chan struct{}
}

func (g *assuranceGateLogs) StoreLog(l *Log) error { return g.StoreLogs([]*Log{l}) }

func (g *assuranceGateLogs) StoreLogs(logs []*Log) error {
	if g.arm.Load() && g.blocked.CompareAndSwap(false, true) {
		g.entered <- struct{}{}
		<-g.release
	}
	return g.InmemStore.StoreLogs(logs)
}

func assuranceRaceWaitFor(what string, cond func() bool, limit time.Duration) bool {
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if cond() {
			return true
		}
		time.Sleep(500 * time.Microsecond)
	}
	return false
}

func TestAssuranceAcceptedRequestThenShutdown(t *testing.T) {
	const (
		op    = "requests-accepted-before-shutdown"
		node  = ServerID("n1")
		extra = 200
	)

	conf := DefaultConfig()
	conf.LocalID = node
	conf.ProtocolVersion = 3
	conf.LogLevel = "ERROR"
	conf.BatchApplyCh = true
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 200 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond
	conf.CommitTimeout = 50 * time.Millisecond
	conf.SnapshotInterval = time.Hour
	conf.SnapshotThreshold = 100000
	conf.TrailingLogs = 100000

	logs := &assuranceGateLogs{InmemStore: NewInmemStore(), entered: make(chan struct{}, 1), release: make(chan struct{})}
	_, trans := NewInmemTransport(ServerAddress(node))
	r, err := NewRaft(conf, assuranceRaceFSM{}, logs, NewInmemStore(), NewInmemSnapshotStore(), trans)
	if err != nil {
		assuranceRaceEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(node), "op": op, "detail": err.Error()})
		t.Fatalf("assurance: NewRaft: %v", err)
	}
	configuration := Configuration{Servers: []Server{{ID: node, Address: trans.LocalAddr(), Suffrage: Voter}}}
	if err := r.BootstrapCluster(configuration).Error(); err != nil {
		assuranceRaceEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(node), "op": op, "detail": "bootstrap: " + err.Error()})
		t.Fatalf("assurance: bootstrap: %v", err)
	}
	if !assuranceRaceWaitFor("leader", func() bool { return r.State() == Leader }, 5*time.Second) {
		assuranceRaceEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(node), "op": op, "detail": "node never became leader"})
		t.Fatalf("assurance: node never became leader")
	}
	time.Sleep(100 * time.Millisecond)

	// Park the main goroutine inside the leader's dispatch path, then queue more
	// requests than the buffered apply channel can hold.
	logs.arm.Store(true)
	blocker := r.Apply([]byte("blocker"), 5*time.Second)
	select {
	case <-logs.entered:
	case <-time.After(5 * time.Second):
		assuranceRaceEvent(map[string]interface{}{"event": "assurance_setup_failed", "node": string(node), "op": op, "detail": "the main goroutine never reached the gated store call"})
		t.Fatalf("assurance: main goroutine never reached the gated store call")
	}

	results := make(chan Future, extra)
	for i := 0; i < extra; i++ {
		go func() { results <- r.Apply([]byte("queued"), 0) }()
	}
	time.Sleep(300 * time.Millisecond)

	shutdown := r.Shutdown()
	close(logs.release)
	if err := shutdown.Error(); err != nil {
		t.Fatalf("assurance: shutdown: %v", err)
	}

	var accepted []*logFuture
	rejectedShutdown, other := 0, 0
	for i := 0; i < extra; i++ {
		select {
		case f := <-results:
			switch v := f.(type) {
			case errorFuture:
				if v.err == ErrRaftShutdown {
					rejectedShutdown++
				} else {
					other++
				}
			case *logFuture:
				accepted = append(accepted, v)
			}
		case <-time.After(5 * time.Second):
			t.Fatalf("assurance: a queued request never returned from Apply")
		}
	}
	unresolved := 0
	for _, f := range accepted {
		select {
		case <-f.errCh:
		default:
			unresolved++
		}
	}
	blockerErr := fmt.Sprintf("%v", blocker.Error())
	logLast, _ := logs.LastIndex()

	assuranceRaceEvent(map[string]interface{}{
		"event":           "requests_issued_while_active",
		"node":            string(node),
		"op":              op,
		"issued":          extra,
		"node_state":      "Leader",
		"main_thread_busy": true,
	})
	assuranceRaceEvent(map[string]interface{}{
		"event":                      "accepted_requests_observed",
		"node":                       string(node),
		"op":                         op,
		"issued":                     extra,
		"accepted":                   len(accepted),
		"rejected_shutdown":          rejectedShutdown,
		"completed_other":            other,
		"unresolved_total":           unresolved,
		"node_state_after_shutdown":  r.State().String(),
		"blocker_result":             blockerErr,
		"log_last_index":             logLast,
	})
}
