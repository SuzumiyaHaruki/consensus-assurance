package raft

import (
	"io"
	"testing"
	"time"
)

type zzFSM struct{}

func (f *zzFSM) Apply(l *Log) interface{}       { return nil }
func (f *zzFSM) Snapshot() (FSMSnapshot, error) { return &zzSnap{}, nil }
func (f *zzFSM) Restore(r io.ReadCloser) error { r.Close(); return nil }

type zzSnap struct{}

func (s *zzSnap) Persist(sink SnapshotSink) error { return sink.Close() }
func (s *zzSnap) Release()                        {}

func TestZZApplyFutureShutdownEscape(t *testing.T) {
	conf := inmemConfig(t)
	conf.BatchApplyCh = true
	conf.MaxAppendEntries = 4
	conf.skipStartup = true
	conf.LocalID = "n1"
	_, trans := NewInmemTransport("n1")
	r, err := NewRaft(conf, &zzFSM{}, NewInmemStore(), NewInmemStore(), NewInmemSnapshotStore(), trans)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}
	future := r.Apply([]byte("x"), 0)
	lf, ok := future.(*logFuture)
	if !ok {
		t.Fatalf("unexpected future type %T", future)
	}
	r.Shutdown()
	time.Sleep(20 * time.Millisecond)
	responded := false
	select {
	case <-lf.errCh:
		responded = true
	default:
	}
	t.Logf("responded_after_shutdown=%v shutdown_escape=%v errCh_nil=%v", responded, lf.ShutdownCh != nil, lf.errCh == nil)
}
