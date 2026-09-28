package raft

import (
	"encoding/json"
	"fmt"
	"reflect"
	"sync"
	"testing"
	"time"
)

type authorityTransport struct {
	*InmemTransport
	mu        sync.Mutex
	successes map[ServerID]int
}

func (a *authorityTransport) AppendEntriesPipeline(id ServerID, target ServerAddress) (AppendPipeline, error) {
	return nil, ErrPipelineReplicationNotSupported
}
func (a *authorityTransport) AppendEntries(id ServerID, target ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
	err := a.InmemTransport.AppendEntries(id, target, req, resp)
	if err == nil && resp.Success {
		a.mu.Lock()
		a.successes[id]++
		a.mu.Unlock()
	}
	return err
}
func (a *authorityTransport) counts() map[ServerID]int {
	a.mu.Lock()
	defer a.mu.Unlock()
	out := map[ServerID]int{}
	for k, v := range a.successes {
		out[k] = v
	}
	return out
}
func authorityEvent(v map[string]interface{}) {
	b, _ := json.Marshal(v)
	fmt.Println("CA_EVENT " + string(b))
}
func authorityWait(t *testing.T, f Future) error {
	t.Helper()
	done := make(chan error, 1)
	go func() { done <- f.Error() }()
	select {
	case err := <-done:
		return err
	case <-time.After(10 * time.Second):
		t.Fatal("future observation deadline")
		return nil
	}
}
func authorityPoll(t *testing.T, what string, p func() bool) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if p() {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("precondition not reached: %s", what)
}
func TestAssuranceVerifySupersededAuthority(t *testing.T) {
	const op = "superseded-verify-1"
	var nodes []*Raft
	var fsms []*MockFSM
	trans := make([]*authorityTransport, 4)
	config := Configuration{}
	for i := range trans {
		id := ServerID(fmt.Sprintf("authority-%d", i))
		addr := ServerAddress(id)
		_, base := NewInmemTransportWithTimeout(addr, 50*time.Millisecond)
		trans[i] = &authorityTransport{InmemTransport: base, successes: map[ServerID]int{}}
		suffrage := Voter
		if i == 3 {
			suffrage = Nonvoter
		}
		config.Servers = append(config.Servers, Server{ID: id, Address: addr, Suffrage: suffrage})
	}
	for i := range trans {
		for j := range trans {
			if i != j {
				trans[i].Connect(trans[j].LocalAddr(), trans[j].InmemTransport)
			}
		}
	}
	defer func() {
		var pending []Future
		for _, r := range nodes {
			pending = append(pending, r.Shutdown())
		}
		for _, tr := range trans {
			tr.Close()
		}
		for _, f := range pending {
			authorityWait(t, f)
		}
	}()
	for i := range trans {
		c := DefaultConfig()
		c.LocalID = config.Servers[i].ID
		c.CommitTimeout = 10 * time.Millisecond
		c.HeartbeatTimeout = 150 * time.Millisecond
		c.ElectionTimeout = 150 * time.Millisecond
		c.LeaderLeaseTimeout = 150 * time.Millisecond
		if i == 0 {
			c.HeartbeatTimeout = 3 * time.Second
			c.ElectionTimeout = 3 * time.Second
			c.LeaderLeaseTimeout = 3 * time.Second
		}
		if i == 3 {
			c.HeartbeatTimeout = 3 * time.Second
			c.ElectionTimeout = 3 * time.Second
			c.LeaderLeaseTimeout = 3 * time.Second
		}
		store := NewInmemStore()
		snap := NewInmemSnapshotStore()
		fsm := &MockFSM{}
		if i == 0 {
			initial := Configuration{Servers: []Server{config.Servers[0]}}
			if err := BootstrapCluster(c, store, store, snap, trans[i], initial); err != nil {
				t.Fatal(err)
			}
		}
		r, err := NewRaft(c, fsm, store, store, snap, trans[i])
		if err != nil {
			t.Fatal(err)
		}
		nodes = append(nodes, r)
		fsms = append(fsms, fsm)
	}
	old := nodes[0]
	authorityPoll(t, "initial single-voter election", func() bool { return old.State() == Leader })
	for i := 1; i <= 2; i++ {
		s := config.Servers[i]
		if err := authorityWait(t, old.AddVoter(s.ID, s.Address, 0, time.Second)); err != nil {
			t.Fatal(err)
		}
	}
	s := config.Servers[3]
	if err := authorityWait(t, old.AddNonvoter(s.ID, s.Address, 0, time.Second)); err != nil {
		t.Fatal(err)
	}
	prefix := old.Apply([]byte("common-prefix"), time.Second)
	if err := authorityWait(t, prefix); err != nil {
		t.Fatal(err)
	}
	authorityPoll(t, "all nodes have final membership and committed prefix", func() bool {
		for _, r := range nodes {
			if !reflect.DeepEqual(r.getLatestConfiguration(), config) || r.CommitIndex() < prefix.Index() {
				return false
			}
		}
		return true
	})
	if err := authorityWait(t, old.VerifyLeader()); err != nil {
		t.Fatal(err)
	}
	authorityEvent(map[string]interface{}{"event": "connected_control", "operation": "connected-control", "success": true, "term": old.CurrentTerm()})
	oldTerm := old.CurrentTerm()
	authorityEvent(map[string]interface{}{"event": "stable_prefix", "operation": op, "old_term": oldTerm, "prefix_index": prefix.Index(), "configuration": config})
	// Disconnect every RPC route crossing {old leader, nonvoter} and {two voters}.
	// Already admitted requests are allowed to finish. No state is assigned and
	// every worker, lease timer and negative-response path remains enabled.
	for _, i := range []int{0, 3} {
		for _, j := range []int{1, 2} {
			trans[i].Disconnect(trans[j].LocalAddr())
			trans[j].Disconnect(trans[i].LocalAddr())
		}
	}
	var replacement *Raft
	ri := -1
	authorityPoll(t, "higher-term elected replacement", func() bool {
		for _, i := range []int{1, 2} {
			if nodes[i].State() == Leader && nodes[i].CurrentTerm() > oldTerm {
				replacement = nodes[i]
				ri = i
				return true
			}
		}
		return false
	})
	command := replacement.Apply([]byte("replacement-command"), time.Second)
	if err := authorityWait(t, command); err != nil {
		t.Fatal(err)
	}
	fsms[ri].Lock()
	seen := false
	for _, data := range fsms[ri].logs {
		if string(data) == "replacement-command" {
			seen = true
		}
	}
	fsms[ri].Unlock()
	replacementTerm := replacement.CurrentTerm()
	if !seen || replacementTerm <= oldTerm || replacement.State() != Leader {
		t.Fatal("replacement authority prerequisite not established")
	}
	authorityEvent(map[string]interface{}{"event": "superseding_command", "operation": op, "old_term": oldTerm, "new_term": replacementTerm, "new_leader": replacement.localID, "command_index": command.Index(), "command_applied": seen, "higher_term": replacementTerm > oldTerm})
	// A newer term on the old node would complicate the selected continuity
	// premise. Leave that schedule incomplete rather than changing the oracle.
	if old.CurrentTerm() != oldTerm {
		t.Fatal("old-node term changed before verification admission")
	}
	before := trans[0].counts()
	authorityEvent(map[string]interface{}{"event": "verification_admitted", "operation": op, "new_term": replacementTerm, "old_term": old.CurrentTerm(), "state": old.State().String(), "before": before})
	future := old.VerifyLeader()
	done := make(chan error, 1)
	go func() { done <- future.Error() }()
	forced := false
	var result error
	select {
	case result = <-done:
	case <-time.After(700 * time.Millisecond):
		// Stop the controlled operation independently of its forbidden outcome.
		forced = true
		shutdown := old.Shutdown()
		select {
		case result = <-done:
		case <-time.After(2 * time.Second):
			t.Fatal("verification completion missing after shutdown")
		}
		if err := authorityWait(t, shutdown); err != nil {
			t.Fatal(err)
		}
	}
	authorityEvent(map[string]interface{}{"event": "verification_result", "operation": op, "success": result == nil, "error": fmt.Sprint(result), "shutdown_forced": forced, "old_term": old.CurrentTerm(), "new_term": replacementTerm, "state": old.State().String(), "after": trans[0].counts()})
}
