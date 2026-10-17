package raft

// Construction notes:
//   * Same follower setup as the forced-ordering probe, but no ordering hook:
//     the stable store optionally sleeps a random interval before persisting the
//     current term, modelling write latency jitter. Each attempt issues one
//     fast-path heartbeat carrying cur+1 concurrently with a term cur+2
//     AppendEntries through the real consumer path, then records whether the
//     persisted term ended below cur+2 (an inversion).

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

type jitterStore struct {
	*InmemStore
	mu       sync.Mutex
	maxDelay time.Duration
	rnd      *rand.Rand
}

func newJitterStore(maxDelay time.Duration) *jitterStore {
	return &jitterStore{InmemStore: NewInmemStore(), maxDelay: maxDelay, rnd: rand.New(rand.NewSource(7))}
}

func (j *jitterStore) SetUint64(key []byte, val uint64) error {
	if string(key) == string(keyCurrentTerm) && j.maxDelay > 0 {
		j.mu.Lock()
		d := time.Duration(j.rnd.Int63n(int64(j.maxDelay)))
		j.mu.Unlock()
		time.Sleep(d)
	}
	return j.InmemStore.SetUint64(key, val)
}

type jitterFSM struct{ mu sync.Mutex }

func (f *jitterFSM) Apply(*Log) interface{}         { return nil }
func (f *jitterFSM) Snapshot() (FSMSnapshot, error) { return &jitterSnapshot{}, nil }
func (f *jitterFSM) Restore(io.ReadCloser) error    { return nil }

type jitterSnapshot struct{}

func (s *jitterSnapshot) Persist(SnapshotSink) error { return nil }
func (s *jitterSnapshot) Release()                   {}

func jEmit(t *testing.T, payload map[string]interface{}) {
	t.Helper()
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(data))
}

// jitterAttempts runs the concurrent term-write race attempts times and returns
// how many attempts ended with a persisted term below the higher request's term.
func jitterAttempts(t *testing.T, name string, maxDelay time.Duration, attempts int) (int, int) {
	t.Helper()
	store := newJitterStore(maxDelay)
	snaps := NewInmemSnapshotStore()
	addr, trans := NewInmemTransport("J")
	trans.Connect(addr, trans)

	conf := DefaultConfig()
	conf.LocalID = "J"
	conf.Logger = hclog.NewNullLogger()
	conf.LogLevel = "ERROR"
	conf.ElectionTimeout = 30 * time.Second
	conf.HeartbeatTimeout = 30 * time.Second
	conf.LeaderLeaseTimeout = 30 * time.Second
	conf.CommitTimeout = time.Second

	cfg := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: "J", Address: addr},
		{Suffrage: Voter, ID: "A", Address: "A"},
		{Suffrage: Voter, ID: "B", Address: "B"},
	}}
	if err := BootstrapCluster(conf, store, store, snaps, trans, cfg); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	r, err := NewRaft(conf, &jitterFSM{}, store, store, snaps, trans)
	if err != nil {
		t.Fatalf("new raft: %v", err)
	}
	defer func() { _ = r.Shutdown().Error() }()
	leader := trans.EncodePeer("A", "A")

	inversions := 0
	for i := 0; i < attempts; i++ {
		cur := r.CurrentTerm()
		last := r.LastIndex()

		// Fast-path heartbeat carrying an intermediate term, on its own goroutine.
		hbDone := make(chan struct{})
		go func(term uint64) {
			defer close(hbDone)
			rpc := RPC{Command: &AppendEntriesRequest{RPCHeader: r.getRPCHeader(), Term: term, Leader: leader},
				RespChan: make(chan RPCResponse, 1)}
			r.processHeartbeat(rpc)
		}(cur + 1)

		// Higher-term request through the consumer path.
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

	jEmit(t, map[string]interface{}{
		"event":        "jitter_case_" + name,
		"case":         name,
		"attempts":     attempts,
		"max_delay_ms": int(maxDelay / time.Millisecond),
		"final_term":   r.CurrentTerm(),
	})
	jEmit(t, map[string]interface{}{
		"event":           "jitter_result_" + name,
		"case":            name,
		"attempts":        attempts,
		"inversion_count": inversions,
	})
	return inversions, attempts
}

func TestAssuranceHeartbeatTermWriteJitter(t *testing.T) {
	t.Run("control_no_delay", func(t *testing.T) {
		jitterAttempts(t, "control_no_delay", 0, 200)
	})
	t.Run("trigger_jittered_writes", func(t *testing.T) {
		jitterAttempts(t, "trigger_jittered_writes", 2*time.Millisecond, 200)
	})
}
