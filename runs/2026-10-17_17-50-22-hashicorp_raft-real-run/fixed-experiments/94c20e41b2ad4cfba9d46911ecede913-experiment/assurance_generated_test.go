package raft

// Construction notes:
//   * Three real nodes run over in-memory transports. {A, B} are bootstrapped as
//     the committed voter set; C runs with no configuration at all and is
//     reachable, so the vote checks that are guarded by a non-empty server list
//     do not apply to it and it will grant votes and accept entries.
//   * The leader's log store fails exactly the write that would carry AddVoter(C),
//     so the in-memory latest configuration becomes {leader, other voter, C}
//     while the stored log never receives that entry.
//   * The leader is then cut from the other committed voter. In the trigger C
//     stays reachable, so the phantom quorum of two can be satisfied by the
//     leader plus C; in the control C is cut too, so the phantom quorum has no
//     attainable second voter.
//   * The decisive observation is whether a client command commits with the
//     committed voter absent, which no quorum of the committed two-voter
//     configuration allows.

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"testing"
	"time"
)

func pgEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

type pgFailStore struct {
	*InmemStore
	mu       sync.Mutex
	failNext bool
}

func newPgFailStore() *pgFailStore { return &pgFailStore{InmemStore: NewInmemStore()} }

func (f *pgFailStore) StoreLogs(logs []*Log) error {
	f.mu.Lock()
	fail := f.failNext
	f.failNext = false
	f.mu.Unlock()
	if fail {
		return pgErr("injected store failure")
	}
	return f.InmemStore.StoreLogs(logs)
}

type pgErr string

func (e pgErr) Error() string { return string(e) }

type pgFSM struct{}

func (f *pgFSM) Apply(*Log) interface{}         { return nil }
func (f *pgFSM) Snapshot() (FSMSnapshot, error) { return &pgSnap{}, nil }
func (f *pgFSM) Restore(io.ReadCloser) error    { return nil }

type pgSnap struct{}

func (s *pgSnap) Persist(SnapshotSink) error { return nil }
func (s *pgSnap) Release()                   {}

func pgRun(t *testing.T, caseName string, cutNew bool) {
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

	storeA, storeB := newPgFailStore(), newPgFailStore()
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

	rA, err := NewRaft(&confA, &pgFSM{}, storeA, storeA, snapsA, transA)
	if err != nil {
		t.Fatalf("raft A: %v", err)
	}
	defer func() { _ = rA.Shutdown().Error() }()
	rB, err := NewRaft(&confB, &pgFSM{}, storeB, storeB, snapsB, transB)
	if err != nil {
		t.Fatalf("raft B: %v", err)
	}
	defer func() { _ = rB.Shutdown().Error() }()
	// C has no configuration: it is the new server the failed AddVoter names.
	rC, err := NewRaft(&confC, &pgFSM{}, storeC, storeC, snapsC, transC)
	if err != nil {
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
	stL, stP := storeA, storeB
	transL, transP := transA, transB
	addrL, addrP := addrA, addrB
	peerID := ServerID("B")
	if rA.Leader() == "B" {
		rL, rP = rB, rA
		stL, stP = storeB, storeA
		transL, transP = transB, transA
		addrL, addrP = addrB, addrA
		peerID = "A"
	}
	_ = rP

	stL.mu.Lock()
	stL.failNext = true
	stL.mu.Unlock()
	errAdd := rL.AddVoter("C", addrC, 0, 5*time.Second).Error()
	lastLogL, _ := stL.LastIndex()
	latestIndex := rL.configurations.latestIndex
	latestServers := rL.getLatestConfiguration().Servers
	pgEmit(t, map[string]interface{}{
		"event":                     "pg_case_" + caseName,
		"case":                      caseName,
		"members":                   3,
		"committed_voters":          2,
		"failure_injected":          true,
		"leader":                    string(rL.localID),
		"committed_peer":            string(peerID),
		"add_error":                 fmt.Sprintf("%v", errAdd),
		"add_failed":                errAdd != nil,
		"latest_index_after_fail":   latestIndex,
		"last_log_index_after_fail": lastLogL,
		"phantom_voters":            len(latestServers),
		"phantom_servers":           fmt.Sprintf("%v", latestServers),
	})

	// Cut the leader from the other committed voter; optionally cut C as well.
	transL.Disconnect(addrP)
	transP.Disconnect(addrL)
	if cutNew {
		transL.Disconnect(addrC)
		transC.Disconnect(addrL)
	}

	deadline = time.Now().Add(10 * time.Second)
	for rL.State() != Leader && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	reElected := rL.State() == Leader
	applyErr := rL.Apply([]byte("grown-phantom"), 3*time.Second).Error()
	commitL := rL.CommitIndex()
	lastL, _ := stL.LastIndex()
	lastP, _ := stP.LastIndex()
	lastC, _ := storeC.LastIndex()
	pgEmit(t, map[string]interface{}{
		"event":                         "pg_result_" + caseName,
		"case":                          caseName,
		"cut_new_server":                cutNew,
		"latest_index_exceeds_log":      latestIndex > lastLogL,
		"re_elected":                    reElected,
		"apply_ok":                      applyErr == nil,
		"commit_index":                  commitL,
		"leader_last_index":             lastL,
		"committed_peer_last_index":     lastP,
		"new_server_last_index":         lastC,
		"committed_peer_has_entry":      lastP >= commitL,
		"new_server_has_entry":          lastC >= commitL,
		"commit_without_committed_voter": applyErr == nil && lastP < commitL,
	})
	t.Logf("case=%v reElected=%v applyErr=%v commitL=%d lastL=%d lastP=%d lastC=%d",
		caseName, reElected, applyErr, commitL, lastL, lastP, lastC)
}

func TestAssurancePhantomGrownQuorum(t *testing.T) {
	t.Run("grow_reachable_new_server", func(t *testing.T) {
		pgRun(t, "grow_reachable_new_server", false)
	})
	t.Run("grow_cut_new_server", func(t *testing.T) {
		pgRun(t, "grow_cut_new_server", true)
	})
}
