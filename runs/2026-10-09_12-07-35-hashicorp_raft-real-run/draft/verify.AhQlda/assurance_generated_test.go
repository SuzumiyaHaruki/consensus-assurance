package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

// hbGateFSM is a minimal FSM; the observation does not involve FSM state.
type hbGateFSM struct{}

func (f *hbGateFSM) Apply(l *Log) interface{}       { return nil }
func (f *hbGateFSM) Snapshot() (FSMSnapshot, error) { return &hbGateSnapshot{}, nil }
func (f *hbGateFSM) Restore(r io.ReadCloser) error  { r.Close(); return nil }

type hbGateSnapshot struct{}

func (s *hbGateSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (s *hbGateSnapshot) Release()                        {}

func hbEmit(t *testing.T, ev map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// hbGateNode builds one Raft node with all background goroutines disabled, so a
// request handler can be driven directly without racing a running main loop.
func hbGateNode(t *testing.T, id ServerID) *Raft {
	t.Helper()
	conf := inmemConfig(t)
	conf.ProtocolVersion = ProtocolVersionMax
	conf.skipStartup = true
	conf.LocalID = id
	_, trans := NewInmemTransport(ServerAddress(id))
	r, err := NewRaft(conf, &hbGateFSM{}, NewInmemStore(), NewInmemStore(),
		NewInmemSnapshotStore(), trans)
	if err != nil {
		t.Fatalf("NewRaft(%s): %v", id, err)
	}
	return r
}

// hbGateHeartbeat builds the pure AppendEntries heartbeat shape that
// net_transport routes to the fast path: term and leader address set, no
// entries, and all previous-log and commit fields zero.
func hbGateHeartbeat(trans Transport, leaderID ServerID, proto ProtocolVersion, term uint64) *AppendEntriesRequest {
	encoded := trans.EncodePeer(leaderID, ServerAddress(leaderID))
	return &AppendEntriesRequest{
		RPCHeader: RPCHeader{ProtocolVersion: proto, ID: []byte(leaderID), Addr: encoded},
		Term:      term,
		Leader:    encoded,
	}
}

func hbGateSnapshotState(r *Raft) (uint64, RaftState, ServerAddress, ServerID, time.Time) {
	addr, id := r.LeaderWithID()
	return r.getCurrentTerm(), r.getState(), addr, id, r.LastContact()
}

// TestAssuranceHeartbeatFastPathProtocolGate compares the two AppendEntries
// entry paths for one out-of-window pure heartbeat: the normal RPC path applies
// checkRPCHeader and rejects it, while the heartbeat fast path reaches
// appendEntries without that check.
func TestAssuranceHeartbeatFastPathProtocolGate(t *testing.T) {
	const leaderID = ServerID("ghost-leader")
	const hbTerm = uint64(5)
	outOfWindow := ProtocolVersion(0) // below Node protocol 3 minus one

	fast := hbGateNode(t, "node-fast")
	normal := hbGateNode(t, "node-normal")
	control := hbGateNode(t, "node-control")

	hbEmit(t, map[string]interface{}{
		"event":                          "scenario_declared",
		"op_id":                          "hb-1",
		"out_of_window_protocol_version": true,
		"request_protocol_version":       int(outOfWindow),
		"node_protocol_version":          int(ProtocolVersionMax),
		"heartbeat_shape":                "term and leader address set; no entries; previous-log and commit fields zero",
	})

	// Normal RPC path: the same request shape, dispatched through processRPC.
	tBefore, sBefore, aBefore, idBefore, cBefore := hbGateSnapshotState(normal)
	normalCh := make(chan RPCResponse, 1)
	normal.processRPC(&RPC{Command: hbGateHeartbeat(normal.trans, leaderID, outOfWindow, hbTerm), RespChan: normalCh})
	normalResp := <-normalCh
	tAfter, sAfter, aAfter, idAfter, cAfter := hbGateSnapshotState(normal)
	normalChanged := tBefore != tAfter || sBefore != sAfter || aBefore != aAfter || idBefore != idAfter || cBefore != cAfter
	hbEmit(t, map[string]interface{}{
		"event":         "normal_path_heartbeat_result",
		"op_id":         "hb-1",
		"path":          "processRPC",
		"rejected":      normalResp.Error == ErrUnsupportedProtocol,
		"error":         fmt.Sprintf("%v", normalResp.Error),
		"state_changed": normalChanged,
	})

	// Heartbeat fast path: the callback body installed by SetHeartbeatHandler.
	fBefore, fsBefore, faBefore, fidBefore, fcBefore := hbGateSnapshotState(fast)
	fastCh := make(chan RPCResponse, 1)
	fast.processHeartbeat(&RPC{Command: hbGateHeartbeat(fast.trans, leaderID, outOfWindow, hbTerm), RespChan: fastCh})
	fastResp := <-fastCh
	fAfter, fsAfter, faAfter, fidAfter, fcAfter := hbGateSnapshotState(fast)
	guardApplied := fBefore == fAfter && fsBefore == fsAfter && faBefore == faAfter && fidBefore == fidAfter && !fcAfter.After(fcBefore)
	hbEmit(t, map[string]interface{}{
		"event":                          "fast_path_heartbeat_result",
		"op_id":                          "hb-1",
		"path":                           "processHeartbeat",
		"out_of_window_protocol_version": true,
		"error":                          fmt.Sprintf("%v", fastResp.Error),
		"term_before":                    fBefore,
		"term_after":                     fAfter,
		"state_before":                   fsBefore.String(),
		"state_after":                    fsAfter.String(),
		"leader_before":                  string(faBefore),
		"leader_after":                   string(faAfter),
		"leader_id_after":                string(fidAfter),
		"last_contact_refreshed":         fcAfter.After(fcBefore),
		"guard_applied":                  guardApplied,
	})

	// Diagnostic control: the same shape with an in-window protocol version is
	// accepted on the normal path, so the difference is attributable to the
	// header window and not to the request shape.
	cBeforeTerm, cBeforeState, cBeforeAddr, cBeforeID, cBeforeContact := hbGateSnapshotState(control)
	controlCh := make(chan RPCResponse, 1)
	control.processRPC(&RPC{Command: hbGateHeartbeat(control.trans, leaderID, ProtocolVersionMax, hbTerm), RespChan: controlCh})
	controlResp := <-controlCh
	cAfterTerm, cAfterState, cAfterAddr, cAfterID, cAfterContact := hbGateSnapshotState(control)
	hbEmit(t, map[string]interface{}{
		"event":                    "control_in_window_heartbeat_result",
		"op_id":                    "hb-control",
		"path":                     "processRPC",
		"rejected":                 controlResp.Error != nil,
		"state_changed":            cBeforeTerm != cAfterTerm || cBeforeState != cAfterState || cBeforeAddr != cAfterAddr || cBeforeID != cAfterID || cAfterContact.After(cBeforeContact),
		"term_before":              cBeforeTerm,
		"term_after":               cAfterTerm,
		"leader_after":             string(cAfterAddr),
		"request_protocol_version": int(ProtocolVersionMax),
	})
}
