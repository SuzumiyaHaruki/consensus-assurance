package raft

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"testing"
)

type snFSM struct{}

func (f *snFSM) Apply(l *Log) interface{}       { return nil }
func (f *snFSM) Snapshot() (FSMSnapshot, error) { return &snSnapshot{}, nil }
func (f *snFSM) Restore(r io.ReadCloser) error  { r.Close(); return nil }

type snSnapshot struct{}

func (s *snSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (s *snSnapshot) Release()                        {}

func snEmit(t *testing.T, ev map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceInstallSnapshotLogTailAlignment observes the node's bookkeeping
// after an InstallSnapshot installs a snapshot at an index below log entries the
// node already holds.
func TestAssuranceInstallSnapshotLogTailAlignment(t *testing.T) {
	const localID = ServerID("node1")
	const installedIndex = uint64(3)
	const installedTerm = uint64(1)
	const tailIndex = uint64(5)

	conf := inmemConfig(t)
	conf.ProtocolVersion = ProtocolVersionMax
	conf.skipStartup = true
	conf.LocalID = localID
	conf.TrailingLogs = 0

	logs, stable, snaps := NewInmemStore(), NewInmemStore(), NewInmemSnapshotStore()
	_, trans := NewInmemTransport(ServerAddress(localID))

	// A configuration whose only voter is another server, so this node is a
	// follower that never campaigns, followed by command entries 2..5.
	otherConfig := Configuration{Servers: []Server{{Suffrage: Voter, ID: "other", Address: "other"}}}
	entries := []*Log{{Index: 1, Term: installedTerm, Type: LogConfiguration, Data: EncodeConfiguration(otherConfig)}}
	for idx := uint64(2); idx <= tailIndex; idx++ {
		entries = append(entries, &Log{Index: idx, Term: installedTerm, Type: LogCommand, Data: []byte("x")})
	}
	if err := logs.StoreLogs(entries); err != nil {
		t.Fatalf("seed log: %v", err)
	}

	r, err := NewRaft(conf, &snFSM{}, logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}

	// Substitute FSM schedule: with skipStartup there is no runFSM goroutine, so
	// snapshot restores are answered here. The proposition under test is the
	// handler's own bookkeeping, for which a successful restore is a premise.
	done := make(chan struct{})
	defer close(done)
	go func() {
		for {
			select {
			case msg := <-r.fsmMutateCh:
				if rf, ok := msg.(*restoreFuture); ok {
					rf.respond(nil)
				}
			case <-done:
				return
			}
		}
	}()

	beforeIndex, beforeTerm := r.getLastEntry()
	rawBefore, _ := logs.LastIndex()
	snEmit(t, map[string]interface{}{
		"event":                               "snapshot_install_declared",
		"op_id":                               "snap-1",
		"installed_index":                     installedIndex,
		"installed_term":                      installedTerm,
		"node_last_index":                     beforeIndex,
		"node_last_term":                      beforeTerm,
		"log_raw_last_index":                  rawBefore,
		"holds_entries_above_installed_index": rawBefore > installedIndex,
	})

	payload := []byte("snapshot-bytes")
	req := &InstallSnapshotRequest{
		RPCHeader:          RPCHeader{ProtocolVersion: ProtocolVersionMax, ID: []byte("other"), Addr: trans.EncodePeer("other", "other")},
		SnapshotVersion:    1,
		Term:               installedTerm,
		Leader:             trans.EncodePeer("other", "other"),
		LastLogIndex:       installedIndex,
		LastLogTerm:        installedTerm,
		Configuration:      EncodeConfiguration(otherConfig),
		ConfigurationIndex: 1,
		Size:               int64(len(payload)),
	}
	ch := make(chan RPCResponse, 1)
	r.installSnapshot(RPC{Command: req, Reader: bytes.NewReader(payload), RespChan: ch}, req)
	resp := <-ch

	afterIndex, afterTerm := r.getLastEntry()
	rawAfter, _ := logs.LastIndex()
	remain := 0
	for idx := uint64(1); idx <= rawAfter; idx++ {
		var l Log
		if err := logs.GetLog(idx, &l); err == nil {
			remain++
		}
	}
	snEmit(t, map[string]interface{}{
		"event":                     "snapshot_install_result",
		"op_id":                     "snap-1",
		"installed_index":           installedIndex,
		"rejected":                  resp.Error != nil,
		"error":                     fmt.Sprintf("%v", resp.Error),
		"last_applied":              r.getLastApplied(),
		"snapshot_index":            func() uint64 { i, _ := r.getLastSnapshot(); return i }(),
		"node_last_index_after":     afterIndex,
		"node_last_term_after":      afterTerm,
		"log_raw_last_index_after":  rawAfter,
		"log_entries_remaining":     remain,
		"within_installed_snapshot": afterIndex <= installedIndex,
	})
}
