// AUDIT DIAGNOSTIC FILE (not part of the captured implementation).
//
// Reproduces the flaky TestRaft_ProtocolVersion_Upgrade_2_3 scenario and, when a
// peer-configuration mismatch is observed, dumps the goroutine stacks of every
// node to work/.runtime/stall_dump.txt so the stalled main loop can be located.
package raft

import (
	"fmt"
	"os"
	"reflect"
	"runtime"
	"testing"
	"time"
)

func TestAuditUpgrade23StallDump(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = 2
	c := MakeCluster(2, t, conf)
	defer c.Close()
	oldAddr := c.Followers()[0].localAddr

	conf = inmemConfig(t)
	conf.ProtocolVersion = 3
	c1 := MakeClusterNoBootstrap(1, t, conf)
	defer c1.Close()

	c.Merge(c1)
	c.FullyConnect()

	future := c.Leader().AddVoter(c1.rafts[0].localID, c1.rafts[0].localAddr, 0, 1*time.Second)
	if err := future.Error(); err != nil {
		t.Fatalf("err: %v", err)
	}

	// Mirror the original test: EnsureSame first, then EnsureSamePeers.
	c.EnsureSame(t)

	limit := time.Now().Add(c.longstopTimeout)
	peerSet := c.getConfiguration(c.rafts[0])
CHECK:
	for i, r := range c.rafts {
		if i == 0 {
			continue
		}
		otherSet := c.getConfiguration(r)
		if !reflect.DeepEqual(peerSet, otherSet) {
			if time.Now().After(limit) {
			var sb []byte
				sb = append(sb, []byte(fmt.Sprintf("=== per-node state at stall (oldAddr=%s) ===\n", oldAddr))...)
				for _, rr := range c.rafts {
					sb = append(sb, []byte(fmt.Sprintf("node %s state=%v committedIdx=%d appliedIdx=%d lastIdx=%d latestCfg=%+v\n",
						rr.localID, rr.State(), rr.CommitIndex(), rr.AppliedIndex(), rr.LastIndex(), c.getConfiguration(rr)))...)
				}
				buf := make([]byte, 1<<23)
				n := runtime.Stack(buf, true)
				sb = append(sb, buf[:n]...)
				_ = os.WriteFile(".runtime/stall_dump.txt", sb, 0o644)
				t.Fatalf("peer mismatch after timeout: %+v vs %+v; dump -> .runtime/stall_dump.txt (%d bytes)", peerSet, otherSet, len(sb))
			} else {
				goto WAIT
			}
		}
	}
	return
WAIT:
	c.WaitEvent(nil, c.conf.CommitTimeout)
	goto CHECK
}
