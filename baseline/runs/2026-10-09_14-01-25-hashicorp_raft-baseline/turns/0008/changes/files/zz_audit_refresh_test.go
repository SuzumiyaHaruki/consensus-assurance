// AUDIT DIAGNOSTIC FILE (not part of the captured implementation).
//
// Control for zz_audit_stall_test.go: identical scenario, but the peer set is
// re-read from every node on each poll instead of being snapshotted once from
// c.rafts[0]. If the flake is caused by testing.go's frozen `peerSet`, this
// variant should pass consistently.
package raft

import (
	"reflect"
	"testing"
	"time"
)

func TestAuditUpgrade23RefreshPeers(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 2
	c := MakeCluster(2, t, conf)
	defer c.Close()
	_ = c.Followers()[0].localAddr

	conf = inmemConfig(t)
	conf.ProtocolVersion = 3
	c1 := MakeClusterNoBootstrap(1, t, conf)
	defer c1.Close()

	c.Merge(c1)
	c.FullyConnect()

	if err := c.Leader().AddVoter(c1.rafts[0].localID, c1.rafts[0].localAddr, 0, 1*time.Second).Error(); err != nil {
		t.Fatalf("err: %v", err)
	}
	c.EnsureSame(t)

	limit := time.Now().Add(c.longstopTimeout)
	for {
		same := true
		base := c.getConfiguration(c.rafts[0])
		for i, r := range c.rafts {
			if i == 0 {
				continue
			}
			if !reflect.DeepEqual(base, c.getConfiguration(r)) {
				same = false
				break
			}
		}
		if same {
			return
		}
		if time.Now().After(limit) {
			t.Fatalf("peer mismatch persisted despite refresh")
		}
		c.WaitEvent(nil, c.conf.CommitTimeout)
	}
}
