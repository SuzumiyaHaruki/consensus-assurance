package raft

import (
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "testing"
)

type assuranceTransport struct { Transport }
func (assuranceTransport) EncodePeer(_ ServerID, a ServerAddress) []byte { return []byte(a) }
func (assuranceTransport) DecodePeer(a []byte) ServerAddress { return ServerAddress(a) }

type assuranceFaultStore struct {
 *InmemStore
 armed bool
 deleted bool
 failed bool
 deleteMin uint64
 deleteMax uint64
}
func (s *assuranceFaultStore) DeleteRange(lo, hi uint64) error {
 err := s.InmemStore.DeleteRange(lo, hi)
 if err == nil { s.deleted = true; s.deleteMin = lo; s.deleteMax = hi }
 return err
}
func (s *assuranceFaultStore) StoreLogs(logs []*Log) error {
 if s.armed {
  s.failed = true
  return errors.New("assurance injected replacement write failure without rollback")
 }
 return s.InmemStore.StoreLogs(logs)
}
func assuranceEmit(t *testing.T, v map[string]interface{}) {
 t.Helper()
 b, err := json.Marshal(v)
 if err != nil { t.Fatal(err) }
 fmt.Println("CA_EVENT " + string(b))
}
func assuranceCall(t *testing.T, r *Raft, a *AppendEntriesRequest) *AppendEntriesResponse {
 t.Helper()
 ch := make(chan RPCResponse, 1)
 rpc := RPC{Command: a, RespChan: ch}
 if err := r.checkRPCHeader(rpc); err != nil { t.Fatalf("header rejected: %v", err) }
 r.appendEntries(rpc, a)
 select {
 case result := <-ch:
  if result.Error != nil { t.Fatalf("RPC error: %v", result.Error) }
  response, ok := result.Response.(*AppendEntriesResponse)
  if !ok { t.Fatalf("unexpected response type %T", result.Response) }
  return response
 default:
  t.Fatal("handler returned without its response")
  return nil
 }
}
func TestAssurancePredecessorIntegrity(t *testing.T) {
 for _, scenario := range []string{"deleted_endpoint", "retained_predecessor"} {
  t.Run(scenario, func(t *testing.T) {
   store := &assuranceFaultStore{InmemStore: NewInmemStore()}
   for index := uint64(1); index <= 3; index++ {
    if err := store.InmemStore.StoreLog(&Log{Index: index, Term: 1, Type: LogNoop}); err != nil { t.Fatal(err) }
   }
   conf := Config{ProtocolVersion: 3, LocalID: ServerID("receiver"), LogOutput: io.Discard}
   r := &Raft{logs: store, stable: store.InmemStore, trans: assuranceTransport{}, localID: conf.LocalID, localAddr: ServerAddress("receiver"), protocolVersion: conf.ProtocolVersion, logger: conf.getOrCreateLogger(), leaderAddr: ServerAddress("sender"), leaderID: ServerID("sender")}
   r.conf.Store(conf)
   r.raftState.setState(Follower)
   r.setCurrentTerm(2)
   r.setLastLog(3, 1)
   r.setCommitIndex(1)
   r.setLastApplied(1)
   for index := uint64(1); index <= 3; index++ {
    var entry Log
    if err := store.InmemStore.GetLog(index, &entry); err != nil || entry.Index != index || entry.Term != 1 { t.Fatalf("initial storage mismatch at %d: %v", index, err) }
   }
   initialIndex, initialTerm := r.getLastLog()
   if initialIndex != 3 || initialTerm != 1 { t.Fatal("initial metadata mismatch") }
   header := RPCHeader{ProtocolVersion: 3, ID: []byte("sender"), Addr: []byte("sender")}
   first := &AppendEntriesRequest{RPCHeader: header, Term: 2, PrevLogEntry: 1, PrevLogTerm: 1, Entries: []*Log{{Index: 2, Term: 2, Type: LogNoop}, {Index: 3, Term: 2, Type: LogNoop}}, LeaderCommitIndex: 0}
   store.armed = true
   firstResponse := assuranceCall(t, r, first)
   if !store.deleted || store.deleteMin != 2 || store.deleteMax != 3 || !store.failed || firstResponse.Success { t.Fatal("required deletion/error prehistory was not reached") }
   var retained Log
   if err := store.InmemStore.GetLog(1, &retained); err != nil || retained.Term != 1 { t.Fatal("retained prefix missing") }
   for _, index := range []uint64{2, 3} {
    var entry Log
    if err := store.InmemStore.GetLog(index, &entry); !errors.Is(err, ErrLogNotFound) { t.Fatalf("deleted entry %d lookup: %v", index, err) }
   }
   prev := uint64(3)
   if scenario == "retained_predecessor" { prev = 1 }
   second := &AppendEntriesRequest{RPCHeader: header, Term: 2, PrevLogEntry: prev, PrevLogTerm: 1, LeaderCommitIndex: 0}
   if err := r.checkRPCHeader(RPC{Command: second}); err != nil { t.Fatal(err) }
   var predecessor Log
   lookupErr := store.InmemStore.GetLog(second.PrevLogEntry, &predecessor)
   if lookupErr != nil && !errors.Is(lookupErr, ErrLogNotFound) { t.Fatal(lookupErr) }
   snapshotIndex, snapshotTerm := r.getLastSnapshot()
   cachedIndex, cachedTerm := r.getLastLog()
   represented := (lookupErr == nil && predecessor.Index == second.PrevLogEntry && predecessor.Term == second.PrevLogTerm) || (snapshotIndex == second.PrevLogEntry && snapshotTerm == second.PrevLogTerm)
   if snapshotIndex != 0 || r.getCommitIndex() != 1 { t.Fatal("snapshot or commit prerequisite differs") }
   op := "predecessor-" + scenario
   assuranceEmit(t, map[string]interface{}{"event":"predecessor_input", "operation_id":op, "scenario":scenario, "first_success":firstResponse.Success, "delete_completed":store.deleted, "delete_min":store.deleteMin, "delete_max":store.deleteMax, "write_failed":store.failed, "prev_index":second.PrevLogEntry, "prev_term":second.PrevLogTerm, "request_term":second.Term, "entry_count":len(second.Entries), "leader_commit":second.LeaderCommitIndex, "represented":represented, "lookup_missing":errors.Is(lookupErr, ErrLogNotFound), "snapshot_index":snapshotIndex, "snapshot_term":snapshotTerm, "cached_index":cachedIndex, "cached_term":cachedTerm})
   response := assuranceCall(t, r, second)
   var finalEntry Log
   finalErr := store.InmemStore.GetLog(second.PrevLogEntry, &finalEntry)
   if finalErr != nil && !errors.Is(finalErr, ErrLogNotFound) { t.Fatal(finalErr) }
   finalSnapshotIndex, finalSnapshotTerm := r.getLastSnapshot()
   finalCachedIndex, finalCachedTerm := r.getLastLog()
   assuranceEmit(t, map[string]interface{}{"event":"predecessor_result", "operation_id":op, "scenario":scenario, "completed":true, "success":response.Success, "response_term":response.Term, "lookup_missing":errors.Is(finalErr, ErrLogNotFound), "stored_index":finalEntry.Index, "stored_term":finalEntry.Term, "snapshot_index":finalSnapshotIndex, "snapshot_term":finalSnapshotTerm, "cached_index":finalCachedIndex, "cached_term":finalCachedTerm, "commit_index":r.getCommitIndex()})
   if scenario == "retained_predecessor" && (!represented || !response.Success) { t.Error("retained matching predecessor control did not succeed") }
  })
 }
}
