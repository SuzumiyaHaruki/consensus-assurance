package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

type assuranceVoteStore struct {
	*InmemStore
	failNext bool
	failed   bool
}

func (s *assuranceVoteStore) StoreLogs(logs []*Log) error {
	if s.failNext {
		s.failNext = false
		s.failed = true
		return fmt.Errorf("assurance: simulated StoreLogs failure")
	}
	return s.InmemStore.StoreLogs(logs)
}

type assuranceVoteFSM struct{}

func (assuranceVoteFSM) Apply(*Log) interface{}         { return nil }
func (assuranceVoteFSM) Snapshot() (FSMSnapshot, error) { return assuranceVoteSnapshot{}, nil }
func (assuranceVoteFSM) Restore(io.ReadCloser) error    { return nil }

type assuranceVoteSnapshot struct{}

func (assuranceVoteSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (assuranceVoteSnapshot) Release()                        {}

func assuranceEmit(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

// TestAssuranceTruncationFailureWithholdsVote extends the confirmed append
// scenario: after the truncation failure the cached last entry is ahead of the
// real log, so a candidate that is genuinely more up to date may be refused.
func TestAssuranceTruncationFailureWithholdsVote(t *testing.T) {
	node := "n1"
	store := &assuranceVoteStore{InmemStore: NewInmemStore()}
	seed := []*Log{
		{Index: 1, Term: 1, Type: LogNoop},
		{Index: 2, Term: 1, Type: LogNoop},
		{Index: 3, Term: 2, Type: LogNoop},
	}
	if err := store.InmemStore.StoreLogs(seed); err != nil {
		t.Fatalf("seed: %v", err)
	}
	conf := DefaultConfig()
	conf.LocalID = ServerID(node)
	conf.ProtocolVersion = 3
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 100 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.SnapshotThreshold = 100000
	conf.skipStartup = true

	_, trans := NewInmemTransport(NewInmemAddr())
	r, err := NewRaft(conf, assuranceVoteFSM{}, store, store, NewInmemSnapshotStore(), trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}
	r.setCurrentTerm(2)
	r.setState(Follower)
	r.setLeader("", "")
	leaderAddr := trans.EncodePeer(ServerID(node), trans.LocalAddr())

	// Truncate the conflicting suffix, then fail the store call.
	conflict := &AppendEntriesRequest{
		RPCHeader: RPCHeader{ProtocolVersion: 3, ID: []byte(node), Addr: leaderAddr},
		Term:      3, Leader: leaderAddr,
		PrevLogEntry: 1, PrevLogTerm: 1,
		Entries: []*Log{{Index: 2, Term: 3, Type: LogNoop}, {Index: 3, Term: 3, Type: LogNoop}},
	}
	store.failNext = true
	respCh := make(chan RPCResponse, 1)
	r.appendEntries(RPC{Command: conflict, RespChan: respCh}, conflict)
	<-respCh
	if !store.failed {
		t.Fatalf("simulated StoreLogs failure did not fire")
	}
	cachedIdx, cachedTerm := r.getLastLog()
	realIdx, realTerm := r.logs.LastIndex()
	realTermEntry := Log{}
	_ = r.logs.GetLog(realIdx, &realTermEntry)

	// A candidate whose log (index 2, term 2) is strictly more up to date than
	// the node's real log (index 1, term 1) must be granted a vote.
	vote := &RequestVoteRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: 3, ID: []byte("n2"), Addr: leaderAddr},
		Term:         3,
		Candidate:    leaderAddr,
		LastLogIndex: 2,
		LastLogTerm:  2,
	}
	voteCh := make(chan RPCResponse, 1)
	r.requestVote(RPC{Command: vote, RespChan: voteCh}, vote)
	out := <-voteCh
	voteResp, _ := out.Response.(*RequestVoteResponse)
	granted := voteResp != nil && voteResp.Granted

	assuranceEmit(map[string]interface{}{
		"event": "vote_precondition", "node": node,
		"cached_index": cachedIdx, "cached_term": cachedTerm,
		"real_index": realIdx, "real_term": realTermEntry.Term,
	})
	assuranceEmit(map[string]interface{}{
		"event": "vote_decision", "node": node,
		"granted": granted, "candidate_index": vote.LastLogIndex, "candidate_term": vote.LastLogTerm,
		"cached_index": cachedIdx, "real_index": realIdx, "real_term": realTerm,
	})
}
