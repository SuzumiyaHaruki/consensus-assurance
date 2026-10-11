package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func caRecord(t *testing.T, ev map[string]interface{}) {
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceVerifyLeaderUnderPartition measures the client-visible
// completion of VerifyLeader on a healthy leader and then on the same leader
// after it is isolated from its followers, with the leader lease set to one
// second so that the bounded completion path is the lease check.
func TestAssuranceVerifyLeaderUnderPartition(t *testing.T) {
	conf := inmemConfig(t)
	conf.HeartbeatTimeout = 300 * time.Millisecond
	conf.ElectionTimeout = 300 * time.Millisecond
	conf.LeaderLeaseTimeout = 300 * time.Millisecond

	c := MakeCluster(3, t, conf)
	defer c.Close()

	leader := c.Leader()
	if leader == nil {
		t.Fatalf("no leader elected")
	}

	caRecord(t, map[string]interface{}{
		"event":        "verify_control_start",
		"node":         string(leader.localID),
		"leader_state": leader.getState().String(),
		"lease_ms":     conf.LeaderLeaseTimeout.Milliseconds(),
	})
	start := time.Now()
	healthyErr := leader.VerifyLeader().Error()
	healthyMs := time.Since(start).Milliseconds()
	caRecord(t, map[string]interface{}{
		"event":        "verify_healthy",
		"node":         string(leader.localID),
		"error_empty":  healthyErr == nil,
		"error_text":   errString2(healthyErr),
		"elapsed_ms":   healthyMs,
		"leader_state": leader.getState().String(),
	})

	// Isolate the leader from both followers; the other two stay connected.
	c.Partition([]ServerAddress{leader.localAddr})
	caRecord(t, map[string]interface{}{
		"event":           "verify_probe_start",
		"node":            string(leader.localID),
		"leader_state":    leader.getState().String(),
		"lease_ms":        conf.LeaderLeaseTimeout.Milliseconds(),
		"peers_connected": 0,
	})

	start = time.Now()
	future := leader.VerifyLeader()
	done := make(chan error, 1)
	go func() { done <- future.Error() }()
	var probeErr error
	completed := false
	select {
	case probeErr = <-done:
		completed = true
	case <-time.After(6 * time.Second):
	}
	elapsed := time.Since(start).Milliseconds()

	caRecord(t, map[string]interface{}{
		"event":         "verify_partitioned",
		"node":          string(leader.localID),
		"completed":     completed,
		"elapsed_ms":    elapsed,
		"error_empty":   completed && probeErr == nil,
		"error_text":    errString2(probeErr),
		"leader_state":  leader.getState().String(),
		"lease_ms":      conf.LeaderLeaseTimeout.Milliseconds(),
		"wait_limit_ms": 6000,
	})
}

func errString2(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
