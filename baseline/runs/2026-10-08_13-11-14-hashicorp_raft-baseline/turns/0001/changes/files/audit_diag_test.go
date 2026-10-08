// Diagnostic-only test added by the audit. It does NOT modify the captured
// implementation; delete this file to restore the tree to its original shape.
//
// Purpose: show that after AddVoter the Raft nodes DO converge on the new
// configuration, and that testing.go:EnsureSamePeers fails intermittently only
// because it captures peerSet from c.rafts[0] once and never refreshes it.
package raft

import (
	"reflect"
	"testing"
	"time"
)

func TestAudit_EnsureSamePeers_StalePeerSetCapture(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 2
	c := MakeCluster(2, t, conf)
	defer c.Close()

	conf = inmemConfig(t)
	conf.ProtocolVersion = 3
	c1 := MakeClusterNoBootstrap(1, t, conf)

	c.Merge(c1)
	c.FullyConnect()

	future := c.Leader().AddVoter(c1.rafts[0].localID, c1.rafts[0].localAddr, 0, 1*time.Second)
	if err := future.Error(); err != nil {
		t.Fatalf("err: %v", err)
	}

	// Mimic exactly what EnsureSamePeers does on its first read.
	peerSet := c.getConfiguration(c.rafts[0])
	t.Logf("captured peerSet from rafts[0] immediately after AddVoter: n=%d %+v",
		len(peerSet.Servers), peerSet)

	// Now poll all nodes and show they converge.
	deadline := time.Now().Add(5 * time.Second)
	for {
		cfgs := make([]Configuration, len(c.rafts))
		for j := range c.rafts {
			cfgs[j] = c.getConfiguration(c.rafts[j])
		}
		converged := true
		for j := 1; j < len(cfgs); j++ {
			if !reflect.DeepEqual(cfgs[0], cfgs[j]) {
				converged = false
			}
		}
		t.Logf("live: rafts[0]=%d rafts[1]=%d rafts[2]=%d converged=%v",
			len(cfgs[0].Servers), len(cfgs[1].Servers), len(cfgs[2].Servers), converged)
		if converged {
			if len(peerSet.Servers) != len(cfgs[0].Servers) {
				t.Logf("CONFIRMED: stale peerSet had %d servers while the cluster live-reports %d; "+
					"EnsureSamePeers compares the stale capture forever and times out",
					len(peerSet.Servers), len(cfgs[0].Servers))
			} else {
				t.Logf("no staleness observed in this run (peerSet was already current)")
			}
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("cluster did not converge to a single configuration within 5s: %+v", cfgs)
		}
		time.Sleep(20 * time.Millisecond)
	}
}
