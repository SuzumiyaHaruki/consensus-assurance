package raft

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func assuranceEmitHeartbeat(t *testing.T, event map[string]interface{}) {
	payload, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("assurance: cannot encode event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(payload))
}

// TestAssuranceHeartbeatAfterShutdown compares the response behaviour of the
// transport heartbeat handler while the node is running with its behaviour
// after the node has been shut down, using the same request on both paths.
func TestAssuranceHeartbeatAfterShutdown(t *testing.T) {
	store := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("")

	configuration := Configuration{Servers: []Server{{
		Suffrage: Voter,
		ID:       ServerID(addr),
		Address:  addr,
	}}}

	conf := DefaultConfig()
	conf.LocalID = ServerID(addr)
	conf.LogLevel = "ERROR"
	conf.HeartbeatTimeout = 50 * time.Millisecond
	conf.ElectionTimeout = 100 * time.Millisecond
	conf.LeaderLeaseTimeout = 50 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond

	if err := BootstrapCluster(conf, store, store, snaps, trans, configuration); err != nil {
		t.Fatalf("assurance: bootstrap failed: %v", err)
	}
	r, err := NewRaft(conf, &MockFSM{}, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("assurance: NewRaft failed: %v", err)
	}

	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) && r.State() != Leader {
		time.Sleep(5 * time.Millisecond)
	}

	probe := func(phase string) {
		rpc := RPC{
			Command: &AppendEntriesRequest{
				RPCHeader: r.getRPCHeader(),
				Term:      r.getCurrentTerm(),
				Leader:    trans.EncodePeer(ServerID(addr), addr),
			},
			RespChan: make(chan RPCResponse, 1),
		}
		start := time.Now()
		r.processHeartbeat(rpc)
		select {
		case resp := <-rpc.RespChan:
			assuranceEmitHeartbeat(t, map[string]interface{}{
				"event":          "heartbeat_handler_response",
				"phase":          phase,
				"responded":      true,
				"response_error": fmt.Sprintf("%v", resp.Error),
				"elapsed_ms":     time.Since(start).Milliseconds(),
				"node_state":     r.State().String(),
			})
		case <-time.After(500 * time.Millisecond):
			assuranceEmitHeartbeat(t, map[string]interface{}{
				"event":      "heartbeat_handler_response",
				"phase":      phase,
				"responded":  false,
				"elapsed_ms": time.Since(start).Milliseconds(),
				"node_state": r.State().String(),
			})
		}
	}

	probe("running")
	_ = r.Shutdown().Error()
	probe("after_shutdown")
}
