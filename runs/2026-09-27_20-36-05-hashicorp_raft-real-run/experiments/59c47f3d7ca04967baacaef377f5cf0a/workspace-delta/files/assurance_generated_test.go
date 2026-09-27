package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"testing"
	"time"
)

func assuranceEmitVerify(v map[string]interface{}) {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

type assuranceVerifyFSM struct{}

func (*assuranceVerifyFSM) Apply(l *Log) interface{}       { return string(l.Data) }
func (*assuranceVerifyFSM) Snapshot() (FSMSnapshot, error) { return assuranceVerifySnapshot{}, nil }
func (*assuranceVerifyFSM) Restore(r io.ReadCloser) error {
	defer r.Close()
	_, err := io.Copy(io.Discard, r)
	return err
}

type assuranceVerifySnapshot struct{}

func (assuranceVerifySnapshot) Persist(s SnapshotSink) error { return s.Close() }
func (assuranceVerifySnapshot) Release()                     {}

type assuranceVerifySchedule struct {
	mu       sync.Mutex
	op       string
	active   bool
	leader   ServerID
	term     uint64
	parked   map[string]bool
	release  map[ServerID]chan struct{}
	released map[ServerID]bool
	roles    map[ServerID]ServerSuffrage
	positive map[ServerID]bool
	seq      uint64
}

type assuranceVerifyTransport struct {
	*InmemTransport
	schedule *assuranceVerifySchedule
	id       ServerID
}

// Unsupported pipelining is a documented Transport variant. Ordinary replication
// and its independent heartbeat worker still use the actual implementation.
func (*assuranceVerifyTransport) AppendEntriesPipeline(ServerID, ServerAddress) (AppendPipeline, error) {
	return nil, ErrPipelineReplicationNotSupported
}
func (tr *assuranceVerifyTransport) AppendEntries(id ServerID, addr ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
	s := tr.schedule
	class := "data"
	if req.PrevLogEntry == 0 && req.PrevLogTerm == 0 && len(req.Entries) == 0 && req.LeaderCommitIndex == 0 {
		class = "heartbeat"
	}
	s.mu.Lock()
	active := s.active && tr.id == s.leader
	var release chan struct{}
	var sequence uint64
	if active {
		s.seq++
		sequence = s.seq
		key := string(id) + "/" + class
		s.parked[key] = true
		release = s.release[id]
		assuranceEmitVerify(map[string]interface{}{"event": "worker_parked", "op": s.op, "peer": string(id), "worker": class, "term": req.Term, "rpc": sequence})
	}
	s.mu.Unlock()
	if release != nil {
		<-release
	}
	err := tr.InmemTransport.AppendEntries(id, addr, req, resp)
	if active {
		s.mu.Lock()
		if err == nil && resp.Success && resp.Term <= req.Term {
			s.positive[id] = true
		}
		errText := ""
		if err != nil {
			errText = err.Error()
		}
		assuranceEmitVerify(map[string]interface{}{"event": "actual_reply", "op": s.op, "peer": string(id), "worker": class, "rpc": sequence, "request_term": req.Term, "response_term": resp.Term, "success": resp.Success, "error": errText, "suffrage": int(s.roles[id])})
		s.mu.Unlock()
	}
	return err
}
func (s *assuranceVerifySchedule) releasePeer(id ServerID) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if ch, ok := s.release[id]; ok && !s.released[id] {
		close(ch)
		s.released[id] = true
	}
}
func (s *assuranceVerifySchedule) releaseAll() {
	s.mu.Lock()
	defer s.mu.Unlock()
	for id, ch := range s.release {
		if !s.released[id] {
			close(ch)
			s.released[id] = true
		}
	}
}
func assuranceWaitVerify(t *testing.T, limit time.Duration, condition func() bool) {
	t.Helper()
	end := time.Now().Add(limit)
	for time.Now().Before(end) {
		if condition() {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("prerequisite observation timed out")
}
func assuranceFutureVerify(t *testing.T, f Future) error {
	t.Helper()
	done := make(chan error, 1)
	go func() { done <- f.Error() }()
	select {
	case err := <-done:
		return err
	case <-time.After(8 * time.Second):
		t.Fatal("future observation timed out")
		return nil
	}
}
func TestAssuranceVerifyEligibleSupport(t *testing.T) {
	for _, onlyNonvoter := range []bool{false, true} {
		name := "voter_control"
		if onlyNonvoter {
			name = "nonvoter_only"
		}
		t.Run(name, func(t *testing.T) { assuranceRunVerifySupport(t, name, onlyNonvoter) })
	}
}
func assuranceRunVerifySupport(t *testing.T, op string, onlyNonvoter bool) {
	ids := []ServerID{"v0", "v1", "v2", "n0"}
	s := &assuranceVerifySchedule{op: op, parked: map[string]bool{}, release: map[ServerID]chan struct{}{}, released: map[ServerID]bool{}, roles: map[ServerID]ServerSuffrage{}, positive: map[ServerID]bool{}}
	conf := Configuration{}
	trs := make([]*assuranceVerifyTransport, 4)
	nodes := make([]*Raft, 0, 4)
	for i, id := range ids {
		role := Voter
		if i == 3 {
			role = Nonvoter
		}
		s.roles[id] = role
		_, base := NewInmemTransportWithTimeout(ServerAddress(id), time.Second)
		trs[i] = &assuranceVerifyTransport{InmemTransport: base, schedule: s, id: id}
		conf.Servers = append(conf.Servers, Server{ID: id, Address: ServerAddress(id), Suffrage: role})
	}
	t.Cleanup(func() {
		s.releaseAll()
		futures := []Future{}
		for _, node := range nodes {
			futures = append(futures, node.Shutdown())
		}
		for _, tr := range trs {
			tr.Close()
		}
		for _, f := range futures {
			assuranceFutureVerify(t, f)
		}
	})
	for i, tr := range trs {
		for j, other := range trs {
			if i != j {
				tr.Connect(other.LocalAddr(), other.InmemTransport)
			}
		}
	}
	for i, id := range ids {
		cfg := DefaultConfig()
		cfg.LocalID = id
		cfg.HeartbeatTimeout = 2 * time.Second
		cfg.ElectionTimeout = 2 * time.Second
		cfg.LeaderLeaseTimeout = 2 * time.Second
		cfg.CommitTimeout = 25 * time.Millisecond
		cfg.LogOutput = io.Discard
		store := NewInmemStore()
		snaps := NewInmemSnapshotStore()
		if err := BootstrapCluster(cfg, store, store, snaps, trs[i], conf); err != nil {
			t.Fatal(err)
		}
		node, err := NewRaft(cfg, &assuranceVerifyFSM{}, store, store, snaps, trs[i])
		if err != nil {
			t.Fatal(err)
		}
		nodes = append(nodes, node)
	}
	leaderIndex := -1
	assuranceWaitVerify(t, 12*time.Second, func() bool {
		found := -1
		for i, node := range nodes {
			if node.State() == Leader {
				if found >= 0 {
					return false
				}
				found = i
			}
		}
		leaderIndex = found
		return found >= 0
	})
	leader := nodes[leaderIndex]
	leaderID := ids[leaderIndex]
	applied := leader.Apply([]byte("prefix-"+op), time.Second)
	if err := assuranceFutureVerify(t, applied); err != nil {
		t.Fatal(err)
	}
	if applied.Response() != string("prefix-"+op) {
		t.Fatal("prefix FSM response mismatch")
	}
	cfgFuture := leader.GetConfiguration()
	if err := cfgFuture.Error(); err != nil {
		t.Fatal(err)
	}
	actual := cfgFuture.Configuration()
	voters := 0
	nonvoters := 0
	if len(actual.Servers) != 4 {
		t.Fatal("unexpected membership")
	}
	for _, member := range actual.Servers {
		role, ok := s.roles[member.ID]
		if !ok || role != member.Suffrage {
			t.Fatal("membership identity/role mismatch")
		}
		if role == Voter {
			voters++
		} else {
			nonvoters++
		}
	}
	if voters != 3 || nonvoters != 1 || s.roles[leaderID] != Voter {
		t.Fatal("invalid prefix roles")
	}
	term := leader.CurrentTerm()
	assuranceEmitVerify(map[string]interface{}{"event": "prefix", "op": op, "leader": string(leaderID), "term": term, "applied_index": applied.Index(), "commit_index": leader.CommitIndex(), "voters": voters, "nonvoters": nonvoters})
	s.mu.Lock()
	s.leader = leaderID
	s.term = term
	for _, id := range ids {
		if id != leaderID {
			s.release[id] = make(chan struct{})
		}
	}
	s.active = true
	s.mu.Unlock()
	// Each peer has exactly one ordinary replication worker and one heartbeat
	// worker. Their next synchronous call establishes consumption of old replies.
	assuranceWaitVerify(t, time.Second, func() bool { s.mu.Lock(); defer s.mu.Unlock(); return len(s.parked) == 6 })
	if leader.State() != Leader || leader.CurrentTerm() != term {
		t.Fatal("authority changed before admission")
	}
	assuranceEmitVerify(map[string]interface{}{"event": "quiescent", "op": op, "parked_workers": 6, "leader": string(leaderID), "term": term})
	f := leader.VerifyLeader()
	assuranceEmitVerify(map[string]interface{}{"event": "admitted", "op": op, "leader": string(leaderID), "term": term, "only_nonvoter": onlyNonvoter, "quorum": voters/2 + 1})
	if onlyNonvoter {
		s.releasePeer("n0")
	} else {
		s.releaseAll()
	}
	done := make(chan error, 1)
	go func() { done <- f.Error() }()
	select {
	case err := <-done:
		s.mu.Lock()
		eligible := 1
		positiveNonvoters := 0
		positivePeers := []string{}
		for id := range s.positive {
			positivePeers = append(positivePeers, string(id))
			if s.roles[id] == Voter {
				eligible++
			} else {
				positiveNonvoters++
			}
		}
		votersReleased := 0
		for id, released := range s.released {
			if released && s.roles[id] == Voter {
				votersReleased++
			}
		}
		s.mu.Unlock()
		errText := ""
		if err != nil {
			errText = err.Error()
		}
		assuranceEmitVerify(map[string]interface{}{"event": "completed", "op": op, "success": err == nil, "error": errText, "eligible_support_possible": eligible >= voters/2+1, "eligible_count_upper_bound": eligible, "positive_nonvoters": positiveNonvoters, "positive_peers": positivePeers, "released_remote_voters": votersReleased, "final_term": leader.CurrentTerm(), "final_state": leader.State().String()})
	case <-time.After(5 * time.Second):
		assuranceEmitVerify(map[string]interface{}{"event": "incomplete", "op": op, "reason": "no public result within observation bound"})
	}
	// Release held calls regardless of success, failure or observation timeout.
	s.releaseAll()
}
