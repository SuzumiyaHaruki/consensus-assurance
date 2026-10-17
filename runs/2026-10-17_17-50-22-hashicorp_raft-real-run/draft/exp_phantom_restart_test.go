package raft

// Construction notes:
//   * Three real nodes over in-memory transports. A and B are bootstrapped as the
//     committed voter set; C runs with no configuration and is reachable.
//   * The leader's log store fails exactly the write that would carry AddVoter(C),
//     so the in-memory latest configuration grows to include C while the stored
//     log never receives that entry.
//   * The leader is cut from the other committed voter but stays reachable to C,
//     applies a command with the phantom quorum, and is then shut down.
//   * A fresh Raft is started over the same stores and transport, and the probe
//     records the configuration it loads and whether the stored log contains the
//     entry that was committed under the phantom configuration.

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"testing"
	"time"
)

func prEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

type prFailStore struct {
	*InmemStore
	mu       sync.Mutex
	failNext bool
}

func newPrFailStore() *prFailStore { return &prFailStore{InmemStore: NewInmemStore()} }

func (f *prFailStore) StoreLogs(logs []*Log) error {
	f.mu.Lock()
	fail := f.failNext
	f.failNext = false
	f.mu.Unlock()
	if fail {
		return fmt.Errorf("injected store failure")
	}
	return f.InmemStore.StoreLogs(logs)
}

type prFSM struct{ applied int }

func (f *prFSM) Apply(*Log) interface{}         { f.applied++; return nil }
func (f *prFSM) Snapshot() (FSMSnapshot, error) { return &prSnap{}, nil }
func (f *prFSM) Restore(io.ReadCloser) error    { f.applied = 0; return nil }

type prSnap struct{}

func (s *prSnap) Persist(SnapshotSink) error { return nil }
func (s *prSnap) Release()                   {}

func TestAssurancePhantomConfigRestart(t *testing.T) {
	base := inmemConfig(t)
	base.HeartbeatTimeout = 300 * time.Millisecond
	base.ElectionTimeout = 300 * time.Millisecond
	base.LeaderLeaseTimeout = 300 * time.Millisecond

	addrA, transA := NewInmemTransport("A")
	addrB, transB := NewInmemTransport("B")
	addrC, transC := NewInmemTransport("C")
	transA.Connect(addrB, transB)
	transA.Connect(addrC, transC)
	transB.Connect(addrA, transA)
	transB.Connect(addrC, transC)
	transC.Connect(addrA, transA)
	transC.Connect(addrB, transB)

	storeA, storeB := newPrFailStore(), newPrFailStore()
	storeC := NewInmemStore()
	snapsA, snapsB, snapsC := NewInmemSnapshotStore(), NewInmemSnapshotStore(), NewInmemSnapshotStore()
	committed := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "A", Address: addrA},
		{Suffrage: Voter, ID: "B", Address: addrB},
	}}

	confA := *base
	confA.LocalID = "A"
	confB := *base
	confB.LocalID = "B"
	confC := *base
	confC.LocalID = "C"
	if err := BootstrapCluster(&confA, storeA, storeA, snapsA, transA, committed); err != nil {
		t.Fatalf("bootstrap A: %v", err)
	}
	if err := BootstrapCluster(&confB, storeB, storeB, snapsB, transB, committed); err != nil {
		t.Fatalf("bootstrap B: %v", err)
	}

	rA, err := NewRaft(&confA, &prFSM{}, storeA, storeA, snapsA, transA)
	if err != nil {
		t.Fatalf("raft A: %v", err)
	}
	rB, err := NewRaft(&confB, &prFSM{}, storeB, storeB, snapsB, transB)
	if err != nil {
		_ = rA.Shutdown().Error()
		t.Fatalf("raft B: %v", err)
	}
	defer func() { _ = rB.Shutdown().Error() }()
	rC, err := NewRaft(&confC, &prFSM{}, storeC, storeC, snapsC, transC)
	if err != nil {
		_ = rA.Shutdown().Error()
		t.Fatalf("raft C: %v", err)
	}
	defer func() { _ = rC.Shutdown().Error() }()

	deadline := time.Now().Add(10 * time.Second)
	for rA.Leader() == "" && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if rA.Leader() == "" {
		t.Fatalf("no leader formed in the two-voter committed configuration")
	}

	rL, rP := rA, rB
	stL := storeA
	confL := &confA
	snapsL := snapsA
	transL, transP := transA, transB
	addrL, addrP := addrA, addrB
	if rA.Leader() == "B" {
		rL, rP = rB, rA
		stL = storeB
		confL = &confB
		snapsL = snapsB
		transL, transP = transB, transA
		addrL, addrP = addrB, addrA
	}
	_ = rP

	stL.mu.Lock()
	stL.failNext = true
	stL.mu.Unlock()
	errAdd := rL.AddVoter("C", addrC, 0, 5*time.Second).Error()
	lastLogL, _ := stL.LastIndex()
	latestIndex := rL.configurations.latestIndex
	latestServers := rL.getLatestConfiguration().Servers

	transL.Disconnect(addrP)
	transP.Disconnect(addrL)
	deadline = time.Now().Add(10 * time.Second)
	for rL.State() != Leader && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	applyErr := rL.Apply([]byte("phantom-restart"), 3*time.Second).Error()
	commitL := rL.CommitIndex()
	lastL, _ := stL.LastIndex()
	lastP, _ := storeB.LastIndex()
	if rL.localID == "B" {
		lastP, _ = storeA.LastIndex()
	}
	prEmit(t, map[string]interface{}{
		"event":                     "pr_case_phantom_commit",
		"case":                      "phantom_restart",
		"phase":                     "commit",
		"add_failed":                errAdd != nil,
		"latest_index_after_fail":   latestIndex,
		"last_log_index_after_fail": lastLogL,
		"phantom_voters":            len(latestServers),
		"apply_ok":                  applyErr == nil,
		"commit_index":              commitL,
		"leader_last_index":         lastL,
		"committed_peer_last_index": lastP,
		"committed_peer_has_entry":  lastP >= commitL,
	})

	if err := rL.Shutdown().Error(); err != nil {
		t.Fatalf("shutdown leader: %v", err)
	}

	restarted, err := NewRaft(confL, &prFSM{}, stL, stL, snapsL, transL)
	if err != nil {
		t.Fatalf("restart leader raft: %v", err)
	}
	defer func() { _ = restarted.Shutdown().Error() }()
	var loaded Configuration
	cfgErr := restarted.GetConfiguration().Error()
	if cfgErr == nil {
		loaded = restarted.GetConfiguration().Configuration()
	}
	loadedIDs := []string{}
	loadedHasC := false
	loadedVoters := 0
	for _, srv := range loaded.Servers {
		loadedIDs = append(loadedIDs, string(srv.ID))
		if srv.ID == "C" {
			loadedHasC = true
		}
		if srv.Suffrage == Voter {
			loadedVoters++
		}
	}
	restartLast, _ := stL.LastIndex()
	restartCommit := uint64(0)
	prEmit(t, map[string]interface{}{
		"event":                          "pr_result_phantom_restart",
		"case":                           "phantom_restart",
		"config_error":                   fmt.Sprintf("%v", cfgErr),
		"restarted_servers":              fmt.Sprintf("%v", loadedIDs),
		"restarted_has_new_server":       loadedHasC,
		"restarted_voters":               loadedVoters,
		"restart_last_log_index":         restartLast,
		"restart_commit_index":           restartCommit,
		"phantom_commit_index":           commitL,
		"stored_log_has_committed_entry": restartLast >= commitL,
		"phantom_survived_restart":       loadedHasC,
	})
	t.Logf("add_failed=%v applyErr=%v commit=%d lastL=%d lastP=%d restartLast=%d hasC=%v servers=%v",
		errAdd != nil, applyErr, commitL, lastL, lastP, restartLast, loadedHasC, loadedIDs)
}
