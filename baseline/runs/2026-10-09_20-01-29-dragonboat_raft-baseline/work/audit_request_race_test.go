package dragonboat

import (
	"fmt"
	"runtime"
	"sync"
	"testing"
)

// Exercise the actual commit-notification, expiration and documented Release
// paths concurrently. A client may use AppliedC when it does not need the
// optional early-commit result, and release after the final timeout result.
func TestAuditCommitNotificationAfterTimeoutRelease(t *testing.T) {
	for _, useResultC := range []bool{false, true} {
		name := "AppliedC"
		if useResultC {
			name = "ResultC"
		}
		t.Run(name, func(t *testing.T) {
			for i := 0; i < 100000; i++ {
				req := &RequestState{key: 1, clientID: 1, seriesID: 1, deadline: 1,
					notifyCommit: true, CompletedC: make(chan RequestResult, 1),
					committedC: make(chan RequestResult, 1), pool: &sync.Pool{}}
				p := &proposalShard{pending: map[uint64]*RequestState{1: req}, logicalClock: newLogicalClock()}
				start := make(chan struct{})
				commitDone := make(chan string, 1)
				gcDone := make(chan struct{})
				go func() {
					defer func() {
						if r := recover(); r != nil {
							commitDone <- fmt.Sprint(r)
						}
					}()
					<-start
					p.committed(1, 1, 1)
					commitDone <- ""
				}()
				go func() { <-start; p.tick(2); p.gc(); close(gcDone) }()
				close(start)
				results := req.AppliedC()
				if useResultC {
					results = req.ResultC()
				}
				result := <-results
				if result.code == requestCommitted {
					result = <-results
				}
				if !result.Timeout() {
					t.Fatal("expected timeout")
				}
				for !req.readyToRelease.ready() {
					runtime.Gosched()
				}
				req.Release()
				failure := <-commitDone
				<-gcDone
				if failure != "" {
					t.Fatalf("iteration %d: commit notifier accessed released request: %s", i, failure)
				}
			}

		})
	}
}
