package raft_test

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"sync"
	"testing"
	"time"

	raft "github.com/hashicorp/raft"
)

type auditDelayedSnapshot struct {
	id      raft.ServerID
	target  raft.ServerAddress
	request raft.InstallSnapshotRequest
	data    []byte
}

type auditSnapshotTransport struct {
	*raft.InmemTransport
	mu          sync.Mutex
	delayTarget raft.ServerAddress
	delayed     chan auditDelayedSnapshot
}

func (s *auditSnapshotTransport) InstallSnapshot(id raft.ServerID, target raft.ServerAddress, req *raft.InstallSnapshotRequest, response *raft.InstallSnapshotResponse, reader io.Reader) error {
	s.mu.Lock()
	delay := target == s.delayTarget
	if delay {
		s.delayTarget = ""
	}
	s.mu.Unlock()
	if delay {
		data, err := io.ReadAll(reader)
		if err != nil {
			return err
		}
		s.delayed <- auditDelayedSnapshot{id, target, *req, data}
		return errors.New("audit: snapshot RPC timed out while its delivery remained pending")
	}
	return s.InmemTransport.InstallSnapshot(id, target, req, response, reader)
}

// An actual leader produces every snapshot and AppendEntries message. The
// wrapper models only one timeout and delayed delivery, with no altered fields.
func TestAuditClusterDelayedSnapshotRollback(t *testing.T) {
	const n = 3
	var nodes [n]*raft.Raft
	var fsms [n]*raft.MockFSM
	var trans [n]*auditSnapshotTransport
	configuration := raft.Configuration{}
	for i := 0; i < n; i++ {
		addr := raft.ServerAddress(fmt.Sprintf("snapshot-node-%d", i))
		_, base := raft.NewInmemTransport(addr)
		trans[i] = &auditSnapshotTransport{InmemTransport: base, delayed: make(chan auditDelayedSnapshot, 1)}
		configuration.Servers = append(configuration.Servers, raft.Server{ID: raft.ServerID(addr), Address: addr, Suffrage: raft.Voter})
	}
	// Node 2 starts disconnected; nodes 0 and 1 form the initial majority.
	trans[0].Connect(trans[1].LocalAddr(), trans[1].InmemTransport)
	trans[1].Connect(trans[0].LocalAddr(), trans[0].InmemTransport)
	defer func() {
		var futures []raft.Future
		for _, node := range nodes {
			if node != nil {
				futures = append(futures, node.Shutdown())
			}
		}
		for _, f := range futures {
			f.Error()
		}
	}()
	for i := 0; i < n; i++ {
		cfg := raft.DefaultConfig()
		cfg.LocalID = configuration.Servers[i].ID
		cfg.HeartbeatTimeout = 100 * time.Millisecond
		cfg.ElectionTimeout = 100 * time.Millisecond
		cfg.LeaderLeaseTimeout = 50 * time.Millisecond
		cfg.CommitTimeout = 5 * time.Millisecond
		cfg.TrailingLogs = 0
		cfg.LogOutput = io.Discard
		if i == 2 {
			cfg.HeartbeatTimeout = time.Hour
			cfg.ElectionTimeout = time.Hour
		}
		store := raft.NewInmemStore()
		snaps, err := raft.NewFileSnapshotStore(t.TempDir(), 3, io.Discard)
		if err != nil {
			t.Fatal(err)
		}
		if err := raft.BootstrapCluster(cfg, store, store, snaps, trans[i], configuration); err != nil {
			t.Fatal(err)
		}
		fsms[i] = &raft.MockFSM{}
		nodes[i], err = raft.NewRaft(cfg, fsms[i], store, store, snaps, trans[i])
		if err != nil {
			t.Fatal(err)
		}
	}
	leaderIndex := -1
	auditWait(t, 3*time.Second, "leader election", func() bool {
		for i := 0; i < 2; i++ {
			if nodes[i].State() == raft.Leader {
				leaderIndex = i
				return true
			}
		}
		return false
	})
	leader := nodes[leaderIndex]
	if err := leader.Apply([]byte("before snapshot"), time.Second).Error(); err != nil {
		t.Fatal(err)
	}
	if err := leader.Snapshot().Error(); err != nil {
		t.Fatal(err)
	}
	leaderTransport := trans[leaderIndex]
	leaderTransport.mu.Lock()
	leaderTransport.delayTarget = trans[2].LocalAddr()
	leaderTransport.mu.Unlock()
	for i := 0; i < 2; i++ {
		trans[i].Connect(trans[2].LocalAddr(), trans[2].InmemTransport)
		trans[2].Connect(trans[i].LocalAddr(), trans[i].InmemTransport)
	}
	var pending auditDelayedSnapshot
	select {
	case pending = <-leaderTransport.delayed:
	case <-time.After(2 * time.Second):
		t.Fatal("leader did not send a snapshot")
	}
	auditWait(t, 3*time.Second, "snapshot retry installed", func() bool { return len(fsms[2].Logs()) == 1 })
	if err := leader.Apply([]byte("after snapshot"), time.Second).Error(); err != nil {
		t.Fatal(err)
	}
	auditWait(t, time.Second, "follower applies new committed command", func() bool { return len(fsms[2].Logs()) == 2 })
	expectedIndex := nodes[2].AppliedIndex()
	t.Logf("before late delivery: snapshot=%d applied=%d commit=%d FSM=%q", pending.request.LastLogIndex, expectedIndex, nodes[2].CommitIndex(), fsms[2].Logs())
	var response raft.InstallSnapshotResponse
	if err := leaderTransport.InmemTransport.InstallSnapshot(pending.id, pending.target, &pending.request, &response, bytes.NewReader(pending.data)); err != nil || !response.Success {
		t.Fatalf("late delivery failed: %+v %v", response, err)
	}
	// Let several real commit-notification intervals elapse with no new writes.
	time.Sleep(100 * time.Millisecond)
	t.Logf("after late delivery: applied=%d commit=%d FSM=%q leader FSM=%q", nodes[2].AppliedIndex(), nodes[2].CommitIndex(), fsms[2].Logs(), fsms[leaderIndex].Logs())
	if len(fsms[2].Logs()) != 2 || nodes[2].AppliedIndex() != expectedIndex {
		t.Error("real leader's delayed snapshot undid an applied committed command and normal replication did not repair it")
	}
}
