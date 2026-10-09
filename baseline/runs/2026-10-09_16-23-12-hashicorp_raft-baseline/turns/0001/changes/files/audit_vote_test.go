package raft_test

import (
	"errors"
	"io"
	"sync/atomic"
	"testing"
	"time"

	raft "github.com/hashicorp/raft"
)

// A failed candidate write leaves all preceding successful per-key writes intact.
// This is also the durable state at a crash between the two vote writes.
type auditVoteStore struct {
	*raft.InmemStore
	failCandidate atomic.Bool
}

func (s *auditVoteStore) Set(key, value []byte) error {
	if string(key) == "LastVoteCand" && s.failCandidate.Swap(false) {
		return errors.New("audit: candidate write interrupted before persistence")
	}
	return s.InmemStore.Set(key, value)
}

func TestAuditInterruptedVotePersistence(t *testing.T) {
	for _, interrupted := range []bool{true, false} {
		name := "complete_write_control"
		if interrupted {
			name = "interrupted_candidate_write"
		}
		t.Run(name, func(t *testing.T) {
			cfg := raft.DefaultConfig()
			cfg.LocalID = "F"
			cfg.HeartbeatTimeout = time.Hour
			cfg.ElectionTimeout = time.Hour
			cfg.LogOutput = io.Discard
			_, trans := raft.NewInmemTransport("F")
			_, sender := raft.NewInmemTransport("sender")
			sender.Connect("F", trans)
			store := &auditVoteStore{InmemStore: raft.NewInmemStore()}
			snaps := raft.NewInmemSnapshotStore()
			conf := raft.Configuration{Servers: []raft.Server{
				{ID: "F", Address: "F", Suffrage: raft.Voter},
				{ID: "A", Address: "A", Suffrage: raft.Voter},
				{ID: "B", Address: "B", Suffrage: raft.Voter},
				{ID: "C", Address: "C", Suffrage: raft.Voter},
				{ID: "D", Address: "D", Suffrage: raft.Voter},
			}}
			if err := raft.BootstrapCluster(cfg, store, store, snaps, trans, conf); err != nil {
				t.Fatal(err)
			}
			node, err := raft.NewRaft(cfg, &raft.MockFSM{}, store, store, snaps, trans)
			if err != nil {
				t.Fatal(err)
			}
			defer func() { node.Shutdown().Error() }()
			vote := func(candidate string, term, logIndex, logTerm uint64) bool {
				t.Helper()
				req := &raft.RequestVoteRequest{RPCHeader: raft.RPCHeader{ProtocolVersion: raft.ProtocolVersionMax, ID: []byte(candidate), Addr: []byte(candidate)}, Term: term, LastLogIndex: logIndex, LastLogTerm: logTerm}
				var resp raft.RequestVoteResponse
				if err := sender.RequestVote("F", "F", req, &resp); err != nil {
					t.Fatal(err)
				}
				return resp.Granted
			}
			if !vote("A", 2, 1, 1) {
				t.Fatal("initial vote for A not granted")
			}
			// B subsequently leads in term 3 without needing F's vote, and F
			// receives a committed term-3 command which A has not received.
			appendReq := &raft.AppendEntriesRequest{
				RPCHeader: raft.RPCHeader{ProtocolVersion: raft.ProtocolVersionMax, ID: []byte("B"), Addr: []byte("B")},
				Term:      3, PrevLogEntry: 1, PrevLogTerm: 1, LeaderCommitIndex: 2,
				Entries: []*raft.Log{{Index: 2, Term: 3, Type: raft.LogCommand, Data: []byte("committed by B")}},
			}
			var appendResp raft.AppendEntriesResponse
			if err := sender.AppendEntries("F", "F", appendReq, &appendResp); err != nil || !appendResp.Success {
				t.Fatalf("append failed: %+v %v", appendResp, err)
			}
			// A restart clears the volatile leader hint, as a real later
			// election timeout would. All log and vote state remains intact.
			if err := node.Shutdown().Error(); err != nil {
				t.Fatal(err)
			}
			node, err = raft.NewRaft(cfg, &raft.MockFSM{}, store, store, snaps, trans)
			if err != nil {
				t.Fatal(err)
			}
			store.failCandidate.Store(interrupted)
			grantedC := vote("C", 4, 2, 3)
			if grantedC == interrupted {
				t.Fatalf("unexpected C vote: granted=%v interrupted=%v", grantedC, interrupted)
			}
			durableTerm, _ := store.GetUint64([]byte("LastVoteTerm"))
			durableCandidate, _ := store.Get([]byte("LastVoteCand"))
			if err := node.Shutdown().Error(); err != nil {
				t.Fatal(err)
			}
			node, err = raft.NewRaft(cfg, &raft.MockFSM{}, store, store, snaps, trans)
			if err != nil {
				t.Fatal(err)
			}
			grantedA := vote("A", 4, 1, 1)
			t.Logf("vote C granted=%v; durable vote=(term %d, candidate %s); after restart stale A (last log 1/1, follower 2/3) granted=%v", grantedC, durableTerm, durableCandidate, grantedA)
			if grantedA {
				t.Error("granted vote to stale candidate due to torn vote record; log freshness check was bypassed")
			}
		})
	}
}
