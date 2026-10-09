package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"testing"
	"time"
)

// The FSM owns its observation state; sampling does not read Raft internals.
type assuranceFSM struct {
	mu     sync.Mutex
	values []string
}

func (f *assuranceFSM) Apply(l *Log) interface{} {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.values = append(f.values, string(l.Data))
	return len(f.values)
}
func (f *assuranceFSM) Snapshot() (FSMSnapshot, error) {
	return nil, fmt.Errorf("snapshot not used by this bounded test")
}
func (f *assuranceFSM) Restore(io.ReadCloser) error {
	return fmt.Errorf("restore not used by this bounded test")
}
func (f *assuranceFSM) contains(v string) bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	for _, x := range f.values {
		if x == v {
			return true
		}
	}
	return false
}
func assuranceEvent(event string, fields map[string]interface{}) {
	fields["event"] = event
	b, err := json.Marshal(fields)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}
func assuranceWait(t *testing.T, why string, limit time.Duration, ready func() bool) {
	t.Helper()
	end := time.Now().Add(limit)
	for time.Now().Before(end) {
		if ready() {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("unreached prerequisite: %s", why)
}

func TestAssuranceVerifyAfterMajorityElection(t *testing.T) {
	const op = "verify-old-A"
	names := []ServerID{"A", "B", "C", "N"}
	transports := make([]*InmemTransport, 4)
	configs := make([]*Config, 4)
	stores := make([]*InmemStore, 4)
	snaps := make([]*InmemSnapshotStore, 4)
	fsms := make([]*assuranceFSM, 4)
	nodes := make([]*Raft, 4)
	for i, id := range names {
		_, transports[i] = NewInmemTransportWithTimeout(ServerAddress(id), 50*time.Millisecond)
		configs[i] = DefaultConfig()
		configs[i].LocalID = id
		configs[i].LogOutput = io.Discard
		configs[i].HeartbeatTimeout = 200 * time.Millisecond
		configs[i].ElectionTimeout = 200 * time.Millisecond
		configs[i].LeaderLeaseTimeout = 100 * time.Millisecond
		configs[i].CommitTimeout = 10 * time.Millisecond
		configs[i].SnapshotInterval = time.Hour
		configs[i].SnapshotThreshold = 100000
		if i == 0 {
			configs[i].HeartbeatTimeout = 3 * time.Second
			configs[i].ElectionTimeout = 3 * time.Second
			configs[i].LeaderLeaseTimeout = 3 * time.Second
		}
		if err := ValidateConfig(configs[i]); err != nil {
			t.Fatal(err)
		}
		stores[i] = NewInmemStore()
		snaps[i] = NewInmemSnapshotStore()
		fsms[i] = &assuranceFSM{}
	}
	for i := range names {
		for j := range names {
			if i != j {
				transports[i].Connect(ServerAddress(names[j]), transports[j])
			}
		}
	}
	// Bootstrap once, then use the normal membership API to add the other nodes.
	if err := BootstrapCluster(configs[0], stores[0], stores[0], snaps[0], transports[0], Configuration{Servers: []Server{{ID: "A", Address: "A", Suffrage: Voter}}}); err != nil {
		t.Fatal(err)
	}
	defer func() {
		var pending []Future
		for _, r := range nodes {
			if r != nil {
				pending = append(pending, r.Shutdown())
			}
		}
		for _, f := range pending {
			if err := f.Error(); err != nil {
				t.Errorf("shutdown: %v", err)
			}
		}
		for _, tr := range transports {
			if err := tr.Close(); err != nil {
				t.Errorf("transport close: %v", err)
			}
		}
		assuranceEvent("cleanup", map[string]interface{}{"operation": op, "joined": true})
	}()
	for i := range names {
		r, err := NewRaft(configs[i], fsms[i], stores[i], stores[i], snaps[i], transports[i])
		if err != nil {
			t.Fatal(err)
		}
		nodes[i] = r
	}
	assuranceWait(t, "A singleton leader", 8*time.Second, func() bool { return nodes[0].State() == Leader })
	for _, i := range []int{1, 2} {
		if err := nodes[0].AddVoter(names[i], ServerAddress(names[i]), 0, time.Second).Error(); err != nil {
			t.Fatal(err)
		}
	}
	added := nodes[0].AddNonvoter("N", "N", 0, time.Second)
	if err := added.Error(); err != nil {
		t.Fatal(err)
	}
	configIndex := added.Index()
	if err := nodes[0].Apply([]byte("prefix"), time.Second).Error(); err != nil {
		t.Fatal(err)
	}
	assuranceWait(t, "prefix applied on all four nodes", 3*time.Second, func() bool {
		for _, f := range fsms {
			if !f.contains("prefix") {
				return false
			}
		}
		return true
	})
	for i, r := range nodes {
		cf := r.GetConfiguration()
		if err := cf.Error(); err != nil {
			t.Fatal(err)
		}
		got := cf.Configuration()
		if len(got.Servers) != 4 {
			t.Fatalf("node %s has wrong configuration", names[i])
		}
		seen := make(map[ServerID]bool)
		for _, s := range got.Servers {
			want := Voter
			if s.ID == "N" {
				want = Nonvoter
			}
			if s.ID != "A" && s.ID != "B" && s.ID != "C" && s.ID != "N" {
				t.Fatal("unknown server")
			}
			if seen[s.ID] || s.Address != ServerAddress(s.ID) || s.Suffrage != want {
				t.Fatalf("unexpected configuration: %+v", got)
			}
			seen[s.ID] = true
		}
		var entry Log
		if err := stores[i].GetLog(configIndex, &entry); err != nil {
			t.Fatal(err)
		}
		if entry.Type != LogConfiguration {
			t.Fatal("configuration index is not a configuration log")
		}
	}
	oldTerm := nodes[0].CurrentTerm()
	// Partition {A,N} from {B,C} using the shipped transport's routing policy.
	// Disconnect closes any existing cross-partition pipelines. In-flight work
	// is not assumed absent; a later completed majority write establishes the
	// new authority before verification is invoked.
	for _, i := range []int{0, 3} {
		for _, j := range []int{1, 2} {
			transports[i].Disconnect(ServerAddress(names[j]))
			transports[j].Disconnect(ServerAddress(names[i]))
		}
	}
	assuranceEvent("partition", map[string]interface{}{"operation": op, "old_term": oldTerm, "configuration_index": configIndex, "old_group": "A,N", "majority_group": "B,C"})
	next := -1
	assuranceWait(t, "new majority leader", 2*time.Second, func() bool {
		for _, i := range []int{1, 2} {
			if nodes[i].State() == Leader && nodes[i].CurrentTerm() > oldTerm {
				next = i
				return true
			}
		}
		return false
	})
	marker := nodes[next].Apply([]byte("new-authority-marker"), time.Second)
	if err := marker.Error(); err != nil {
		t.Fatalf("majority marker did not complete: %v", err)
	}
	var markerLog Log
	if err := stores[next].GetLog(marker.Index(), &markerLog); err != nil {
		t.Fatal(err)
	}
	if markerLog.Type != LogCommand || string(markerLog.Data) != "new-authority-marker" || markerLog.Term <= oldTerm {
		t.Fatal("marker identity or newer term not established")
	}
	newTerm := markerLog.Term
	if !fsms[next].contains("new-authority-marker") {
		t.Fatal("completed marker missing from new leader FSM")
	}
	if nodes[0].State() != Leader || nodes[0].CurrentTerm() != oldTerm {
		t.Fatal("old local leader did not remain in original term for discriminator")
	}
	if fsms[0].contains("new-authority-marker") {
		t.Fatal("old FSM unexpectedly contains majority marker")
	}
	assuranceEvent("admitted", map[string]interface{}{"operation": op, "node": "A", "new_leader": string(names[next]), "old_term": oldTerm, "new_term": newTerm, "newer_term_established": newTerm > oldTerm, "marker_completed": true, "marker_index": marker.Index(), "old_marker_present": false, "configuration_index": configIndex, "policy": "three-voters-one-nonvoter-partition"})
	// Admission is immediately before the public invocation. Error waits for
	// this exact future, including lease-based failure if verification rejects.
	future := nodes[0].VerifyLeader()
	err := future.Error()
	errText := ""
	if err != nil {
		errText = err.Error()
	}
	assuranceEvent("verification_result", map[string]interface{}{"operation": op, "node": "A", "success": err == nil, "error": errText, "old_term_after": nodes[0].CurrentTerm(), "old_state_after": nodes[0].State().String(), "old_marker_present": fsms[0].contains("new-authority-marker"), "policy": "three-voters-one-nonvoter-partition"})
}
