package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
)

type tnvFSM struct{}

func (f *tnvFSM) Apply(l *Log) interface{}       { return nil }
func (f *tnvFSM) Snapshot() (FSMSnapshot, error) { return &tnvSnapshot{}, nil }
func (f *tnvFSM) Restore(r io.ReadCloser) error  { r.Close(); return nil }

type tnvSnapshot struct{}

func (s *tnvSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (s *tnvSnapshot) Release()                        {}

func tnvEmit(t *testing.T, ev map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

// tnvNode builds a voter node with a bootstrapped configuration and a known
// leader, with all background goroutines disabled.
func tnvNode(t *testing.T, localID ServerID, voters []ServerID, leader ServerID) *Raft {
	t.Helper()
	conf := inmemConfig(t)
	conf.ProtocolVersion = ProtocolVersionMax
	conf.skipStartup = true
	conf.LocalID = localID
	_, trans := NewInmemTransport(ServerAddress(localID))
	logs, stable, snaps := NewInmemStore(), NewInmemStore(), NewInmemSnapshotStore()
	configuration := Configuration{}
	for _, v := range voters {
		configuration.Servers = append(configuration.Servers, Server{
			Suffrage: Voter, ID: v, Address: ServerAddress(v),
		})
	}
	if err := BootstrapCluster(conf, logs, stable, snaps, trans, configuration); err != nil {
		t.Fatalf("BootstrapCluster(%s): %v", localID, err)
	}
	r, err := NewRaft(conf, &tnvFSM{}, logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("NewRaft(%s): %v", localID, err)
	}
	r.setState(Follower)
	r.setLeader(ServerAddress(leader), leader)
	return r
}

func tnvAskVote(r *Raft, candidate ServerID, lastIdx, lastTerm uint64, transfer bool) (bool, string) {
	ch := make(chan RPCResponse, 1)
	encoded := r.trans.EncodePeer(candidate, ServerAddress(candidate))
	req := &RequestVoteRequest{
		RPCHeader:          RPCHeader{ProtocolVersion: ProtocolVersionMax, ID: []byte(candidate), Addr: encoded},
		Term:               r.getCurrentTerm(),
		Candidate:          encoded,
		LastLogIndex:       lastIdx,
		LastLogTerm:        lastTerm,
		LeadershipTransfer: transfer,
	}
	r.processRPC(RPC{Command: req, RespChan: ch})
	res := <-ch
	if res.Error != nil {
		return false, fmt.Sprintf("%v", res.Error)
	}
	resp, ok := res.Response.(*RequestVoteResponse)
	if !ok || resp == nil {
		return false, "unexpected response type"
	}
	return resp.Granted, ""
}

// TestAssuranceLeadershipTransferVotePrivilege observes the effect of
// RequestVoteRequest.LeadershipTransfer: a voter that already has a known
// leader grants the vote only when the flag is set.
func TestAssuranceLeadershipTransferVotePrivilege(t *testing.T) {
	const receiver = ServerID("node1")
	const leader = ServerID("node2")
	const voter = ServerID("node3")
	const outsider = ServerID("outsider")
	voters := []ServerID{receiver, leader, voter}

	// Case: configured voter, flag set, receiver already follows a leader.
	privileged := tnvNode(t, receiver, voters, leader)
	lastIdx, lastTerm := privileged.getLastEntry()
	tnvEmit(t, map[string]interface{}{
		"event":                         "privileged_vote_declared",
		"op_id":                         "vote-1",
		"transfer_privilege_set":        true,
		"candidate_is_configured_voter": true,
		"receiver_has_leader":           true,
		"candidate":                     string(voter),
		"known_leader":                  string(leader),
	})
	granted, errStr := tnvAskVote(privileged, voter, lastIdx, lastTerm, true)
	tnvEmit(t, map[string]interface{}{
		"event":                         "privileged_vote_result",
		"op_id":                         "vote-1",
		"transfer_privilege_set":        true,
		"candidate_is_configured_voter": true,
		"granted":                       granted,
		"error":                         errStr,
	})

	// Control: identical request without the flag.
	plain := tnvNode(t, receiver, voters, leader)
	pIdx, pTerm := plain.getLastEntry()
	pGranted, pErr := tnvAskVote(plain, voter, pIdx, pTerm, false)
	tnvEmit(t, map[string]interface{}{
		"event":                  "control_plain_vote_result",
		"op_id":                  "vote-2",
		"granted":                pGranted,
		"error":                  pErr,
		"transfer_privilege_set": false,
	})

	// Control: the flag does not defeat the membership check.
	unconfigured := tnvNode(t, receiver, voters, leader)
	uIdx, uTerm := unconfigured.getLastEntry()
	uGranted, uErr := tnvAskVote(unconfigured, outsider, uIdx, uTerm, true)
	tnvEmit(t, map[string]interface{}{
		"event":                         "control_unconfigured_candidate_result",
		"op_id":                         "vote-3",
		"granted":                       uGranted,
		"error":                         uErr,
		"transfer_privilege_set":        true,
		"candidate_is_configured_voter": false,
	})
}
