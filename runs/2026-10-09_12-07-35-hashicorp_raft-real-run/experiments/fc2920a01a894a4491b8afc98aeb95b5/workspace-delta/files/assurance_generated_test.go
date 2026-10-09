package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
)

type hbvFSM struct{}

func (f *hbvFSM) Apply(l *Log) interface{}       { return nil }
func (f *hbvFSM) Snapshot() (FSMSnapshot, error) { return &hbvSnapshot{}, nil }
func (f *hbvFSM) Restore(r io.ReadCloser) error  { r.Close(); return nil }

type hbvSnapshot struct{}

func (s *hbvSnapshot) Persist(sink SnapshotSink) error { return sink.Close() }
func (s *hbvSnapshot) Release()                        {}

func hbvEmit(t *testing.T, ev map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func hbvNode(t *testing.T, localID ServerID, voters []ServerID) *Raft {
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
	r, err := NewRaft(conf, &hbvFSM{}, logs, stable, snaps, trans)
	if err != nil {
		t.Fatalf("NewRaft(%s): %v", localID, err)
	}
	r.setState(Follower)
	return r
}

// hbvGhostHeartbeat delivers a pure heartbeat with an out-of-window protocol
// version through the fast-path handler, as net_transport would after
// classifying it.
func hbvGhostHeartbeat(t *testing.T, r *Raft, ghost ServerID, term uint64) {
	t.Helper()
	encoded := r.trans.EncodePeer(ghost, ServerAddress(ghost))
	req := &AppendEntriesRequest{
		RPCHeader: RPCHeader{ProtocolVersion: ProtocolVersion(0), ID: []byte(ghost), Addr: encoded},
		Term:      term,
		Leader:    encoded,
	}
	ch := make(chan RPCResponse, 1)
	r.processHeartbeat(RPC{Command: req, RespChan: ch})
	<-ch
}

func hbvAskVote(r *Raft, candidate ServerID, lastIdx, lastTerm uint64) (bool, string) {
	ch := make(chan RPCResponse, 1)
	encoded := r.trans.EncodePeer(candidate, ServerAddress(candidate))
	req := &RequestVoteRequest{
		RPCHeader:    RPCHeader{ProtocolVersion: ProtocolVersionMax, ID: []byte(candidate), Addr: encoded},
		Term:         r.getCurrentTerm() + 1,
		Candidate:    encoded,
		LastLogIndex: lastIdx,
		LastLogTerm:  lastTerm,
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

// TestAssuranceGhostHeartbeatSuppressesVote observes whether an out-of-window
// heartbeat that reaches the fast path leaves the receiver unwilling to vote for
// a legitimate candidate.
func TestAssuranceGhostHeartbeatSuppressesVote(t *testing.T) {
	const receiver = ServerID("node1")
	const candidate = ServerID("node2")
	const ghost = ServerID("ghost")
	voters := []ServerID{receiver, candidate, "node3"}

	hbvEmit(t, map[string]interface{}{
		"event":                         "ghost_scenario_declared",
		"op_id":                         "hbv-1",
		"ghost_heartbeat_out_of_window": true,
		"candidate":                     string(candidate),
		"candidate_is_configured_voter": true,
	})

	tested := hbvNode(t, receiver, voters)
	lastIdx, lastTerm := tested.getLastEntry()
	hbvGhostHeartbeat(t, tested, ghost, tested.getCurrentTerm()+1)
	leaderAddr, leaderID := tested.LeaderWithID()
	granted, errStr := hbvAskVote(tested, candidate, lastIdx, lastTerm)
	hbvEmit(t, map[string]interface{}{
		"event":                   "vote_after_ghost_heartbeat",
		"op_id":                   "hbv-1",
		"ghost_leader_adopted":    leaderAddr != "",
		"known_leader_id":         string(leaderID),
		"legitimate_vote_granted": granted,
		"error":                   errStr,
		"candidate":               string(candidate),
	})

	// Control: the same vote request on a receiver that never saw the ghost.
	control := hbvNode(t, receiver, voters)
	cIdx, cTerm := control.getLastEntry()
	cGranted, cErr := hbvAskVote(control, candidate, cIdx, cTerm)
	cAddr, cID := control.LeaderWithID()
	hbvEmit(t, map[string]interface{}{
		"event":                   "control_vote_without_ghost",
		"op_id":                   "hbv-2",
		"ghost_leader_adopted":    false,
		"known_leader_id":         string(cID),
		"known_leader_addr":       string(cAddr),
		"legitimate_vote_granted": cGranted,
		"error":                   cErr,
		"candidate":               string(candidate),
	})
}
