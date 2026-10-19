//go:build dragonboat_audit

// Audit-only reproduction tests. These files are not part of the captured
// implementation; they only exercise it. Delete before any upstream diff.
// Run with: -tags dragonboat_no_rocksdb,dragonboat_audit

package dragonboat

import (
	"testing"
	"time"

	"github.com/lni/dragonboat/v3/internal/vfs"
)

// Measures dispatch latency of both read paths with a timeout long enough for
// both to complete, so the effect is the one-tick dispatch delay rather than an
// expiry.
func TestAuditNodeUserReadIndexDispatchLatency(t *testing.T) {
	fs := vfs.GetTestFS()
	to := &testOption{
		defaultTestNode: true,
		tf: func(nh *NodeHost) {
			rtt := nh.NodeHostConfig().RTTMillisecond
			timeout := time.Duration(rtt*20) * time.Millisecond
			nu, err := nh.GetNodeUser(1)
			if err != nil {
				t.Fatalf("GetNodeUser failed: %v", err)
			}
			for i := 0; i < 3; i++ {
				start := time.Now()
				rs, err := nh.ReadIndex(1, timeout)
				if err != nil {
					t.Fatalf("NodeHost.ReadIndex failed: %v", err)
				}
				v := <-rs.ResultC()
				nhLatency := time.Since(start)

				start = time.Now()
				rs, err = nu.ReadIndex(timeout)
				if err != nil {
					t.Fatalf("NodeUser.ReadIndex failed: %v", err)
				}
				v2 := <-rs.ResultC()
				nuLatency := time.Since(start)

				t.Logf("round %d: NodeHost.ReadIndex=%v (completed=%t) "+
					"NodeUser.ReadIndex=%v (completed=%t) rtt=%dms",
					i, nhLatency, v.Completed(), nuLatency, v2.Completed(), rtt)
			}
		},
	}
	runNodeHostTest(t, to, fs)
}

// Linearizable reads are documented to work on any non-witness node; on a
// follower the ReadIndex request has to be forwarded to the leader and
// confirmed by the leader's heartbeat round. This measures both paths on a
// healthy two-node cluster with a generous timeout.
func TestAuditFollowerReadIndex(t *testing.T) {
	fs := vfs.GetTestFS()
	dir := singleNodeHostTestDir
	if err := fs.RemoveAll(dir); err != nil {
		t.Fatalf("%v", err)
	}
	defer func() {
		if err := fs.RemoveAll(dir); err != nil {
			t.Fatalf("%v", err)
		}
	}()
	nh1, nh2, _, _, err := createRateLimitedTwoTestNodeHosts(nodeHostTestAddr1,
		nodeHostTestAddr2, fs.PathJoin(dir, "nh1"), fs.PathJoin(dir, "nh2"), fs)
	if err != nil {
		t.Fatalf("failed to create nodehosts: %v", err)
	}
	defer nh1.Stop()
	defer nh2.Stop()
	waitForLeaderToBeElected(t, nh1, 1)
	waitForLeaderToBeElected(t, nh2, 1)
	leaderID, ready, err := nh1.GetLeaderID(1)
	if err != nil || !ready {
		t.Fatalf("no leader: %v, %t", err, ready)
	}
	leader, follower := nh1, nh2
	if leaderID != 1 {
		leader, follower = nh2, nh1
	}
	rtt := leader.NodeHostConfig().RTTMillisecond
	timeout := auditTimeout(leader, 30)
	measure := func(nh *NodeHost, name string) time.Duration {
		start := time.Now()
		rs, err := nh.ReadIndex(1, timeout)
		if err != nil {
			t.Fatalf("%s ReadIndex failed: %v", name, err)
		}
		v := <-rs.ResultC()
		elapsed := time.Since(start)
		if !v.Completed() {
			t.Fatalf("%s ReadIndex did not complete (dropped=%t timeout=%t)",
				name, v.Dropped(), v.Timeout())
		}
		return elapsed
	}
	for i := 0; i < 3; i++ {
		l := measure(leader, "leader")
		f := measure(follower, "follower")
		t.Logf("round %d: leader=%v follower=%v rtt=%dms", i, l, f, rtt)
	}
}

// NodeHost.ReadIndex wakes the execution engine so the read request is
// dispatched immediately, while nodeUser.ReadIndex does not. With a one-RTT
// timeout the request is only picked up by the next tick, by which time its
// deadline has already expired.
func TestAuditNodeUserReadIndexOneTickTimeout(t *testing.T) {
	fs := vfs.GetTestFS()
	to := &testOption{
		defaultTestNode: true,
		tf: func(nh *NodeHost) {
			rtt := nh.NodeHostConfig().RTTMillisecond
			timeout := time.Duration(rtt) * time.Millisecond

			// control: NodeHost API with the same timeout
			rs, err := nh.ReadIndex(1, timeout)
			if err != nil {
				t.Fatalf("NodeHost.ReadIndex failed: %v", err)
			}
			if v := <-rs.ResultC(); !v.Completed() {
				t.Errorf("NodeHost.ReadIndex did not complete within %v", timeout)
			}

			// subject: INodeUser API with the same timeout
			nu, err := nh.GetNodeUser(1)
			if err != nil {
				t.Fatalf("GetNodeUser failed: %v", err)
			}
			rs, err = nu.ReadIndex(timeout)
			if err != nil {
				t.Fatalf("NodeUser.ReadIndex failed: %v", err)
			}
			if v := <-rs.ResultC(); !v.Completed() {
				t.Errorf("NodeUser.ReadIndex did not complete within %v: "+
					"completed=%t dropped=%t timeout=%t rejected=%t",
					timeout, v.Completed(), v.Dropped(), v.Timeout(), v.Rejected())
			}
		},
	}
	runNodeHostTest(t, to, fs)
}

// Characterises the boundary: a two-RTT timeout still succeeds via the
// INodeUser path because the next tick (one RTT later) leaves one tick of
// slack. One RTT has no slack and fails (see the test above).
func TestAuditNodeUserReadIndexTwoTickTimeout(t *testing.T) {
	fs := vfs.GetTestFS()
	to := &testOption{
		defaultTestNode: true,
		tf: func(nh *NodeHost) {
			rtt := nh.NodeHostConfig().RTTMillisecond
			timeout := 2 * time.Duration(rtt) * time.Millisecond
			nu, err := nh.GetNodeUser(1)
			if err != nil {
				t.Fatalf("GetNodeUser failed: %v", err)
			}
			rs, err := nu.ReadIndex(timeout)
			if err != nil {
				t.Fatalf("NodeUser.ReadIndex failed: %v", err)
			}
			if v := <-rs.ResultC(); !v.Completed() {
				t.Fatalf("NodeUser.ReadIndex with a 2-RTT timeout did not complete")
			}
		},
	}
	runNodeHostTest(t, to, fs)
}
