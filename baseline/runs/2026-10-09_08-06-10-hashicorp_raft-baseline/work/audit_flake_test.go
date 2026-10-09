package raft

// Diagnostic-only test (NOT part of the captured implementation).
// Purpose: decide whether the flaky EnsureSamePeers failures reported in
// report.md are a benign replication/read lag or a genuine stall.
//
// It rebuilds the TestRaft_HasExistingState scenario, calls AddVoter, then
// polls the non-quorum follower's latest configuration up to a long deadline,
// recording how long convergence actually took.

import (
	"reflect"
	"testing"
	"time"
)

func auditConfigLooksUpToDate(c *cluster, r *Raft, want Configuration) bool {
	got := c.getConfiguration(r)
	return reflect.DeepEqual(got, want)
}

func TestAudit_ConfigConvergenceLag(t *testing.T) {
	const iters = 40
	const deadline = 60 * time.Second
	var over1s, over5s, never int
	var maxLag time.Duration

	for i := 0; i < iters; i++ {
		func() {
			c := MakeCluster(2, t, nil)
			defer c.Close()
			c1 := MakeClusterNoBootstrap(1, t, nil)
			defer c1.Close()

			c.Merge(c1)
			c.FullyConnect()

			leader := c.Leader()
			fut := leader.AddVoter(c1.rafts[0].localID, c1.rafts[0].localAddr, 0, 0)
			if err := fut.Error(); err != nil {
				t.Fatalf("AddVoter failed: %v", err)
			}
			want := leader.GetConfiguration().Configuration()

			// The straggler is any raft in c that is not the leader.
			var straggler *Raft
			for _, r := range c.rafts {
				if r != leader {
					straggler = r
					break
				}
			}
			if straggler == nil {
				t.Fatal("no straggler?")
			}

			start := time.Now()
			var converged bool
			for time.Since(start) < deadline {
				if auditConfigLooksUpToDate(c, straggler, want) {
					converged = true
					break
				}
				time.Sleep(10 * time.Millisecond)
			}
			lag := time.Since(start)
			if lag > maxLag {
				maxLag = lag
			}
			if !converged {
				never++
				t.Logf("iter %d: NEVER converged within %v; straggler=%v want=%v",
					i, deadline, c.getConfiguration(straggler), want)
			} else if lag > 5*time.Second {
				over5s++
				t.Logf("iter %d: converged after %v (>5s test window)", i, lag)
			} else if lag > 1*time.Second {
				over1s++
				t.Logf("iter %d: converged after %v (>1s)", i, lag)
			}
		}()
	}
	t.Logf("SUMMARY iters=%d over1s=%d over5s=%d never=%d maxLag=%v",
		iters, over1s, over5s, never, maxLag)
}
