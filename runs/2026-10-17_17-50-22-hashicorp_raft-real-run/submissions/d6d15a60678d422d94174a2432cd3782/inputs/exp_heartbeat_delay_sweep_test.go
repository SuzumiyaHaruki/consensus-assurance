package raft

// Construction notes:
//   * Same follower setup and race as the two-point jitter probe, but the stable
//     store's current-term write is delayed by a uniform interval drawn from
//     [0, maxDelay), and the harness sweeps maxDelay instead of testing a single
//     value: 0, 250 us, 500 us, 1 ms and 2 ms, 200 attempts each.
//   * Each attempt issues one fast-path heartbeat carrying cur+1 concurrently
//     with a term cur+2 AppendEntries through the real consumer path, then
//     records whether the persisted term ended below cur+2.
//   * The point is the shape of the rate against store latency, which the
//     target's own divergence note ties to heartbeat concurrency.

import (
	"encoding/json"
	"fmt"
	"io"
	"math/rand"
	"sync"
	"testing"
	"time"

	hclog "github.com/hashicorp/go-hclog"
)

type sweepStore struct {
	*InmemStore
	mu       sync.Mutex
	maxDelay time.Duration
	rnd      *rand.Rand
}

func newSweepStore(maxDelay time.Duration) *sweepStore {
	return &sweepStore{InmemStore: NewInmemStore(), maxDelay: maxDelay, rnd: rand.New(rand.NewSource(11))}
}

func (s *sweepStore) SetUint64(key []byte, val uint64) error {
	if string(key) == string(keyCurrentTerm) && s.maxDelay > 0 {
		s.mu.Lock()
		d := time.Duration(s.rnd.Int63n(int64(s.maxDelay)))
		s.mu.Unlock()
		time.Sleep(d)
	}
	return s.InmemStore.SetUint64(key, val)
}

type sweepFSM struct{ mu sync.Mutex }

func (f *sweepFSM) Apply(*Log) interface{}         { return nil }
func (f *sweepFSM) Snapshot() (FSMSnapshot, error) { return &sweepSnapshot{}, nil }
func (f *sweepFSM) Restore(io.ReadCloser) error    { return nil }

type sweepSnapshot struct{}

func (s *sweepSnapshot) Persist(SnapshotSink) error { return nil }
func (s *sweepSnapshot) Release()                  {}

func swEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

func sweepAttempts(t *testing.T, name string, maxDelay time.Duration, attempts int) int {
	t.Helper()
	store := newSweepStore(maxDelay)
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("S")
	trans.Connect(addr, trans)

	conf := DefaultConfig()
	conf.LocalID = "S"
	conf.Logger = hclog.NewNullLogger()
	conf.LogLevel = "ERROR"
	conf.ElectionTimeout = 30 * time.Second
	conf.HeartbeatTimeout = 30 * time.Second
	conf.LeaderLeaseTimeout = 30 * time.Second
	conf.CommitTimeout = time.Second

	cfg := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "S", Address: addr},
		{Suffrage: Voter, ID: "A", Address: "A"},
		{Suffrage: Voter, ID: "B", Address: "B"},
	}}
	if err := BootstrapCluster(conf, store, store, snaps, trans, cfg); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	r, err := NewRaft(conf, &sweepFSM{}, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("new raft: %v", err)
	}
	defer func() { _ = r.Shutdown().Error() }()
	leader := trans.EncodePeer("A", "A")

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

	swEmit(t, map[string]interface{}{
		"event":        "sw_case_" + name,
		"case":         name,
		"attempts":     attempts,
		"max_delay_us": int(maxDelay / time.Microsecond),
	})
	swEmit(t, map[string]interface{}{
		"event":           "sw_result_" + name,
		"case":            name,
		"attempts":        attempts,
		"max_delay_us":    int(maxDelay / time.Microsecond),
		"inversion_count": inversions,
	})
	return inversions
}

func TestAssuranceHeartbeatDelaySweep(t *testing.T) {
	t.Run("delay_0us", func(t *testing.T) {
		sweepAttempts(t, "delay_0us", 0, 200)
	})
	t.Run("delay_250us", func(t *testing.T) {
		sweepAttempts(t, "delay_250us", 250*time.Microsecond, 200)
	})
	t.Run("delay_500us", func(t *testing.T) {
		sweepAttempts(t, "delay_500us", 500*time.Microsecond, 200)
	})
	t.Run("delay_1000us", func(t *testing.T) {
		sweepAttempts(t, "delay_1000us", time.Millisecond, 200)
	})
	t.Run("delay_2000us", func(t *testing.T) {
		sweepAttempts(t, "delay_2000us", 2*time.Millisecond, 200)
	})
}
