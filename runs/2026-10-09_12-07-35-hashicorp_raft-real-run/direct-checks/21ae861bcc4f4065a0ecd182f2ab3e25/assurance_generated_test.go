package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
)

type vfFSM struct{}

func (f *vfFSM) Apply(l *Log) interface{}       { return nil }
func (f *vfFSM) Snapshot() (FSMSnapshot, error) { return &vfSnapshot{}, nil }
func (f *vfFSM) Restore(r io.ReadCloser) error  { r.Close(); return nil }

type vfSnapshot struct{}

func (s *vfSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (s *vfSnapshot) Release()                        {}

func vfEmit(t *testing.T, ev map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceVerifyFutureShutdownEscape checks whether the same completion gap
// affects VerifyLeader, whose request channel is buffered.
func TestAssuranceVerifyFutureShutdownEscape(t *testing.T) {
	conf := inmemConfig(t)
	conf.ProtocolVersion = ProtocolVersionMax
	conf.skipStartup = true
	conf.LocalID = ServerID("node1")
	_, trans := NewInmemTransport(ServerAddress("node1"))
	r, err := NewRaft(conf, &vfFSM{}, NewInmemStore(), NewInmemStore(), NewInmemSnapshotStore(), trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}

	future := r.VerifyLeader()
	vf, ok := future.(*verifyFuture)
	if !ok {
		t.Fatalf("unexpected future type %T", future)
	}
	vfEmit(t, map[string]interface{}{
		"event":            "verify_scenario_declared",
		"op_id":            "verify-1",
		"request_accepted": true,
		"note":             "the verify request was accepted into its buffered channel and no loop is running",
	})

	r.Shutdown()

	responded := false
	select {
	case <-vf.errCh:
		responded = true
	default:
	}
	escape := vf.ShutdownCh != nil
	vfEmit(t, map[string]interface{}{
		"event":                    "verify_future_after_shutdown",
		"op_id":                    "verify-1",
		"request_accepted":         true,
		"responded_after_shutdown": responded,
		"shutdown_escape":          escape,
		"caller_can_complete":      responded || escape,
	})

	// Control: the same call on a served node completes.
	cconf := inmemConfig(t)
	c := MakeCluster(1, t, cconf)
	defer c.Close()
	leader := c.Leader()
	servedErr := leader.VerifyLeader().Error()
	vfEmit(t, map[string]interface{}{
		"event":     "control_verify_completes_when_served",
		"op_id":     "verify-2",
		"served":    true,
		"completed": servedErr == nil,
		"error":     fmt.Sprintf("%v", servedErr),
	})
}
