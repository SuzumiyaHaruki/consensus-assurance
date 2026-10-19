//go:build dragonboat_audit

package dragonboat

import (
	"time"

	"github.com/lni/dragonboat/v3/internal/invariants"
)

// auditTimeout returns an RTT-based timeout with extra slack when running
// under the race detector (mirrors the upstream pto/lpto helpers).
func auditTimeout(nh *NodeHost, rttMultiple int) time.Duration {
	rtt := nh.NodeHostConfig().RTTMillisecond
	d := time.Duration(rtt*uint64(rttMultiple)) * time.Millisecond
	if invariants.Race && d < 20*time.Second {
		return 20 * time.Second
	}
	return d
}
