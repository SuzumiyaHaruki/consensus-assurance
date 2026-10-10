// Copyright (c) HashiCorp, Inc.
// SPDX-License-Identifier: MPL-2.0

package raft

import (
	"fmt"
	"testing"
	"time"
)

// TestAssurancePublicConfigurationIndex compares the index reported by the
// public GetConfiguration future with the index the node itself tracks after a
// committed membership change.
func TestAssurancePublicConfigurationIndex(t *testing.T) {
	_, trans := NewInmemTransport("")
	store := &assuranceFailStore{InmemStore: NewInmemStore()}
	r := assuranceSingleNode(t, store, trans, &MockFSM{})
	defer r.Shutdown()
	if !assuranceWaitLeader(r, 3*time.Second) {
		t.Fatalf("never became leader, state=%v", r.State())
	}
	if err := r.Apply([]byte("baseline"), 2*time.Second).Error(); err != nil {
		t.Fatalf("baseline apply: %v", err)
	}
	// A non-voter change keeps a single-voter quorum, so it commits.
	change := r.AddNonvoter(ServerID("extra"), ServerAddress("extra-addr"), 0, 2*time.Second)
	changeErr := change.Error()

	public := r.GetConfiguration()
	_ = public.Error()

	// The main thread's own view, requested the same way takeSnapshot does.
	configReq := &configurationsFuture{}
	configReq.ShutdownCh = r.shutdownCh
	configReq.init()
	select {
	case r.configurationsCh <- configReq:
	case <-r.shutdownCh:
		t.Fatalf("shutdown while asking for configurations")
	}
	if err := configReq.Error(); err != nil {
		t.Fatalf("internal configurations: %v", err)
	}

	assuranceEmit(t, map[string]interface{}{
		"event":                  "public_configuration_index",
		"add_nonvoter_error":     fmt.Sprint(changeErr),
		"add_nonvoter_index":     change.Index(),
		"public_config_index":    public.Index(),
		"internal_config_index":  configReq.Index(),
		"public_servers":         assuranceServers(public.Configuration()),
		"internal_servers":       assuranceServers(configReq.Configuration()),
		"index_reported_as_zero": public.Index() == 0,
		"indexes_disagree":       public.Index() != configReq.Index(),
	})
}
