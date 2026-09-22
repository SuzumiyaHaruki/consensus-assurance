package raft

import (
 "encoding/json"
 "errors"
 "fmt"
 "os"
 "path/filepath"
 "testing"
)

func assuranceEmit(t *testing.T, v map[string]interface{}) {
 t.Helper()
 b, err := json.Marshal(v)
 if err != nil { t.Fatal(err) }
 fmt.Println("CA_EVENT " + string(b))
}

func assuranceError(err error) string {
 if err == nil { return "" }
 return err.Error()
}

type assuranceObservedSink struct {
 *FileSnapshotSink
 t *testing.T
 attempt string
 calls int
 writeFailed bool
 cancelled bool
 fresh bool
}

func (s *assuranceObservedSink) Write(p []byte) (int, error) {
 n, err := s.FileSnapshotSink.Write(p)
 if err != nil || n != len(p) { s.writeFailed = true }
 return n, err
}

func (s *assuranceObservedSink) Cancel() error {
 s.cancelled = true
 return s.FileSnapshotSink.Cancel()
}

func (s *assuranceObservedSink) Close() error {
 s.calls++
 if s.calls != 1 { s.t.Fatal("unexpected repeated Close") }
 // Replace only temporary metadata with a directory to force os.Create failure.
 metaPath := filepath.Join(s.dir, metaFilePath)
 if err := os.Remove(metaPath); err != nil { s.t.Fatalf("fault setup remove: %v", err) }
 if err := os.Mkdir(metaPath, 0700); err != nil { s.t.Fatalf("fault setup mkdir: %v", err) }
 err := s.FileSnapshotSink.Close()
 var pe *os.PathError
 metadataFailure := errors.As(err, &pe) && pe.Path == metaPath && pe.Op == "open"
 _, statErr := os.Stat(filepath.Join(s.parentDir, s.ID()))
 assuranceEmit(s.t, map[string]interface{}{
  "event": "first_close_return", "attempt": s.attempt, "sink_id": s.ID(),
  "first_close": s.calls == 1, "fresh": s.fresh,
  "encoding_succeeded": !s.writeFailed && !s.cancelled,
  "close_error": err != nil, "close_error_text": assuranceError(err),
  "metadata_create_failure": metadataFailure,
  "final_path_absent": os.IsNotExist(statErr),
  "final_path_stat_error": assuranceError(statErr),
  "finalized_size": s.meta.Size,
 })
 return err
}

func TestAssuranceMockSnapshotPersistCompletionError(t *testing.T) {
 store, err := NewFileSnapshotStoreWithLogger(t.TempDir(), 1, newTestLogger(t))
 if err != nil { t.Fatalf("create store: %v", err) }
 _, trans := NewInmemTransport(NewInmemAddr())
 raw, err := store.Create(SnapshotVersionMax, 10, 3, Configuration{}, 0, trans)
 if err != nil { t.Fatalf("create sink: %v", err) }
 sink, ok := raw.(*FileSnapshotSink)
 if !ok { t.Fatal("unexpected sink implementation") }
 defer sink.stateFile.Close()
 finalPath := filepath.Join(store.path, sink.ID())
 _, initialErr := os.Stat(finalPath)
 if !os.IsNotExist(initialErr) { t.Fatalf("fresh final path prerequisite: %v", initialErr) }
 observed := &assuranceObservedSink{FileSnapshotSink: sink, t: t, attempt: "persist-1", fresh: true}
 snapshot := &MockSnapshot{logs: [][]byte{[]byte("captured-entry")}, maxIndex: 1}
 persistErr := snapshot.Persist(observed)
 listed, listErr := store.List()
 present := false
 for _, meta := range listed { if meta.ID == sink.ID() { present = true } }
 _, reader, openErr := store.Open(sink.ID())
 if reader != nil { defer reader.Close() }
 _, finalErr := os.Stat(finalPath)
 assuranceEmit(t, map[string]interface{}{
  "event": "persist_result", "attempt": observed.attempt, "sink_id": sink.ID(),
  "persist_error": persistErr != nil, "persist_error_text": assuranceError(persistErr),
  "close_calls": observed.calls, "cancelled": observed.cancelled,
  "list_error": listErr != nil, "list_error_text": assuranceError(listErr),
  "listed": present, "open_error": openErr != nil,
  "open_not_exist": os.IsNotExist(openErr), "open_error_text": assuranceError(openErr),
  "final_path_absent": os.IsNotExist(finalErr),
  "final_path_stat_error": assuranceError(finalErr),
 })
}
