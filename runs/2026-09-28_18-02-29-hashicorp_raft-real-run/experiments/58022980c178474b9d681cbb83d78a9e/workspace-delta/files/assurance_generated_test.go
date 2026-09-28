package raft

import (
	"encoding/json"
	"fmt"
	"reflect"
	"sync"
	"testing"
	"time"
)

// Gate calls before delivery. Each peer has exactly one ordinary replication
// worker and one heartbeat worker; pipelines are explicitly unsupported.
type assuranceVerifyTransport struct {
	*InmemTransport
	mu      sync.Mutex
	active  bool
	gates   map[ServerID]chan struct{}
	blocked map[string]bool
	replies map[ServerID]int
}

func (g *assuranceVerifyTransport) AppendEntriesPipeline(ServerID, ServerAddress) (AppendPipeline, error) {
	return nil, ErrPipelineReplicationNotSupported
}
func (g *assuranceVerifyTransport) AppendEntries(id ServerID, address ServerAddress, req *AppendEntriesRequest, resp *AppendEntriesResponse) error {
	kind := "append"
	if req.PrevLogEntry == 0 && req.PrevLogTerm == 0 && len(req.Entries) == 0 && req.LeaderCommitIndex == 0 {
		kind = "heartbeat"
	}
	g.mu.Lock()
	var wait chan struct{}
	if g.active {
		wait = g.gates[id]
		g.blocked[string(id)+"/"+kind] = true
	}
	g.mu.Unlock()
	if wait != nil {
		<-wait
	}
	err := g.InmemTransport.AppendEntries(id, address, req, resp)
	g.mu.Lock()
	if g.active && err == nil && resp.Success {
		g.replies[id]++
	}
	g.mu.Unlock()
	return err
}
func (g *assuranceVerifyTransport) release(id ServerID) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if ch := g.gates[id]; ch != nil {
		close(ch)
		g.gates[id] = nil
	}
}
func assuranceVerifyEvent(e map[string]interface{}) {
	b, _ := json.Marshal(e)
	fmt.Println("CA_EVENT " + string(b))
}
func assuranceWait(t *testing.T, d time.Duration, f func() bool, what string) {
	t.Helper()
	until := time.Now().Add(d)
	for time.Now().Before(until) {
		if f() {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("setup incomplete: %s", what)
}
func TestAssuranceVerifyParticipantEligibility(t *testing.T) {
	for _, selected := range []int{3, 1} {
		name := "nonvoter"
		if selected == 1 {
			name = "voter_control"
		}
		t.Run(name, func(t *testing.T) {
			ids := []ServerID{"leader", "voter-b", "voter-c", "nonvoter"}
			config := Configuration{}
			transports := make([]*InmemTransport, 4)
			for i, id := range ids {
				addr, tr := NewInmemTransportWithTimeout(ServerAddress(string(id)), 200*time.Millisecond)
				transports[i] = tr
				suffrage := Voter
				if i == 3 {
					suffrage = Nonvoter
				}
				config.Servers = append(config.Servers, Server{ID: id, Address: addr, Suffrage: suffrage})
			}
			for i := range ids {
				for j := range ids {
					if i != j {
						transports[i].Connect(ServerAddress(ids[j]), transports[j])
					}
				}
			}
			gate := &assuranceVerifyTransport{InmemTransport: transports[0], gates: make(map[ServerID]chan struct{}), blocked: make(map[string]bool), replies: make(map[ServerID]int)}
			nodes := make([]*Raft, 0, 4)
			defer func() {
				for _, id := range ids[1:] {
					gate.release(id)
				}
				futures := make([]Future, 0, len(nodes))
				for _, r := range nodes {
					futures = append(futures, r.Shutdown())
				}
				for _, f := range futures {
					_ = f.Error()
				}
				for _, tr := range transports {
					_ = tr.Close()
				}
			}()
			for i, id := range ids {
				conf := DefaultConfig()
				conf.LocalID = id
				conf.HeartbeatTimeout = 5 * time.Second
				conf.ElectionTimeout = 5 * time.Second
				conf.LeaderLeaseTimeout = 900 * time.Millisecond
				conf.CommitTimeout = 20 * time.Millisecond
				if i == 0 {
					conf.HeartbeatTimeout = time.Second
					conf.ElectionTimeout = time.Second
				}
				store := NewInmemStore()
				snapshots := NewInmemSnapshotStore()
				var tr Transport = transports[i]
				if i == 0 {
					tr = gate
				}
				if err := BootstrapCluster(conf, store, store, snapshots, tr, config); err != nil {
					t.Fatal(err)
				}
				r, err := NewRaft(conf, &MockFSM{}, store, store, snapshots, tr)
				if err != nil {
					t.Fatal(err)
				}
				nodes = append(nodes, r)
			}
			leader := nodes[0]
			assuranceWait(t, 4*time.Second, func() bool { return leader.State() == Leader }, "real election of local voter")
			apply := leader.Apply([]byte("prefix-"+name), time.Second)
			applyDone := make(chan error, 1)
			go func() { applyDone <- apply.Error() }()
			select {
			case err := <-applyDone:
				if err != nil {
					t.Fatal(err)
				}
			case <-time.After(2 * time.Second):
				t.Fatal("prefix apply incomplete")
			}
			cf := leader.GetConfiguration()
			if err := cf.Error(); err != nil {
				t.Fatal(err)
			}
			var configEntry Log
			if err := leader.logs.GetLog(1, &configEntry); err != nil {
				t.Fatal(err)
			}
			if configEntry.Type != LogConfiguration || !reflect.DeepEqual(DecodeConfiguration(configEntry.Data), config) || !reflect.DeepEqual(cf.Configuration(), config) {
				t.Fatal("configuration differs from bootstrap")
			}
			if leader.CommitIndex() < configEntry.Index {
				t.Fatal("configuration not committed")
			}
			for i := 1; i < 4; i++ {
				idx := apply.Index()
				assuranceWait(t, time.Second, func() bool { return nodes[i].AppliedIndex() >= idx }, "all peers receive committed prefix")
			}
			term := leader.CurrentTerm()
			gate.mu.Lock()
			for _, id := range ids[1:] {
				gate.gates[id] = make(chan struct{})
			}
			gate.active = true
			gate.mu.Unlock()
			// Reaching the next transport call on both loops proves that each loop
			// consumed its preceding reply before we admit the verification operation.
			assuranceWait(t, 500*time.Millisecond, func() bool {
				gate.mu.Lock()
				defer gate.mu.Unlock()
				for _, id := range ids[1:] {
					if !gate.blocked[string(id)+"/append"] || !gate.blocked[string(id)+"/heartbeat"] {
						return false
					}
				}
				return true
			}, "all six sender loops quiescent at transport boundary")
			if leader.State() != Leader || leader.CurrentTerm() != term {
				t.Fatal("leader generation changed before admission")
			}
			gate.mu.Lock()
			gate.replies = make(map[ServerID]int)
			gate.mu.Unlock()
			assuranceVerifyEvent(map[string]interface{}{"event": "prefix", "op": name, "term": term, "configuration_index": configEntry.Index, "applied_index": apply.Index(), "voters": 3, "quiescent_loops": 6, "selected_id": string(ids[selected]), "selected_voter": config.Servers[selected].Suffrage == Voter})
			vf := leader.VerifyLeader()
			assuranceVerifyEvent(map[string]interface{}{"event": "admitted", "op": name, "term": term})
			gate.release(ids[selected])
			result := make(chan error, 1)
			go func() { result <- vf.Error() }()
			select {
			case err := <-result:
				gate.mu.Lock()
				voterReplies := gate.replies[ids[1]] + gate.replies[ids[2]]
				nonvoterReplies := gate.replies[ids[3]]
				gate.mu.Unlock()
				errText := ""
				if err != nil {
					errText = err.Error()
				}
				assuranceVerifyEvent(map[string]interface{}{"event": "result", "op": name, "success": err == nil, "error": errText, "remote_voter_reply": voterReplies > 0, "voter_replies": voterReplies, "nonvoter_replies": nonvoterReplies, "selected_id": string(ids[selected]), "term": leader.CurrentTerm(), "state": leader.State().String()})
			case <-time.After(600 * time.Millisecond):
				assuranceVerifyEvent(map[string]interface{}{"event": "incomplete", "op": name, "reason": "no result before finite schedule ends"})
			}
		})
	}
}
