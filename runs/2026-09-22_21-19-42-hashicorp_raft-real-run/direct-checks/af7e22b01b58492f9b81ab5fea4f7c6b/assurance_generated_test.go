package raft

import (
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "testing"
)

type assuranceIdentityTransport struct { Transport }
func (*assuranceIdentityTransport) EncodePeer(_ ServerID, a ServerAddress) []byte { return []byte(a) }
func (*assuranceIdentityTransport) DecodePeer(a []byte) ServerAddress { return ServerAddress(a) }

type assuranceIdentityStore struct {
 *InmemStore
 t *testing.T
 emit func(string, map[string]interface{}) int
 initialSeq, deleteSeq, failureSeq int
 armed bool
}
func (s *assuranceIdentityStore) DeleteRange(lo, hi uint64) error {
 err := s.InmemStore.DeleteRange(lo, hi)
 if err != nil { return err }
 for i := lo; i <= hi; i++ {
  var l Log
  if err := s.InmemStore.GetLog(i, &l); err != ErrLogNotFound { s.t.Fatalf("deletion inspection at %d: %v", i, err) }
 }
 s.deleteSeq = s.emit("suffix_deleted", map[string]interface{}{"initial_seq":s.initialSeq, "min":lo, "max":hi, "removed":true})
 return nil
}
func (s *assuranceIdentityStore) StoreLogs(logs []*Log) error {
 if !s.armed { return s.InmemStore.StoreLogs(logs) }
 if s.deleteSeq == 0 { s.t.Fatal("replacement fault reached without deletion") }
 err := errors.New("assurance controlled replacement failure without writes")
 s.failureSeq = s.emit("replacement_failed", map[string]interface{}{"delete_seq":s.deleteSeq, "error":err.Error(), "writes":0, "count":len(logs)})
 return err
}

func TestAssuranceAppendFailureRetainedIdentity(t *testing.T) {
 seq := 0
 emit := func(event string, fields map[string]interface{}) int {
  seq++
  fields["event"] = event
  fields["op"] = "append-conflict-1"
  fields["seq"] = seq
  b, err := json.Marshal(fields)
  if err != nil { t.Fatal(err) }
  fmt.Println("CA_EVENT " + string(b))
  return seq
 }
 base := NewInmemStore()
 initial := []*Log{{Index:1, Term:1, Type:LogNoop}, {Index:2, Term:2, Type:LogNoop}, {Index:3, Term:2, Type:LogNoop}}
 if err := base.StoreLogs(initial); err != nil { t.Fatal(err) }
 store := &assuranceIdentityStore{InmemStore:base, t:t, emit:emit}
 conf := DefaultConfig()
 conf.LocalID = "follower"
 conf.LogOutput = io.Discard
 if err := ValidateConfig(conf); err != nil { t.Fatal(err) }
 snaps := NewInmemSnapshotStore()
 r := &Raft{logs:store, stable:NewInmemStore(), snapshots:snaps, trans:&assuranceIdentityTransport{}, localID:conf.LocalID, localAddr:"follower", logger:conf.getOrCreateLogger()}
 r.conf.Store(*conf)
 r.setState(Follower)
 r.setCurrentTerm(3)
 r.setLastLog(3, 2)
 r.setCommitIndex(1)
 r.setLastSnapshot(0, 0)
 idx, err := base.LastIndex()
 if err != nil { t.Fatal(err) }
 var terminal Log
 if err := base.GetLog(idx, &terminal); err != nil { t.Fatal(err) }
 ci, ct := r.getLastEntry()
 if ci != terminal.Index || ct != terminal.Term { t.Fatal("initial cache differs from retained log") }
 metas, err := snaps.List()
 if err != nil || len(metas) != 0 { t.Fatalf("initial snapshots: %v, %v", metas, err) }
 store.initialSeq = emit("initial_consistent", map[string]interface{}{"consistent":true, "index":ci, "term":ct, "commit_index":r.getCommitIndex(), "snapshot_count":len(metas)})
 store.armed = true
 req := &AppendEntriesRequest{RPCHeader:RPCHeader{ProtocolVersion:conf.ProtocolVersion, ID:[]byte("leader"), Addr:[]byte("leader")}, Term:3, PrevLogEntry:1, PrevLogTerm:1, Entries:[]*Log{{Index:2, Term:3, Type:LogNoop}, {Index:3, Term:3, Type:LogNoop}}, LeaderCommitIndex:1}
 responses := make(chan RPCResponse, 1)
 rpc := RPC{Command:req, RespChan:responses}
 if err := r.checkRPCHeader(rpc); err != nil { t.Fatal(err) }
 r.appendEntries(rpc, req)
 var rr RPCResponse
 select { case rr = <-responses: default: t.Fatal("handler returned without response") }
 resp, ok := rr.Response.(*AppendEntriesResponse)
 if !ok { t.Fatalf("unexpected response type %T", rr.Response) }
 if store.failureSeq == 0 { t.Fatal("replacement failure prerequisite missing") }
 idx, err = base.LastIndex()
 if err != nil { t.Fatal(err) }
 var retained Log
 if idx != 0 { if err := base.GetLog(idx, &retained); err != nil { t.Fatal(err) } }
 for i := uint64(2); i <= 3; i++ {
  var l Log
  if err := base.GetLog(i, &l); err != ErrLogNotFound { t.Fatalf("replacement unexpectedly retained at %d: %v", i, err) }
 }
 metas, err = snaps.List()
 if err != nil { t.Fatal(err) }
 expectedIndex, expectedTerm := retained.Index, retained.Term
 for _, meta := range metas {
  if meta.Index > expectedIndex { expectedIndex, expectedTerm = meta.Index, meta.Term }
 }
 rpcError := ""
 if rr.Error != nil { rpcError = rr.Error.Error() }
 retainedSeq := emit("retained_inspected", map[string]interface{}{"failure_seq":store.failureSeq, "handler_returned":true, "success":resp.Success, "rpc_error":rpcError, "identity":fmt.Sprintf("%d/%d", expectedIndex, expectedTerm), "retained_index":retained.Index, "retained_term":retained.Term, "snapshot_count":len(metas)})
 actualIndex, actualTerm := r.getLastEntry()
 emit("terminal_identity_observed", map[string]interface{}{"retained_seq":retainedSeq, "identity":fmt.Sprintf("%d/%d", actualIndex, actualTerm), "index":actualIndex, "term":actualTerm})
}
