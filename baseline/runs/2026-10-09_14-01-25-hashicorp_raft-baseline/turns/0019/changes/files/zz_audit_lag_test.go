//go:build auditdiag

// AUDIT DIAGNOSTIC FILE (not part of the captured implementation).
// Built only with: go test -tags auditdiag ...
//
// Measures how long each node takes to observe the committed configuration
// change after AddVoter returns. Distinguishes "inherent small lag" (=> the
// frozen-peerSet helper is at fault) from "pathologically slow/stuck follower"
// (=> the raft implementation is at fault).
package raft

import (
	"testing"
	"time"
)

func TestAuditConfigPropagationLag(t *testing.T) {
	conf := inmemConfig(t)
	c := MakeCluster(2, t, conf)
	defer c.Close()

	conf = inmemConfig(t)
	c1 := MakeClusterNoBootstrap(1, t, conf)
	defer c1.Close()

	c.Merge(c1)
	c.FullyConnect()

	if auditWaitLeader(c, 10*time.Second) == nil {
		t.Fatal("no leader")
	}
	n0 := len(c.getConfiguration(c.rafts[0]).Servers)
	t0 := time.Now()
	if err := c.Leader().AddVoter(c1.rafts[0].localID, c1.rafts[0].localAddr, 0, 2*time.Second).Error(); err != nil {
		t.Fatalf("AddVoter: %v", err)
	}
	afterAdd := time.Now()

	// Immediately after AddVoter returns, is the first node already updated?
	staleAtFirstRead := len(c.getConfiguration(c.rafts[0]).Servers) == n0

	lags := make([]time.Duration, len(c.rafts))
	for i, r := range c.rafts {
		for {
			if len(c.getConfiguration(r).Servers) > n0 {
				lags[i] = time.Since(afterAdd)
				break
			}
			if time.Since(afterAdd) > 5*time.Second {
				lags[i] = -1
				break
			}
			time.Sleep(100 * time.Microsecond)
		}
	}
	t.Logf("staleAtFirstRead=%v lags(ms after AddVoter):", staleAtFirstRead)
	for i, l := range lags {
		t.Logf("  node%d %v: %v", i, c.rafts[i].localID, l)
	}
	_ = t0
}
