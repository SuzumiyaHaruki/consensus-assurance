package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
)

type sdFSM struct{}

func (f *sdFSM) Apply(l *Log) interface{}       { return nil }
func (f *sdFSM) Snapshot() (FSMSnapshot, error) { return &sdSnapshot{}, nil }
func (f *sdFSM) Restore(r io.ReadCloser) error  { r.Close(); return nil }

type sdSnapshot struct{}

func (s *sdSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (s *sdSnapshot) Release()                        {}

func sdEmit(t *testing.T, ev map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceClientFutureShutdownEscape observes whether a client future that
// the library accepted can still complete after the node shuts down before any
// loop dequeues it.
func TestAssuranceClientFutureShutdownEscape(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = ProtocolVersionMax
	conf.skipStartup = true
	conf.LocalID = ServerID("node1")
	conf.BatchApplyCh = true
	conf.MaxAppendEntries = 4
	_, trans := NewInmemTransport(ServerAddress("node1"))
	r, err := NewRaft(conf, &sdFSM{}, NewInmemStore(), NewInmemStore(), NewInmemSnapshotStore(), trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}

	future := r.Apply([]byte("payload"), 0)
	lf, ok := future.(*logFuture)
	if !ok {
		t.Fatalf("unexpected future type %T", future)
	}
	sdEmit(t, map[string]interface{}{
		"event":            "shutdown_scenario_declared",
		"op_id":            "shutdown-1",
		"batch_apply_ch":   true,
		"request_accepted": true,
		"note":             "the request was accepted into the buffered apply channel and no loop is running",
	})

	r.Shutdown()

	responded := false
	select {
	case <-lf.errCh:
		responded = true
	default:
	}
	escape := lf.ShutdownCh != nil
	sdEmit(t, map[string]interface{}{
		"event":                    "apply_future_after_shutdown",
		"op_id":                    "shutdown-1",
		"request_accepted":         true,
		"responded_after_shutdown": responded,
		"shutdown_escape":          escape,
		"caller_can_complete":      responded || escape,
	})

	// Control: the same client call on a served node completes normally.
	cconf := inmemConfig(t)
	c := MakeCluster(1, t, cconf)
	defer c.Close()
	leader := c.Leader()
	served := leader.Apply([]byte("payload"), 0)
	servedErr := served.Error()
	sdEmit(t, map[string]interface{}{
		"event":     "control_apply_completes_when_served",
		"op_id":     "shutdown-2",
		"served":    true,
		"completed": servedErr == nil,
		"error":     fmt.Sprintf("%v", servedErr),
	})
}
