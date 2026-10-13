package raft

import (
	"fmt"
	"io"
	"sync"
	"testing"
	"time"
)

// stallReader signals when its first Read call begins and then blocks until
// released. A Read that blocks for a long time is what a caller-supplied
// backup stream can do to the handler that consumes it.
type stallReader struct {
	started chan struct{}
	release chan struct{}
	once    sync.Once
}

func (s *stallReader) Read(p []byte) (int, error) {
	s.once.Do(func() { close(s.started) })
	<-s.release
	return 0, io.ErrUnexpectedEOF
}

// TestAssurance_QueuedDutyAtShutdown observes whether a duty that the public
// API already accepted (a Barrier future handed to the caller) still has a
// completion path once the node loses authority by Shutdown rather than by
// stepping down.
//
// Initialization: MakeCluster(3, conf) with conf.BatchApplyCh = true (a
// documented public option that buffers applyCh to MaxAppendEntries) bootstraps
// a real three-node cluster and elects a leader. The main loop is then occupied
// through the public Restore API with a caller-supplied reader that stalls on
// its first Read, so the loop is provably inside a handler and cannot select on
// applyCh again. A Barrier future is then enqueued by the ordinary public path.
func TestAssurance_QueuedDutyAtShutdown(t *testing.T) {
	conf := inmemConfig(t)
	conf.BatchApplyCh = true
	c := MakeCluster(3, t, conf)
	defer c.Close()

	leader := c.Leader()
	leaderAddr := string(leader.localAddr)

	// Control: the same public call completes while a producer is available.
	controlErr := ""
	if err := leader.Barrier(0).Error(); err != nil {
		controlErr = err.Error()
	}

	// Occupy the main loop with the public Restore path and a reader that
	// stalls. The reader's first Read is the handshake.
	reader := &stallReader{started: make(chan struct{}), release: make(chan struct{})}
	restoreErr := make(chan error, 1)
	go func() {
		restoreErr <- leader.Restore(&SnapshotMeta{Version: 1, ID: "assurance-stall", Index: 1, Term: 1, Size: 1}, reader, 0)
	}()

	handshake := "inside_restore_read"
	select {
	case <-reader.started:
	case <-time.After(5 * time.Second):
		handshake = "timeout"
	}

	// Accept a duty through the ordinary public path: the send into the
	// buffered apply channel succeeds and the caller holds the future.
	accepted := make(chan Future, 1)
	go func() { accepted <- leader.Barrier(0) }()
	var duty Future
	dutyAccepted := true
	select {
	case duty = <-accepted:
	case <-time.After(5 * time.Second):
		dutyAccepted = false
	}
	stateAtAccept := leader.State().String()

	// Lose authority by shutdown while the duty sits in the buffer.
	leader.Shutdown()

	waited := 3 * time.Second
	result := "not_attempted"
	waitedMs := int64(0)
	if dutyAccepted {
		waitStart := time.Now()
		done := make(chan error, 1)
		go func() { done <- duty.Error() }()
		result = "no_completion"
		select {
		case err := <-done:
			result = fmt.Sprintf("completed:%v", err)
		case <-time.After(waited):
		}
		waitedMs = time.Since(waitStart).Milliseconds()
	}

	queued := len(leader.applyCh)
	capacity := cap(leader.applyCh)
	stateAfter := leader.State().String()

	// Release the stalled reader so the occupied handler can return and the
	// node can finish shutting down.
	close(reader.release)
	restoreResult := ""
	select {
	case err := <-restoreErr:
		if err != nil {
			restoreResult = err.Error()
		}
	case <-time.After(3 * time.Second):
		restoreResult = "restore still blocked"
	}

	fmt.Printf("CA_EVENT {\"event\":\"queued_duty_at_shutdown\",\"leader_addr\":%q,"+
		"\"control_barrier_err\":%q,\"freeze_handshake\":%q,\"state_at_accept\":%q,"+
		"\"state_after_shutdown\":%q,\"duty_accepted\":%t,\"queued_in_apply_ch\":%d,"+
		"\"apply_ch_capacity\":%d,\"waited_ms\":%d,\"result\":%q,\"restore_after_release\":%q}\n",
		leaderAddr, controlErr, handshake, stateAtAccept, stateAfter,
		dutyAccepted, queued, capacity, waitedMs, result, restoreResult)
}
