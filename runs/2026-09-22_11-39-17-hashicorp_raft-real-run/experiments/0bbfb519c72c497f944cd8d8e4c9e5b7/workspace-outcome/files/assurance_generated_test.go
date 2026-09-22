package raft

import (
 "encoding/json"
 "fmt"
 "io"
 "os"
 "path/filepath"
 "testing"
)

// Only peer encoding is used by this store-only experiment.
type assuranceSnapshotTransport struct { Transport }
func (assuranceSnapshotTransport) EncodePeer(_ ServerID, address ServerAddress) []byte {
 return []byte(address)
}

func TestAssuranceSnapshotRepeatedClosePublication(t *testing.T) {
 emit := func(event map[string]interface{}) {
  t.Helper()
  b, err := json.Marshal(event)
  if err != nil { t.Fatal(err) }
  fmt.Println("CA_EVENT " + string(b))
 }
 errorText := func(err error) string {
  if err == nil { return "" }
  return err.Error()
 }
 store, err := NewFileSnapshotStore(t.TempDir(), 1, io.Discard)
 if err != nil { t.Fatalf("create store: %v", err) }
 configuration := Configuration{Servers: []Server{{Suffrage: Voter, ID: ServerID("node-1"), Address: ServerAddress("local-1")}}}
 configurationErr := checkConfiguration(configuration)
 if configurationErr != nil { t.Fatal(configurationErr) }
 raw, createErr := store.Create(1, 10, 2, configuration, 1, assuranceSnapshotTransport{})
 if createErr != nil { t.Fatalf("create snapshot: %v", createErr) }
 sink, ok := raw.(*FileSnapshotSink)
 if !ok { t.Fatal("unexpected sink implementation") }
 defer sink.stateFile.Close()
 id := sink.ID()
 op := "snapshot-operation-1"
 payload := []byte("snapshot-state")
 n, writeErr := sink.Write(payload)
 emit(map[string]interface{}{"event":"snapshot_write", "operation_id":op, "snapshot_id":id, "written":n, "requested":len(payload), "error":errorText(writeErr)})
 if writeErr != nil || n != len(payload) { t.Fatalf("write prerequisite: n=%d err=%v", n, writeErr) }
 // Inject a resource failure without changing Close, finalize, or Open.
 injectionErr := sink.stateFile.Close()
 if injectionErr != nil { t.Fatalf("fault injection: %v", injectionErr) }
 firstErr := sink.Close()
 _, firstStatErr := os.Stat(filepath.Join(store.path, id))
 firstMissing := os.IsNotExist(firstStatErr)
 emit(map[string]interface{}{"event":"first_close", "operation_id":op, "snapshot_id":id, "success":firstErr == nil, "error":errorText(firstErr), "published_directory_missing":firstMissing, "stat_error":errorText(firstStatErr)})
 if firstErr == nil || !firstMissing { t.Fatal("pre-publication failure prerequisite was not reached") }
 secondErr := sink.Close()
 emit(map[string]interface{}{"event":"second_close", "operation_id":op, "snapshot_id":id, "success":secondErr == nil, "error":errorText(secondErr), "observed_first_error":errorText(firstErr)})
 meta, reader, openErr := store.Open(id)
 _, finalStatErr := os.Stat(filepath.Join(store.path, id))
 metaID := ""
 if meta != nil { metaID = meta.ID }
 emit(map[string]interface{}{
  "event":"snapshot_open", "operation_id":op, "snapshot_id":id,
  "open_success":openErr == nil && reader != nil,
  "open_error":errorText(openErr), "open_not_exist":os.IsNotExist(openErr),
  "returned_meta_id":metaID, "second_close_success":secondErr == nil,
  "published_directory_missing":os.IsNotExist(finalStatErr), "stat_error":errorText(finalStatErr),
  "create_success":createErr == nil, "configuration_valid":configurationErr == nil,
  "write_success":writeErr == nil && n == len(payload),
  "injection_success":injectionErr == nil,
  "first_close_failed":firstErr != nil, "first_publication_missing":firstMissing,
  "sync_enabled":!store.noSync && !sink.noSync,
  "snapshot_version":int(sink.meta.Version), "retention":store.retain,
  "configuration_index_valid":sink.meta.ConfigurationIndex <= sink.meta.Index,
 })
 if reader != nil {
  if err := reader.Close(); err != nil { t.Fatalf("reader cleanup: %v", err) }
 }
}
