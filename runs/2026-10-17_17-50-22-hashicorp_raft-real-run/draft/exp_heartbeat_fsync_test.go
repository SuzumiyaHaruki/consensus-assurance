package raft

// Construction notes:
//   * Same follower race as the jitter probes, but the stable store performs a
//     real file write plus fsync for every current-term update instead of
//     sleeping for a synthetic delay.
//   * This tests whether the inversion appears under genuine disk latency
//     rather than under an injected sleep.
//   * The harness records the inversion count, the number of attempts, and the
//     mean and maximum duration of the term write so the latency actually
//     exercised is visible in the receipt.

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

type fsyncStore struct {
	*InmemStore
	mu       sync.Mutex
	file     *os.File
	total    time.Duration
	max      time.Duration
	writes   int
}

func newFsyncStore(dir string) (*fsyncStore, error) {
	f, err := os.Create(filepath.Join(dir, "term.bin"))
	if err != nil {
		return nil, err
	}
	return &fsyncStore{InmemStore: NewInmemStore(), file: f}, nil
}

func (s *fsyncStore) SetUint64(key []byte, val uint64) error {
	if string(key) == string(keyCurrentTerm) {
		var buf [8]byte
		binary.LittleEndian.PutUint64(buf[:], val)
		start := time.Now()
		if _, err := s.file.WriteAt(buf[:], 0); err != nil {
			return err
		}
		if err := s.file.Sync(); err != nil {
			return err
		}
		d := time.Since(start)
		s.mu.Lock()
		s.total += d
		s.writes++
		if d > s.max {
			s.max = d
		}
		s.mu.Unlock()
	}
	return s.InmemStore.SetUint64(key, val)
}

func (s *fsyncStore) stats() (time.Duration, time.Duration, int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.writes == 0 {
		return 0, 0, 0
	}
	return s.total / time.Duration(s.writes), s.max, s.writes
}

type fsFSM struct{ mu sync.Mutex }

func (f *fsFSM) Apply(*Log) interface{}         { return nil }
func (f *fsFSM) Snapshot() (FSMSnapshot, error) { return &fsSnapshot{}, nil }
func (f *fsFSM) Restore(io.ReadCloser) error    { return nil }

type fsSnapshot struct{}

func (s *fsSnapshot) Persist(SnapshotSink) error { return nil }
func (s *fsSnapshot) Release()                  {}

func fsEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

func TestAssuranceHeartbeatFsync(t *testing.T) {
	const attempts = 200
	store, err := newFsyncStore(t.TempDir())
	if err != nil {
		t.Fatalf("store: %v", err)
	}
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("F")
	trans.Connect(addr, trans)

	conf := DefaultConfig()
	conf.LocalID = "F"
	conf.Logger = hclog.NewNullLogger()
	conf.LogLevel = "ERROR"
	conf.ElectionTimeout = 30 * time.Second
	conf.HeartbeatTimeout = 30 * time.Second
	conf.LeaderLeaseTimeout = 30 * time.Second
	conf.CommitTimeout = time.Second

	cfg := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "F", Address: addr},
		{Suffrage: Voter, ID: "A", Address: "A"},
		{Suffrage: Voter, ID: "B", Address: "B"},
	}}
	if err := BootstrapCluster(conf, store, store, snaps, trans, cfg); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	r, err := NewRaft(conf, &fsFSM{}, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("new raft: %v", err)
	}
	defer func() { _ = r.Shutdown().Error() }()
	leader := trans.EncodePeer("A", "A")

	fsEmit(t, map[string]interface{}{
		"event":    "cd_case_fsync_term_writes",
		"case":     "fsync_term_writes",
		"attempts": attempts,
		"mode":     "file_write_plus_fsync",
	})

	inversions := 0
	for i := 0; i < attempts; i++ {
		cur := r.CurrentTerm()
		last := r.LastIndex()

		hbDone := make(chan struct{})
		go func(term uint64) {
			defer close(hbDone)
			rpc := RPC{Command: &AppendEntriesRequest{RPCHeader: r.getRPCHeader(), Term: term, Leader: leader},
				RespChan: make(chan RPCResponse, 1)}
			r.processHeartbeat(rpc)
		}(cur + 1)

		req := &AppendEntriesRequest{RPCHeader: r.getRPCHeader(), Term: cur + 2, Leader: leader,
			PrevLogEntry: last, LeaderCommitIndex: last + 1,
			Entries: []*Log{{Index: last + 1, Term: cur + 2, Type: LogCommand, Data: []byte("x")}}}
		if last == 0 {
			req.PrevLogTerm = 0
		} else {
			var prev Log
			if err := r.logs.GetLog(last, &prev); err == nil {
				req.PrevLogTerm = prev.Term
			}
		}
		resp := &AppendEntriesResponse{}
		if err := trans.AppendEntries("A", addr, req, resp); err != nil {
			t.Fatalf("appendEntries: %v", err)
		}
		<-hbDone
		if r.CurrentTerm() < cur+2 {
			inversions++
		}
		time.Sleep(time.Millisecond)
	}
	mean, max, writes := store.stats()
	fsEmit(t, map[string]interface{}{
		"event":            "cd_result_fsync_term_writes",
		"case":             "fsync_term_writes",
		"attempts":         attempts,
		"inversion_count":  inversions,
		"term_writes":      writes,
		"mean_write_us":    int(mean / time.Microsecond),
		"max_write_us":     int(max / time.Microsecond),
	})
	t.Logf("attempts=%d inversions=%d writes=%d mean=%v max=%v", attempts, inversions, writes, mean, max)
}
