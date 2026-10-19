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
