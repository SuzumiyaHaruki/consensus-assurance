package raft_test

import (
	"bytes"
	"io"
	"testing"
	"time"

	raft "github.com/hashicorp/raft"
)

func TestAuditDelayedSnapshotRollback(t *testing.T) {
	cfg := raft.DefaultConfig()
	cfg.LocalID = "F"
	cfg.HeartbeatTimeout = time.Hour
	cfg.ElectionTimeout = time.Hour
	cfg.LogOutput = io.Discard
	_, receiver := raft.NewInmemTransport("F")
	_, sender := raft.NewInmemTransport("L")
	sender.Connect("F", receiver)
	conf := raft.Configuration{Servers: []raft.Server{
		{ID: "F", Address: "F", Suffrage: raft.Voter},
		{ID: "L", Address: "L", Suffrage: raft.Voter},
		{ID: "C", Address: "C", Suffrage: raft.Voter},
	}}
	logs := raft.NewInmemStore()
	// Use the disk snapshot store so publication semantics of the in-memory
	// snapshot store cannot explain the result.
	snaps, err := raft.NewFileSnapshotStore(t.TempDir(), 3, io.Discard)
	if err != nil {
		t.Fatal(err)
	}
	if err := raft.BootstrapCluster(cfg, logs, logs, snaps, receiver, conf); err != nil {
		t.Fatal(err)
	}
	fsm := &raft.MockFSM{}
	node, err := raft.NewRaft(cfg, fsm, logs, logs, snaps, receiver)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { node.Shutdown().Error() }()

	// Make a valid snapshot payload using the supplied FSM implementation.
	snapshotFSM := &raft.MockFSM{}
	snapshotFSM.Apply(&raft.Log{Index: 2, Term: 2, Type: raft.LogCommand, Data: []byte("before")})
	image, err := snapshotFSM.Snapshot()
	if err != nil {
		t.Fatal(err)
	}
	defer image.Release()
	imageStore := raft.NewInmemSnapshotStore()
	sink, err := imageStore.Create(1, 2, 2, conf, 1, sender)
	if err != nil {
		t.Fatal(err)
	}
	if err := image.Persist(sink); err != nil {
		t.Fatal(err)
	}
	_, reader, err := imageStore.Open(sink.ID())
	if err != nil {
		t.Fatal(err)
	}
	payload, err := io.ReadAll(reader)
	reader.Close()
	if err != nil {
		t.Fatal(err)
	}
	request := &raft.InstallSnapshotRequest{
		RPCHeader:       raft.RPCHeader{ProtocolVersion: raft.ProtocolVersionMax, ID: []byte("L"), Addr: []byte("L")},
		SnapshotVersion: 1, Term: 2, LastLogIndex: 2, LastLogTerm: 2,
		Configuration: raft.EncodeConfiguration(conf), ConfigurationIndex: 1, Size: int64(len(payload)),
	}
	install := func() {
		t.Helper()
		var response raft.InstallSnapshotResponse
		if err := sender.InstallSnapshot("F", "F", request, &response, bytes.NewReader(payload)); err != nil || !response.Success {
			t.Fatalf("install snapshot failed: %+v %v", response, err)
		}
	}
	appendRequest := func(entries []*raft.Log) {
		t.Helper()
		prev := uint64(3)
		if len(entries) != 0 {
			prev = entries[0].Index - 1
		}
		req := &raft.AppendEntriesRequest{
			RPCHeader: raft.RPCHeader{ProtocolVersion: raft.ProtocolVersionMax, ID: []byte("L"), Addr: []byte("L")},
			Term:      2, PrevLogEntry: prev, PrevLogTerm: 2, LeaderCommitIndex: 3, Entries: entries,
		}
		var response raft.AppendEntriesResponse
		if err := sender.AppendEntries("F", "F", req, &response); err != nil || !response.Success {
			t.Fatalf("append failed: %+v %v", response, err)
		}
	}
	install()
	appendRequest([]*raft.Log{{Index: 3, Term: 2, Type: raft.LogCommand, Data: []byte("after")}})
	auditWait(t, time.Second, "post-snapshot log application", func() bool { return len(fsm.Logs()) == 2 })
	t.Logf("before duplicate: commit=%d applied=%d FSM=%q", node.CommitIndex(), node.AppliedIndex(), fsm.Logs())
	// Delivery order of an earlier timed-out snapshot and its retry can be
	// reversed. Deliver the late identical snapshot after subsequent appends.
	install()
	// Ordinary same-leader commit notifications cannot repair the rollback:
	// commitIndex was not rolled back, so the handler skips processLogs.
	appendRequest(nil)
	t.Logf("after duplicate and commit notification: commit=%d applied=%d FSM=%q", node.CommitIndex(), node.AppliedIndex(), fsm.Logs())
	if len(fsm.Logs()) != 2 || node.AppliedIndex() != 3 {
		t.Error("delayed snapshot rolled back an already applied committed command; repeat commit notification did not replay it")
	}
}
