package raft

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"testing"
)

type sn2FSM struct{}

func (f *sn2FSM) Apply(l *Log) interface{}       { return nil }
func (f *sn2FSM) Snapshot() (FSMSnapshot, error) { return &sn2Snapshot{}, nil }
func (f *sn2FSM) Restore(r io.ReadCloser) error  { r.Close(); return nil }

type sn2Snapshot struct{}

func (s *sn2Snapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (s *sn2Snapshot) Release()                        {}

func sn2Emit(t *testing.T, ev map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceInstallSnapshotTailReplacedByAppendEntries bounds the retained
// snapshot tail: an AppendEntries whose entries conflict with it must replace
// the tail and update the node's last log.
func TestAssuranceInstallSnapshotTailReplacedByAppendEntries(t *testing.T) {
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
	otherConfig := Configuration{Servers: []Server{{Suffrage: Voter, ID: "other", Address: "other"}}}
	entries := []*Log{{Index: 1, Term: installedTerm, Type: LogConfiguration, Data: EncodeConfiguration(otherConfig)}}
	for idx := uint64(2); idx <= tailIndex; idx++ {
		entries = append(entries, &Log{Index: idx, Term: installedTerm, Type: LogCommand, Data: []byte("x")})
	}
	if err := logs.StoreLogs(entries); err != nil {
		t.Fatalf("seed log: %v", err)
	}
	r, err := NewRaft(conf, &sn2FSM{}, logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}

	done := make(chan struct{})
	defer close(done)
	go func() {
		for {
			select {
			case msg := <-r.fsmMutateCh:
				if rf, ok := msg.(*restoreFuture); ok {
					rf.respond(nil)
				}
				if batch, ok := msg.([]*commitTuple); ok {
					_ = batch
				}
			case <-done:
				return
			}
		}
	}()

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
	if res := <-ch; res.Error != nil {
		t.Fatalf("install snapshot: %v", res.Error)
	}
	idxAfterInstall, termAfterInstall := r.getLastEntry()
	rawAfterInstall, _ := logs.LastIndex()
	sn2Emit(t, map[string]interface{}{
		"event":              "tail_after_install",
		"op_id":              "tail-1",
		"installed_index":    installedIndex,
		"node_last_index":    idxAfterInstall,
		"node_last_term":     termAfterInstall,
		"log_raw_last_index": rawAfterInstall,
		"tail_retained":      idxAfterInstall > installedIndex,
	})

	// The leader now sends entries that conflict with the retained tail.
	newTerm := uint64(2)
	appendReq := &AppendEntriesRequest{
		RPCHeader:         RPCHeader{ProtocolVersion: ProtocolVersionMax, ID: []byte("other"), Addr: trans.EncodePeer("other", "other")},
		Term:              newTerm,
		Leader:            trans.EncodePeer("other", "other"),
		PrevLogEntry:      installedIndex,
		PrevLogTerm:       installedTerm,
		Entries:           []*Log{{Index: 4, Term: newTerm, Type: LogCommand, Data: []byte("y")}, {Index: tailIndex, Term: newTerm, Type: LogCommand, Data: []byte("z")}},
		LeaderCommitIndex: tailIndex,
	}
	ch2 := make(chan RPCResponse, 1)
	r.appendEntries(RPC{Command: appendReq, RespChan: ch2}, appendReq)
	res2 := <-ch2
	appendResp, _ := res2.Response.(*AppendEntriesResponse)
	idxFinal, termFinal := r.getLastEntry()
	rawFinal, _ := logs.LastIndex()
	sn2Emit(t, map[string]interface{}{
		"event":              "tail_after_append_entries",
		"op_id":              "tail-1",
		"append_success":     appendResp != nil && appendResp.Success,
		"node_last_index":    idxFinal,
		"node_last_term":     termFinal,
		"leader_last_term":   newTerm,
		"log_raw_last_index": rawFinal,
		"tail_replaced":      idxFinal == tailIndex && termFinal == newTerm,
		"committed_index":    r.getCommitIndex(),
	})
}
