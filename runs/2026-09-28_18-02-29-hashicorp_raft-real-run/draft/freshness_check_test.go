package raft

import (
	"encoding/json"
	"fmt"
	"reflect"
	"sync"
	"testing"
	"time"
)

type assuranceHeldReply struct {
	Term        uint64
	RequestTerm uint64
	Success     bool
	Error       string
}
type assuranceFreshTransport struct {
	*InmemTransport
	mu        sync.Mutex
	active    bool
	reserved  map[string]bool
	held      map[string]assuranceHeldReply
	release   chan struct{}
	later     chan struct{}
	once      sync.Once
	closeOnce sync.Once
}

func (g *assuranceFreshTransport) AppendEntriesPipeline(ServerID, ServerAddress) (AppendPipeline, error) {
	return nil, ErrPipelineReplicationNotSupported
}
func (g *assuranceFreshTransport) AppendEntries(id ServerID, addr ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
	kind := "append"
	if req.PrevLogEntry == 0 && req.PrevLogTerm == 0 && len(req.Entries) == 0 && req.LeaderCommitIndex == 0 {
		kind = "heartbeat"
	}
	key := string(id) + "/" + kind
	g.mu.Lock()
	capture := g.active && !g.reserved[key]
	park := g.active && g.reserved[key]
	if capture {
		g.reserved[key] = true
	}
	g.mu.Unlock()
	if park {
		<-g.later
		return fmt.Errorf("controlled link unavailable after captured reply")
	}
	err := g.InmemTransport.AppendEntries(id, addr, req, resp)
	if capture {
		msg := ""
		if err != nil {
			msg = err.Error()
		}
		g.mu.Lock()
		g.held[key] = assuranceHeldReply{resp.Term, req.Term, resp.Success, msg}
		g.mu.Unlock()
		<-g.release
	}
	return err
}
func (g *assuranceFreshTransport) releaseHeld() { g.once.Do(func() { close(g.release) }) }
func (g *assuranceFreshTransport) finish() {
	g.releaseHeld()
	g.closeOnce.Do(func() { close(g.later) })
}
func assuranceFreshEvent(e map[string]interface{}) {
	b, _ := json.Marshal(e)
	fmt.Println("CA_EVENT " + string(b))
}
func assuranceFreshWait(t *testing.T, d time.Duration, f func() bool, what string) {
	t.Helper()
	end := time.Now().Add(d)
	for time.Now().Before(end) {
		if f() {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("incomplete setup: %s", what)
}
func assuranceFreshContains(f *MockFSM, cmd string) bool {
	f.Lock()
	defer f.Unlock()
	for _, b := range f.logs {
		if string(b) == cmd {
			return true
		}
	}
	return false
}
func TestAssuranceVerifyAfterNewLeaderCommit(t *testing.T) {
	ids := []ServerID{"old", "b", "c"}
	confMembers := Configuration{}
	trs := make([]*InmemTransport, 3)
	fsms := make([]*MockFSM, 3)
	for i, id := range ids {
		addr, tr := NewInmemTransportWithTimeout(ServerAddress(id), 200*time.Millisecond)
		trs[i] = tr
		confMembers.Servers = append(confMembers.Servers, Server{ID: id, Address: addr, Suffrage: Voter})
	}
	for i := range ids {
		for j := range ids {
			if i != j {
				trs[i].Connect(ServerAddress(ids[j]), trs[j])
			}
		}
	}
	gate := &assuranceFreshTransport{InmemTransport: trs[0], reserved: make(map[string]bool), held: make(map[string]assuranceHeldReply), release: make(chan struct{}), later: make(chan struct{})}
	nodes := make([]*Raft, 0, 3)
	defer func() {
		gate.finish()
		var done []Future
		for _, r := range nodes {
			done = append(done, r.Shutdown())
		}
		for _, f := range done {
			_ = f.Error()
		}
		for _, tr := range trs {
			_ = tr.Close()
		}
	}()
	for i, id := range ids {
		cfg := DefaultConfig()
		cfg.LocalID = id
		cfg.HeartbeatTimeout = 5 * time.Second
		cfg.ElectionTimeout = 5 * time.Second
		cfg.LeaderLeaseTimeout = 50 * time.Millisecond
		cfg.CommitTimeout = 10 * time.Millisecond
		if i == 0 {
			cfg.HeartbeatTimeout = time.Second
			cfg.ElectionTimeout = time.Second
			cfg.LeaderLeaseTimeout = 900 * time.Millisecond
		}
		store := NewInmemStore()
		snap := NewInmemSnapshotStore()
		var tr Transport = trs[i]
		if i == 0 {
			tr = gate
		}
		if err := BootstrapCluster(cfg, store, store, snap, tr, confMembers); err != nil {
			t.Fatal(err)
		}
		fsms[i] = &MockFSM{}
		r, err := NewRaft(cfg, fsms[i], store, store, snap, tr)
		if err != nil {
			t.Fatal(err)
		}
		nodes = append(nodes, r)
	}
	old := nodes[0]
	assuranceFreshWait(t, 4*time.Second, func() bool { return old.State() == Leader }, "old election")
	prefix := old.Apply([]byte("prefix"), time.Second)
	pd := make(chan error, 1)
	go func() { pd <- prefix.Error() }()
	select {
	case err := <-pd:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("prefix incomplete")
	}
	cf := old.GetConfiguration()
	if err := cf.Error(); err != nil {
		t.Fatal(err)
	}
	var entry Log
	if err := old.logs.GetLog(1, &entry); err != nil {
		t.Fatal(err)
	}
	if entry.Type != LogConfiguration || !reflect.DeepEqual(DecodeConfiguration(entry.Data), confMembers) || !reflect.DeepEqual(cf.Configuration(), confMembers) || old.CommitIndex() < entry.Index {
		t.Fatal("prefix membership mismatch")
	}
	for _, f := range fsms {
		f := f
		assuranceFreshWait(t, time.Second, func() bool { return assuranceFreshContains(f, "prefix") }, "prefix FSM application")
	}
	oldTerm := old.CurrentTerm()
	gate.mu.Lock()
	gate.active = true
	gate.mu.Unlock()
	assuranceFreshWait(t, 350*time.Millisecond, func() bool { gate.mu.Lock(); defer gate.mu.Unlock(); return len(gate.held) == 4 }, "four real replies captured")
	gate.mu.Lock()
	held := make(map[string]assuranceHeldReply)
	for k, v := range gate.held {
		held[k] = v
	}
	gate.mu.Unlock()
	for k, v := range held {
		if !v.Success || v.Error != "" || v.Term != oldTerm || v.RequestTerm != oldTerm {
			t.Fatalf("unexpected held reply %s: %+v", k, v)
		}
	}
	// The only responses later released to old were produced before this split.
	for i := 1; i < 3; i++ {
		trs[0].Disconnect(ServerAddress(ids[i]))
		trs[i].Disconnect(ServerAddress(ids[0]))
	}
	for i := 1; i < 3; i++ {
		rc := nodes[i].ReloadableConfig()
		rc.HeartbeatTimeout = 80 * time.Millisecond
		rc.ElectionTimeout = 80 * time.Millisecond
		if err := nodes[i].ReloadConfig(rc); err != nil {
			t.Fatal(err)
		}
	}
	newIndex := -1
	assuranceFreshWait(t, 550*time.Millisecond, func() bool {
		for i := 1; i < 3; i++ {
			if nodes[i].State() == Leader && nodes[i].CurrentTerm() > oldTerm {
				newIndex = i
				return true
			}
		}
		return false
	}, "later real election")
	current := nodes[newIndex]
	newTerm := current.CurrentTerm()
	command := "new-leader-command"
	write := current.Apply([]byte(command), 200*time.Millisecond)
	wd := make(chan error, 1)
	go func() { wd <- write.Error() }()
	select {
	case err := <-wd:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(200 * time.Millisecond):
		t.Fatal("new write incomplete")
	}
	if current.CurrentTerm() != newTerm || current.State() != Leader || !assuranceFreshContains(fsms[newIndex], command) {
		t.Fatal("new command/leader identity changed")
	}
	// Each verification gets its own identity but shares this real transition.
	observe := func(op string, target *Raft, targetFSM *MockFSM, release bool) {
		superseded := target.localID != current.localID
		assuranceFreshEvent(map[string]interface{}{"event": "transition", "op": op, "old_id": string(ids[0]), "old_term": oldTerm, "new_id": string(current.localID), "new_term": newTerm, "new_write_index": write.Index(), "new_command_present": assuranceFreshContains(fsms[newIndex], command), "held_replies": held, "configuration_index": entry.Index})
		future := target.VerifyLeader()
		assuranceFreshEvent(map[string]interface{}{"event": "admitted", "op": op, "target_id": string(target.localID), "superseded": superseded, "new_term": newTerm})
		if release {
			gate.releaseHeld()
		}
		result := make(chan error, 1)
		go func() { result <- future.Error() }()
		select {
		case err := <-result:
			msg := ""
			if err != nil {
				msg = err.Error()
			}
			assuranceFreshEvent(map[string]interface{}{"event": "result", "op": op, "target_id": string(target.localID), "superseded": superseded, "success": err == nil, "error": msg, "target_term": target.CurrentTerm(), "target_state": target.State().String(), "command_present": assuranceFreshContains(targetFSM, command)})
		case <-time.After(250 * time.Millisecond):
			assuranceFreshEvent(map[string]interface{}{"event": "incomplete", "op": op, "reason": "bounded wait elapsed"})
		}
	}
	observe("old-after-new-commit", old, fsms[0], true)
	observe("current-leader-control", current, fsms[newIndex], false)
}
