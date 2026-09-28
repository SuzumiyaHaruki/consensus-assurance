package raft

import (
	"encoding/json"
	"fmt"
	"sync"
	"testing"
	"time"
)

// The wrapper selects a supported non-pipelined transport mode and controls
// outgoing AppendEntries delivery without manufacturing protocol responses.
type assuranceTransport struct {
	*InmemTransport
	gate      sync.RWMutex
	blocked   map[ServerID]bool
	mu        sync.Mutex
	successes map[ServerID]int
}

func (a *assuranceTransport) AppendEntriesPipeline(id ServerID, target ServerAddress) (AppendPipeline, error) {
	return nil, ErrPipelineReplicationNotSupported
}
func (a *assuranceTransport) AppendEntries(id ServerID, target ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
	a.gate.RLock()
	defer a.gate.RUnlock()
	if a.blocked[id] {
		return fmt.Errorf("exploration link unavailable: %s", id)
	}
	err := a.InmemTransport.AppendEntries(id, target, req, resp)
	if err == nil && resp.Success {
		a.mu.Lock()
		a.successes[id]++
		a.mu.Unlock()
	}
	return err
}
func (a *assuranceTransport) links(blocked map[ServerID]bool) {
	// Wait for transport calls already admitted through this wrapper to return.
	// Their caller-side consumption is not synchronized by this lock.
	a.gate.Lock()
	a.blocked = blocked
	a.gate.Unlock()
}
func (a *assuranceTransport) counts() map[ServerID]int {
	a.mu.Lock()
	defer a.mu.Unlock()
	out := make(map[ServerID]int)
	for k, v := range a.successes {
		out[k] = v
	}
	return out
}
func assuranceEmit(v map[string]interface{}) {
	b, _ := json.Marshal(v)
	fmt.Println("CA_EVENT " + string(b))
}
func assuranceWait(t *testing.T, f Future) error {
	t.Helper()
	ch := make(chan error, 1)
	go func() { ch <- f.Error() }()
	select {
	case e := <-ch:
		return e
	case <-time.After(8 * time.Second):
		t.Fatal("future observation deadline")
		return nil
	}
}
func TestAssuranceExploreVerificationEligibility(t *testing.T) {
	const n = 4
	var nodes []*Raft
	trans := make([]*assuranceTransport, n)
	config := Configuration{}
	for i := 0; i < n; i++ {
		id := ServerID(fmt.Sprintf("probe-%d", i))
		addr := ServerAddress(id)
		_, base := NewInmemTransportWithTimeout(addr, 100*time.Millisecond)
		trans[i] = &assuranceTransport{InmemTransport: base, blocked: map[ServerID]bool{}, successes: map[ServerID]int{}}
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
		var fs []Future
		for _, r := range nodes {
			fs = append(fs, r.Shutdown())
		}
		for _, tr := range trans {
			tr.Close()
		}
		for _, f := range fs {
			assuranceWait(t, f)
		}
	}()
	for i := range trans {
		c := DefaultConfig()
		c.LocalID = config.Servers[i].ID
		c.HeartbeatTimeout = 2 * time.Second
		c.ElectionTimeout = 2 * time.Second
		c.LeaderLeaseTimeout = 2 * time.Second
		c.CommitTimeout = 20 * time.Millisecond
		store := NewInmemStore()
		snap := NewInmemSnapshotStore()
		if err := BootstrapCluster(c, store, store, snap, trans[i], config); err != nil {
			t.Fatal(err)
		}
		r, err := NewRaft(c, &MockFSM{}, store, store, snap, trans[i])
		if err != nil {
			t.Fatal(err)
		}
		nodes = append(nodes, r)
	}
	var leader *Raft
	li := -1
	deadline := time.Now().Add(12 * time.Second)
	for time.Now().Before(deadline) && leader == nil {
		for i, r := range nodes {
			if r.State() == Leader {
				leader = r
				li = i
				break
			}
		}
		if leader == nil {
			time.Sleep(10 * time.Millisecond)
		}
	}
	if leader == nil {
		t.Fatal("no elected leader before observation deadline")
	}
	if err := assuranceWait(t, leader.Apply([]byte("prefix"), time.Second)); err != nil {
		t.Fatal(err)
	}
	cf := leader.GetConfiguration()
	if err := assuranceWait(t, cf); err != nil {
		t.Fatal(err)
	}
	assuranceEmit(map[string]interface{}{"event": "prefix", "leader": leader.localID, "term": leader.CurrentTerm(), "configuration": cf.Configuration(), "configuration_index": cf.Index(), "commit_index": leader.CommitIndex()})
	control := assuranceWait(t, leader.VerifyLeader())
	assuranceEmit(map[string]interface{}{"event": "connected_control", "error": fmt.Sprint(control), "state": leader.State().String()})
	blocked := map[ServerID]bool{}
	for _, s := range config.Servers {
		if s.ID != leader.localID {
			blocked[s.ID] = true
		}
	}
	trans[li].links(blocked)
	// This finite settling interval reduces old-call interference but is not a
	// proof that every prior caller has consumed its returned response.
	time.Sleep(150 * time.Millisecond)
	before := trans[li].counts()
	f := leader.VerifyLeader()
	done := make(chan error, 1)
	go func() { done <- f.Error() }()
	select {
	case e := <-done:
		assuranceEmit(map[string]interface{}{"event": "early_result", "error": fmt.Sprint(e), "counts": trans[li].counts(), "before": before})
		return
	case <-time.After(50 * time.Millisecond):
		assuranceEmit(map[string]interface{}{"event": "pending_before_release", "operation": "isolated-verification", "state": leader.State().String(), "term": leader.CurrentTerm(), "before": before})
	}
	onlyVotersBlocked := map[ServerID]bool{}
	for _, s := range config.Servers {
		if s.ID != leader.localID && s.Suffrage == Voter {
			onlyVotersBlocked[s.ID] = true
		}
	}
	trans[li].links(onlyVotersBlocked)
	assuranceEmit(map[string]interface{}{"event": "nonvoter_link_released", "operation": "isolated-verification", "nonvoter": config.Servers[3].ID})
	select {
	case e := <-done:
		assuranceEmit(map[string]interface{}{"event": "verification_result", "operation": "isolated-verification", "error": fmt.Sprint(e), "state": leader.State().String(), "term": leader.CurrentTerm(), "before": before, "after": trans[li].counts()})
	case <-time.After(4 * time.Second):
		assuranceEmit(map[string]interface{}{"event": "observation_timeout", "operation": "isolated-verification", "state": leader.State().String(), "before": before, "after": trans[li].counts()})
	}
}
