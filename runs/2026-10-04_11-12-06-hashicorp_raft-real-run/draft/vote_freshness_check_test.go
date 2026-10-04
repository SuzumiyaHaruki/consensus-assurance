package raft

import (
	"bytes"
	"encoding/json"
	"fmt"
	"testing"
	"time"
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

// This transport executes real handlers synchronously at scheduled deliveries.
// Selected vote RPCs are dropped; no successful response is synthesized.
type assuranceVoteNetwork struct {
	nodes map[ServerID]*Raft
}
type assuranceVoteTransport struct {
	*InmemTransport
	from          ServerID
	network       *assuranceVoteNetwork
	targetReplies chan map[string]interface{}
}

func (tr *assuranceVoteTransport) RequestVote(id ServerID, addr ServerAddress, req *RequestVoteRequest, resp *RequestVoteResponse) error {
	if tr.from == "b" && ((req.Term == 4 && id == "v") || (req.Term == 5 && id == "a")) {
		return fmt.Errorf("scheduled vote RPC loss")
	}
	target := tr.network.nodes[id]
	index, term := target.getLastEntry()
	ch := make(chan RPCResponse, 1)
	target.processRPC(RPC{Command: req, RespChan: ch})
	got := <-ch
	if got.Error != nil {
		return got.Error
	}
	*resp = *got.Response.(*RequestVoteResponse)
	if tr.from == "a" && id == "v" && req.Term == 5 {
		tr.targetReplies <- map[string]interface{}{"candidate": string(req.ID), "request_term": req.Term, "candidate_last_index": req.LastLogIndex, "candidate_last_term": req.LastLogTerm, "local_index": index, "local_log_term": term, "granted": resp.Granted, "candidate_log_older": req.LastLogTerm < term, "response_term": resp.Term}
	}
	return nil
}
func (tr *assuranceVoteTransport) AppendEntries(id ServerID, addr ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
	ch := make(chan RPCResponse, 1)
	tr.network.nodes[id].processRPC(RPC{Command: req, RespChan: ch})
	got := <-ch
	if got.Error != nil {
		return got.Error
	}
	*resp = *got.Response.(*AppendEntriesResponse)
	return nil
}
func TestAssuranceVoteFreshnessAfterStoreError(t *testing.T) {
	for _, inject := range []bool{false, true} {
		t.Run(fmt.Sprint(inject), func(t *testing.T) {
			network := &assuranceVoteNetwork{nodes: make(map[ServerID]*Raft)}
			configs := make(map[ServerID]*Config)
			stores := make(map[ServerID]*assuranceVoteStore)
			snapshots := make(map[ServerID]*InmemSnapshotStore)
			transports := make(map[ServerID]*assuranceVoteTransport)
			configuration := Configuration{Servers: []Server{{Suffrage: Voter, ID: "v", Address: "v"}, {Suffrage: Voter, ID: "a", Address: "a"}, {Suffrage: Voter, ID: "b", Address: "b"}}}
			for _, server := range configuration.Servers {
				c := DefaultConfig()
				c.LocalID = server.ID
				c.skipStartup = true
				c.PreVoteDisabled = true
				c.HeartbeatTimeout = 5 * time.Millisecond
				c.ElectionTimeout = 5 * time.Millisecond
				c.LeaderLeaseTimeout = 5 * time.Millisecond
				configs[server.ID] = c
				stores[server.ID] = &assuranceVoteStore{InmemStore: NewInmemStore()}
				snapshots[server.ID] = NewInmemSnapshotStore()
				_, base := NewInmemTransport(server.Address)
				transports[server.ID] = &assuranceVoteTransport{InmemTransport: base, from: server.ID, network: network, targetReplies: make(chan map[string]interface{}, 1)}
			}
			if err := BootstrapCluster(configs["v"], stores["v"], stores["v"], snapshots["v"], transports["v"], configuration); err != nil {
				t.Fatal(err)
			}
			restart := func(id ServerID) {
				t.Helper()
				if old := network.nodes[id]; old != nil {
					if err := old.Shutdown().Error(); err != nil {
						t.Fatal(err)
					}
				}
				r, err := NewRaft(configs[id], &MockFSM{}, stores[id], stores[id], snapshots[id], transports[id])
				if err != nil {
					t.Fatal(err)
				}
				network.nodes[id] = r
			}
			for _, id := range []ServerID{"v", "a", "b"} {
				restart(id)
			}
			defer func() {
				for _, r := range network.nodes {
					r.Shutdown().Error()
				}
				for _, tr := range transports {
					tr.Close()
				}
			}()
			// Drain all actual campaign results before changing the scheduled network.
			// Only the majority state transition from runCandidate is performed here.
			campaign := func(id ServerID) int {
				t.Helper()
				r := network.nodes[id]
				r.runFollower()
				if r.getState() != Candidate {
					t.Fatal("candidate not reached")
				}
				results := r.electSelf()
				if results == nil {
					t.Fatal("self vote failed")
				}
				grants := 0
				for i := 0; i < len(configuration.Servers); i++ {
					select {
					case vote := <-results:
						if vote.Granted {
							grants++
						}
					case <-time.After(time.Second):
						t.Fatal("campaign result missing")
					}
				}
				if grants >= r.quorumSize() {
					r.setState(Leader)
					r.setLeader(r.localAddr, r.localID)
				}
				idx, term := r.getLastEntry()
				assuranceVoteEvent(t, "produced_campaign", map[string]interface{}{"case_id": fmt.Sprint(inject), "node": string(id), "term": r.getCurrentTerm(), "grants": grants, "last_index": idx, "last_log_term": term})
				return grants
			}
			prepareLeader := func(id ServerID) *logFuture {
				r := network.nodes[id]
				r.setupLeaderState()
				f := &logFuture{log: Log{Type: LogNoop}}
				f.init()
				r.dispatchLogs([]*logFuture{f})
				return f
			}
			replicate := func(from, to ServerID) {
				t.Helper()
				r := network.nodes[from]
				peer := Server{Suffrage: Voter, ID: to, Address: ServerAddress(to)}
				s := &followerReplication{peer: peer, currentTerm: r.getCurrentTerm(), nextIndex: 1, commitment: r.leaderState.commitment, stopCh: make(chan uint64), notify: make(map[*verifyFuture]struct{}), stepDown: make(chan struct{}, 1)}
				if r.replicateTo(s, r.getLastIndex()) {
					t.Fatal("replication stopped")
				}
			}
			commit := func(id ServerID, f *logFuture) {
				t.Helper()
				r := network.nodes[id]
				idx := r.leaderState.commitment.getCommitIndex()
				if idx != f.log.Index {
					t.Fatal("quorum commitment missing")
				}
				r.setCommitIndex(idx)
				r.setCommittedConfiguration(r.configurations.latest, r.configurations.latestIndex)
				r.processLogs(idx, map[uint64]*logFuture{f.log.Index: f})
			}
			if campaign("v") < 2 {
				t.Fatal("initial election failed")
			}
			f := prepareLeader("v")
			replicate("v", "a")
			replicate("v", "b")
			commit("v", f)
			replicate("v", "a")
			replicate("v", "b")
			// The first leader crashes; its successor a obtains an actual term-3 vote
			// from v, then crashes before dispatching its first leader no-op.
			restart("v")
			restart("b")
			if campaign("a") < 2 {
				t.Fatal("a election failed")
			}
			restart("a")
			// b wins term 4 using a plus self, while its request to v is lost. It
			// creates a term-4 no-op and replicates it to v, but not to a.
			if campaign("b") < 2 {
				t.Fatal("b election failed")
			}
			f = prepareLeader("b")
			replicate("b", "v")
			commit("b", f)
			replicate("b", "v")
			oldVoteTerm, _ := stores["v"].GetUint64(keyLastVoteTerm)
			oldCandidate, _ := stores["v"].Get(keyLastVoteCand)
			if oldVoteTerm != 3 || string(oldCandidate) != "a" {
				t.Fatalf("unexpected previous vote: %d %q", oldVoteTerm, oldCandidate)
			}
			restart("b")
			stores["v"].failCandidate = inject
			bGrants := campaign("b") // Request to a is lost, keeping a in term 4.
			storedTerm, _ := stores["v"].GetUint64(keyLastVoteTerm)
			storedCandidate, _ := stores["v"].Get(keyLastVoteCand)
			index, term := network.nodes["v"].getLastEntry()
			assuranceVoteEvent(t, "produced_failure_prefix", map[string]interface{}{"case_id": fmt.Sprint(inject), "prior_vote_term": oldVoteTerm, "prior_candidate": string(oldCandidate), "stored_vote_term": storedTerm, "stored_candidate": string(storedCandidate), "injected_failures": stores["v"].failures, "local_index": index, "local_log_term": term, "b_term5_grants": bGrants})
			aGrants := campaign("a")
			observed := <-transports["a"].targetReplies
			observed["case_id"] = fmt.Sprint(inject)
			observed["a_term5_grants"] = aGrants
			observed["injected_failures"] = stores["v"].failures
			assuranceVoteEvent(t, "produced_stale_vote", observed)
		})
	}
}
