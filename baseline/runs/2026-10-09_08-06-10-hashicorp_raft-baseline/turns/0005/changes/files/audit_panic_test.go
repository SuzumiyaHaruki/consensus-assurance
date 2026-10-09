package raft

// Diagnostic-only reproduction (NOT part of the captured implementation) for a
// network-reachable panic in InstallSnapshot handling.
//
// `installSnapshot` decodes the snapshot's `Configuration` field with
// `DecodeConfiguration`, which panics on malformed msgpack. Unlike the
// deprecated `Peers` path (which uses `decodePeers` and returns an error), the
// `Configuration` path performs no validation and no `recover`, so a peer that
// sends an InstallSnapshot with SnapshotVersion>0 and a non-msgpack
// `Configuration` crashes the receiving node's RPC loop.

import (
	"bytes"
	"os"
	"testing"
	"time"

	"github.com/hashicorp/go-hclog"
)

func TestAudit_InstallSnapshot_MalformedConfigurationPanics(t *testing.T) {
	_, transport := NewInmemTransport("")
	r := &Raft{trans: transport, logger: hclog.New(nil)}

	req := &InstallSnapshotRequest{
		SnapshotVersion: 1,                    // >0 selects the Configuration path
		Configuration:   []byte("not msgpack"),
	}
	chResp := make(chan RPCResponse, 1)
	rpc := RPC{Reader: new(bytes.Buffer), RespChan: chResp}

	defer func() {
		if rec := recover(); rec != nil {
			t.Logf("REPRODUCED panic from installSnapshot: %v", rec)
			return
		}
		t.Fatalf("expected a panic from malformed Configuration, got none")
	}()

	r.installSnapshot(rpc, req)
}

// Control: the deprecated Peers path is handled gracefully (returns an error,
// no panic). Mirrors the upstream test TestRaft_InstallSnapshot_InvalidPeers to
// show the asymmetry is specific to the Configuration path.
func TestAudit_InstallSnapshot_MalformedPeersNoPanic(t *testing.T) {
	_, transport := NewInmemTransport("")
	r := &Raft{trans: transport, logger: hclog.New(nil)}

	req := &InstallSnapshotRequest{Peers: []byte("not msgpack")}
	chResp := make(chan RPCResponse, 1)
	rpc := RPC{Reader: new(bytes.Buffer), RespChan: chResp}

	r.installSnapshot(rpc, req)
	resp := <-chResp
	if resp.Error == nil {
		t.Fatalf("expected an error from the Peers path, got nil")
	}
	t.Logf("Peers path returned error as expected: %v", resp.Error)
}

// End-to-end demonstration: deliver the malformed InstallSnapshot through the
// transport/RPC loop of a live node. There is no recover() in the RPC main
// loop, so this aborts the whole process (the "node crashes" case). Guarded by
// an env var so it does not break ordinary `go test` runs.
//
//	RAFT_AUDIT_CRASH=1 go test -run TestAudit_InstallSnapshot_NetworkCrash -v .
func TestAudit_InstallSnapshot_NetworkCrash(t *testing.T) {
	if os.Getenv("RAFT_AUDIT_CRASH") != "1" {
		t.Skip("set RAFT_AUDIT_CRASH=1 to run the crashing end-to-end repro")
	}

	c := MakeCluster(1, t, inmemConfig(t))
	defer c.Close()
	node := c.rafts[0]

	extAddr, ext := NewInmemTransport("attacker")
	_ = extAddr
	nodeTrans := node.trans.(*InmemTransport)
	nodeTrans.Connect("attacker", ext) // so responses could route back
	ext.Connect(node.localAddr, nodeTrans)

	req := &InstallSnapshotRequest{
		RPCHeader:       RPCHeader{ProtocolVersion: ProtocolVersionMax},
		SnapshotVersion: 1,
		Term:            node.getCurrentTerm() + 1000, // avoid the stale-term early return
		Configuration:   []byte("not msgpack"),
	}
	resp := &InstallSnapshotResponse{}
	t.Logf("sending malformed InstallSnapshot to %v", node.localAddr)
	_ = ext.InstallSnapshot("attacker", node.localAddr, req, resp, bytes.NewReader(nil))
	time.Sleep(500 * time.Millisecond)
	t.Fatalf("node did not crash (no panic observed)")
}

// Second, independent instance of the same class: an AppendEntries request
// carrying a log entry with an unrecognized LogType is stored, then committed
// via the leader's commit index; processLogs -> prepareLog hits the `default`
// branch and panics ("unrecognized log type"). No recover in the RPC loop, so
// the node process aborts.
func TestAudit_AppendEntries_UnknownLogTypePanics(t *testing.T) {
	_, transport := NewInmemTransport("")
	store := NewInmemStore()
	cfg := DefaultConfig()
	cfg.LocalID = "victim"
	cfg.ProtocolVersion = ProtocolVersionMax
	node, err := NewRaft(cfg, &MockFSM{}, store, store, NewInmemSnapshotStore(), transport)
	if err != nil {
		t.Fatal(err)
	}
	defer node.Shutdown()

	req := &AppendEntriesRequest{
		RPCHeader:         RPCHeader{ProtocolVersion: ProtocolVersionMax},
		Term:              node.getCurrentTerm() + 1000,
		Entries:           []*Log{{Index: 1, Term: 1, Type: LogType(99), Data: []byte("boom")}},
		LeaderCommitIndex: 1,
	}
	chResp := make(chan RPCResponse, 1)
	rpc := RPC{Reader: new(bytes.Buffer), RespChan: chResp}

	defer func() {
		if rec := recover(); rec != nil {
			t.Logf("REPRODUCED panic from appendEntries/processLogs: %v", rec)
			return
		}
		t.Fatalf("expected panic from unknown log type, got none")
	}()

	node.appendEntries(rpc, req)
}
