package raft

import (
	"bytes"
	"encoding/json"
	"fmt"
	"testing"
)

type assuranceVoteStore struct {
	*InmemStore
	failCandidate bool
	failures      int
}

func (s *assuranceVoteStore) Set(key, value []byte) error {
	if s.failCandidate && bytes.Equal(key, keyLastVoteCand) {
		s.failCandidate = false
		s.failures++
		return fmt.Errorf("injected candidate-key write failure; previous value retained")
	}
	return s.InmemStore.Set(key, value)
}
func assuranceVoteEvent(t *testing.T, event string, m map[string]interface{}) {
	m["event"] = event
	b, err := json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}
func TestAssuranceExplorePartialVotePersistence(t *testing.T) {
	for _, inject := range []bool{false, true} {
		t.Run(fmt.Sprintf("candidate_write_failure_%v", inject), func(t *testing.T) {
			conf := DefaultConfig()
			conf.LocalID = "v"
			conf.skipStartup = true
			_, tr := NewInmemTransport("v")
			defer tr.Close()
			logs := NewInmemStore()
			stable := &assuranceVoteStore{InmemStore: NewInmemStore()}
			snaps := NewInmemSnapshotStore()
			config := Configuration{Servers: []Server{{Suffrage: Voter, ID: "v", Address: "v"}, {Suffrage: Voter, ID: "a", Address: "a"}, {Suffrage: Voter, ID: "b", Address: "b"}}}
			if err := BootstrapCluster(conf, logs, stable, snaps, tr, config); err != nil {
				t.Fatal(err)
			}
			r, err := NewRaft(conf, &MockFSM{}, logs, stable, snaps, tr)
			if err != nil {
				t.Fatal(err)
			}
			defer func() { r.Shutdown().Error() }()
			header := func(id string) RPCHeader {
				return RPCHeader{ProtocolVersion: conf.ProtocolVersion, ID: []byte(id), Addr: []byte(id)}
			}
			call := func(command interface{}) RPCResponse {
				ch := make(chan RPCResponse, 1)
				r.processRPC(RPC{Command: command, RespChan: ch})
				return <-ch
			}
			vote := func(id string, term, index, logterm uint64) *RequestVoteResponse {
				got := call(&RequestVoteRequest{RPCHeader: header(id), Term: term, LastLogIndex: index, LastLogTerm: logterm})
				if got.Error != nil {
					t.Fatal(got.Error)
				}
				return got.Response.(*RequestVoteResponse)
			}
			// Constructed receiver history, not an executed distributed election:
			// a requested a term-2 vote; a different term-3 leader b supplies a new
			// uncommitted log entry. Its election by other voters is not executed.
			first := vote("a", 2, 1, 1)
			if !first.Granted {
				t.Fatal("initial vote rejected")
			}
			appended := call(&AppendEntriesRequest{RPCHeader: header("b"), Term: 3, PrevLogEntry: 1, PrevLogTerm: 1, Entries: []*Log{{Index: 2, Term: 3, Type: LogNoop}}})
			if appended.Error != nil || !appended.Response.(*AppendEntriesResponse).Success {
				t.Fatal("append prerequisite failed")
			}
			lastIndex, lastTerm := r.getLastEntry()
			stable.failCandidate = inject
			fresh := vote("b", 4, lastIndex, lastTerm)
			storedTerm, _ := stable.GetUint64(keyLastVoteTerm)
			storedCandidate, _ := stable.Get(keyLastVoteCand)
			assuranceVoteEvent(t, "vote_prefix", map[string]interface{}{"case_id": fmt.Sprint(inject), "initial_vote_granted": first.Granted, "local_index": lastIndex, "local_log_term": lastTerm, "fresh_vote_granted": fresh.Granted, "injected_failures": stable.failures, "stored_vote_term": storedTerm, "stored_candidate": string(storedCandidate), "current_term": r.getCurrentTerm()})
			stale := vote("a", 4, 1, 1)
			assuranceVoteEvent(t, "stale_vote_reply", map[string]interface{}{"case_id": fmt.Sprint(inject), "candidate": "a", "request_term": 4, "candidate_last_index": 1, "candidate_last_term": 1, "local_index": lastIndex, "local_log_term": lastTerm, "granted": stale.Granted, "response_term": stale.Term, "injected_failures": stable.failures})
		})
	}
}
