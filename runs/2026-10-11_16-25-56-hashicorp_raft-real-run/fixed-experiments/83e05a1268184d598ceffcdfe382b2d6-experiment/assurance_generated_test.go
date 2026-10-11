package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func caState(t *testing.T, ev map[string]interface{}) {
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceReloadConfigValidation checks that a reload whose merged
// configuration violates the validated invariants is rejected without changing
// the running configuration, and that a valid reload is accepted and visible.
func TestAssuranceReloadConfigValidation(t *testing.T) {
	c := MakeCluster(1, t, nil)
	defer c.Close()

	r := c.rafts[0]
	before := r.ReloadableConfig()
	leaseBefore := r.config().LeaderLeaseTimeout

	caState(t, map[string]interface{}{
		"event":                  "reload_probe_start",
		"node":                   string(r.localID),
		"heartbeat_ms_before":    before.HeartbeatTimeout.Milliseconds(),
		"election_ms_before":     before.ElectionTimeout.Milliseconds(),
		"leader_lease_ms_before": leaseBefore.Milliseconds(),
	})

	// Invalid: lowering the heartbeat below the (non-reloadable) leader lease.
	invalid := before
	invalid.HeartbeatTimeout = 10 * time.Millisecond
	invalid.ElectionTimeout = 10 * time.Millisecond
	invalidErr := r.ReloadConfig(invalid)
	afterInvalid := r.ReloadableConfig()
	caState(t, map[string]interface{}{
		"event":               "reload_invalid",
		"node":                string(r.localID),
		"error_text":          errStringReload(invalidErr),
		"error_empty":         invalidErr == nil,
		"config_unchanged":    afterInvalid == before,
		"heartbeat_ms_after":  afterInvalid.HeartbeatTimeout.Milliseconds(),
		"heartbeat_ms_before": before.HeartbeatTimeout.Milliseconds(),
	})

	// Valid: raising heartbeat and election together keeps the lease invariant.
	valid := before
	valid.HeartbeatTimeout = 100 * time.Millisecond
	valid.ElectionTimeout = 100 * time.Millisecond
	validErr := r.ReloadConfig(valid)
	afterValid := r.ReloadableConfig()
	caState(t, map[string]interface{}{
		"event":              "reload_valid",
		"node":               string(r.localID),
		"error_text":         errStringReload(validErr),
		"error_empty":        validErr == nil,
		"heartbeat_ms_after": afterValid.HeartbeatTimeout.Milliseconds(),
		"election_ms_after":  afterValid.ElectionTimeout.Milliseconds(),
		"lease_ms_after":     r.config().LeaderLeaseTimeout.Milliseconds(),
		"heartbeat_applied":  afterValid.HeartbeatTimeout == 100*time.Millisecond,
	})
}

func errStringReload(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
