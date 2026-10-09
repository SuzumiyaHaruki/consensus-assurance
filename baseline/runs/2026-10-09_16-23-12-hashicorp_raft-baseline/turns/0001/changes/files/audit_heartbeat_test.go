package raft_test

import (
	"io"
	"sync/atomic"
	"testing"
	"time"

	raft "github.com/hashicorp/raft"
)

// This thread-safe store delays one SetUint64 before its atomic write. Each
// successful write is otherwise exactly the supplied store's operation.
type auditDelayedTermStore struct {
	*raft.InmemStore
	armed   atomic.Bool
	entered chan struct{}
	release chan struct{}
}

func (s *auditDelayedTermStore) SetUint64(key []byte, value uint64) error {
	if string(key) == "CurrentTerm" && value == 2 && s.armed.Swap(false) {
		close(s.entered)
		<-s.release
	}
	return s.InmemStore.SetUint64(key, value)
}

// Requires the authorized private network namespace: see audit-results/commands.md.
func TestAuditConcurrentHeartbeatTermRegression(t *testing.T) {
	makeTransport := func() *raft.NetworkTransport {
		t.Helper()
		trans, err := raft.NewTCPTransport("127.0.0.1:0", nil, 3, 3*time.Second, io.Discard)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { trans.Close() })
		return trans
	}
	receiver, oldLeader, newLeader := makeTransport(), makeTransport(), makeTransport()
	store := &auditDelayedTermStore{InmemStore: raft.NewInmemStore(), entered: make(chan struct{}), release: make(chan struct{})}
	cfg := raft.DefaultConfig()
	cfg.LocalID = "F"
	cfg.HeartbeatTimeout = time.Hour
	cfg.ElectionTimeout = time.Hour
	cfg.LogOutput = io.Discard
	snaps := raft.NewInmemSnapshotStore()
	conf := raft.Configuration{Servers: []raft.Server{
		{ID: "F", Address: receiver.LocalAddr(), Suffrage: raft.Voter},
		{ID: "A", Address: oldLeader.LocalAddr(), Suffrage: raft.Voter},
		{ID: "B", Address: newLeader.LocalAddr(), Suffrage: raft.Voter},
	}}
	if err := raft.BootstrapCluster(cfg, store, store, snaps, receiver, conf); err != nil {
		t.Fatal(err)
	}
	node, err := raft.NewRaft(cfg, &raft.MockFSM{}, store, store, snaps, receiver)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { node.Shutdown().Error() }()
	send := func(trans *raft.NetworkTransport, id string, term uint64) (raft.AppendEntriesResponse, error) {
		req := &raft.AppendEntriesRequest{RPCHeader: raft.RPCHeader{ProtocolVersion: raft.ProtocolVersionMax, ID: []byte(id), Addr: []byte(trans.LocalAddr())}, Term: term}
		var response raft.AppendEntriesResponse
		err := trans.AppendEntries("F", receiver.LocalAddr(), req, &response)
		return response, err
	}
	store.armed.Store(true)
	type outcome struct {
		response raft.AppendEntriesResponse
		err      error
	}
	oldDone := make(chan outcome, 1)
	go func() { resp, err := send(oldLeader, "A", 2); oldDone <- outcome{resp, err} }()
	select {
	case <-store.entered:
	case <-time.After(time.Second):
		t.Fatal("term-2 heartbeat did not reach store")
	}
	// Always release the delayed operation, including on a failed assertion.
	released := false
	defer func() {
		if !released {
			close(store.release)
		}
	}()
	newer, err := send(newLeader, "B", 3)
	if err != nil || !newer.Success {
		t.Fatalf("term-3 heartbeat failed: %+v %v", newer, err)
	}
	before := node.CurrentTerm()
	if before != 3 {
		t.Fatalf("expected current term 3 before release, got %d", before)
	}
	close(store.release)
	released = true
	old := <-oldDone
	if old.err != nil {
		t.Fatal(old.err)
	}
	durable, _ := store.GetUint64([]byte("CurrentTerm"))
	after := node.CurrentTerm()
	_, leaderID := node.LeaderWithID()
	t.Logf("new heartbeat success=%v; current term before releasing old write=%d; old heartbeat success=%v; current term after=%d; durable term=%d; leader=%s", newer.Success, before, old.response.Success, after, durable, leaderID)
	// Control: the same descending terms are rejected when handled serially.
	if response, err := send(newLeader, "B", 3); err != nil || !response.Success {
		t.Fatalf("control newer heartbeat failed: %+v %v", response, err)
	}
	serialOld, err := send(oldLeader, "A", 2)
	if err != nil || serialOld.Success || node.CurrentTerm() != 3 {
		t.Fatalf("serial control unexpected: %+v %v term=%d", serialOld, err, node.CurrentTerm())
	}
	t.Logf("serial control: term-2 heartbeat success=%v current term=%d", serialOld.Success, node.CurrentTerm())
	if after < before || durable < before {
		t.Error("current term regressed after acknowledging a newer-term leader")
	}
}
