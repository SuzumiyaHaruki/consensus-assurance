package raft

import (
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "os"
 "path/filepath"
 "testing"
)

func assurancePersistEmit(t *testing.T, fields map[string]interface{}) {
 t.Helper()
 b, err := json.Marshal(fields)
 if err != nil { t.Fatal(err) }
 fmt.Println("CA_EVENT " + string(b))
}

func assurancePersistError(err error) string {
 if err == nil { return "" }
 return err.Error()
}

type assurancePersistSink struct {
 *FileSnapshotSink
 t *testing.T
 op string
 writes int
 bytes int
 writeFailed bool
 closes int
 cancels int
}

func (s *assurancePersistSink) Write(p []byte) (int, error) {
 n, err := s.FileSnapshotSink.Write(p)
 s.writes++
 s.bytes += n
 if err != nil || n != len(p) { s.writeFailed = true }
 return n, err
}

func (s *assurancePersistSink) Cancel() error {
 s.cancels++
 return s.FileSnapshotSink.Cancel()
}

func (s *assurancePersistSink) Close() error {
 s.closes++
 // MockSnapshot reaches Close only after Encode returns without error.
 assurancePersistEmit(s.t, map[string]interface{}{
  "event":"encoding_completed", "op_id":s.op, "snapshot_id":s.ID(),
  "seq":1, "writes":s.writes, "bytes":s.bytes,
  "writes_ok":!s.writeFailed && s.writes > 0 && s.bytes > 0,
 })
 if s.closes != 1 || s.cancels != 0 || s.closed {
  s.t.Fatal("initial completion prerequisite not reached")
 }
 // Obstruct only metadata completion, after encoding has completed.
 metaPath := filepath.Join(s.dir, metaFilePath)
 if err := os.Remove(metaPath); err != nil { s.t.Fatal(err) }
 if err := os.Mkdir(metaPath, 0700); err != nil { s.t.Fatal(err) }
 info, err := os.Stat(metaPath)
 if err != nil || !info.IsDir() { s.t.Fatalf("metadata obstruction unavailable: %v", err) }
 closeErr := s.FileSnapshotSink.Close()
 var pe *os.PathError
 metadataOpenFailed := errors.As(closeErr, &pe) && pe.Op == "open" && pe.Path == metaPath
 _, finalErr := os.Stat(filepath.Join(s.store.path, s.ID()))
 _, tempErr := os.Stat(s.dir)
 assurancePersistEmit(s.t, map[string]interface{}{
  "event":"initial_close_returned", "op_id":s.op, "snapshot_id":s.ID(),
  "encoding_seq":1, "close_error":assurancePersistError(closeErr),
  "close_failed":closeErr != nil, "metadata_open_failed":metadataOpenFailed,
  "finalization_recorded":s.meta.Size == int64(s.bytes) && len(s.meta.CRC) > 0,
  "final_directory_missing":os.IsNotExist(finalErr), "temporary_directory_exists":tempErr == nil,
 })
 return closeErr
}

func TestAssuranceMockPersistPublicationResult(t *testing.T) {
 store, err := NewFileSnapshotStore(t.TempDir(), 3, io.Discard)
 if err != nil { t.Fatal(err) }
 // Empty configuration is used by the supplied file-store tests.
 _, trans := NewInmemTransport(NewInmemAddr())
 sink, err := store.Create(SnapshotVersionMax, 10, 3, Configuration{}, 0, trans)
 if err != nil { t.Fatal(err) }
 fs, ok := sink.(*FileSnapshotSink)
 if !ok { t.Fatal("unexpected sink implementation") }
 defer fs.stateFile.Close()
 before, err := store.List()
 if err != nil || len(before) != 0 { t.Fatalf("fresh store prerequisite failed: %v", err) }
 _, statErr := os.Stat(filepath.Join(store.path, sink.ID()))
 if !os.IsNotExist(statErr) { t.Fatalf("final path was not absent: %v", statErr) }
 wrapped := &assurancePersistSink{FileSnapshotSink:fs, t:t, op:"persist-1"}
 snapshot := &MockSnapshot{logs:[][]byte{[]byte("assurance-record")}, maxIndex:1}
 defer snapshot.Release()
 persistErr := snapshot.Persist(wrapped)
 if wrapped.closes != 1 || wrapped.cancels != 0 { t.Fatal("encoding/completion path not reached") }
 listed, listErr := store.List()
 listedID := false
 for _, meta := range listed { if meta.ID == sink.ID() { listedID = true } }
 _, reader, openErr := store.Open(sink.ID())
 if reader != nil {
  if err := reader.Close(); err != nil { t.Fatalf("reader cleanup failed: %v", err) }
 }
 assurancePersistEmit(t, map[string]interface{}{
  "event":"persist_publication_observed", "op_id":wrapped.op, "snapshot_id":sink.ID(),
  "persist_nil":persistErr == nil, "persist_error":assurancePersistError(persistErr),
  "list_ok":listErr == nil, "listed":listedID,
  "open_missing":os.IsNotExist(openErr), "open_error":assurancePersistError(openErr),
 })
 if listErr != nil { t.Fatalf("publication listing failed: %v", listErr) }
}
