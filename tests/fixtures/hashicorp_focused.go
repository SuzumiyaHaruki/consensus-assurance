package raft

import (
    "bytes"
    "fmt"
    "encoding/json"
    "testing"
    "github.com/hashicorp/go-hclog"
)

type assuranceStore struct {
    *InmemStore
    failKey string
    observe func()
}
func (s *assuranceStore) Set(k, v []byte) error {
    if string(k) == s.failKey { return fmt.Errorf("injected write failure") }
    err := s.InmemStore.Set(k, v)
    if s.observe != nil { s.observe() }
    return err
}
func (s *assuranceStore) SetUint64(k []byte, v uint64) error {
    if string(k) == s.failKey { return fmt.Errorf("injected write failure") }
    err := s.InmemStore.SetUint64(k, v)
    if s.observe != nil { s.observe() }
    return err
}
func assuranceNode(t *testing.T, s *assuranceStore) *Raft {
    t.Helper()
    cfg := DefaultConfig()
    cfg.LocalID = "voter"
    cfg.Logger = hclog.NewNullLogger()
    cfg.skipStartup = true
    _, trans := NewInmemTransport("voter")
    r, err := NewRaft(cfg, &MockFSM{}, s, s, NewInmemSnapshotStore(), trans)
    if err != nil { t.Fatal(err) }
    t.Cleanup(func(){ trans.Close() })
    return r
}
func assuranceVote(t *testing.T, r *Raft, term uint64, cand string) bool {
    t.Helper()
    ch := make(chan RPCResponse, 1)
    req := &RequestVoteRequest{Term: term, Candidate: []byte(cand)}
    r.requestVote(RPC{Command: req, RespChan: ch}, req)
    result := <-ch
    if result.Error != nil { t.Fatal(result.Error) }
    return result.Response.(*RequestVoteResponse).Granted
}
func TestAssuranceVoteSurvivesRecovery(t *testing.T) {
    store := &assuranceStore{InmemStore: NewInmemStore()}
    r := assuranceNode(t, store)
    if !assuranceVote(t, r, 1, "a") { t.Fatal("first vote rejected") }
    r = assuranceNode(t, store)
    if assuranceVote(t, r, 1, "b") { t.Fatal("conflicting vote granted after reconstruction") }
    if !assuranceVote(t, r, 1, "a") { t.Fatal("same-candidate retry rejected") }
}
func TestAssurancePartialWriteAndRetry(t *testing.T) {
    for _, key := range []string{string(keyLastVoteTerm), string(keyLastVoteCand)} {
        t.Run(key, func(t *testing.T) {
            store := &assuranceStore{InmemStore: NewInmemStore(), failKey:key}
            r := assuranceNode(t, store)
            if assuranceVote(t, r, 1, "a") { t.Fatal("vote granted despite storage failure") }
            store.failKey = ""
            r = assuranceNode(t, store)
            if !assuranceVote(t, r, 1, "b") { t.Fatal("retry rejected with no prior granted vote") }
            if assuranceVote(t, r, 1, "a") { t.Fatal("conflicting retry granted") }
        })
    }
}
func TestAssuranceOldCandidatePartialNewTerm(t *testing.T) {
    store := &assuranceStore{InmemStore: NewInmemStore()}
    r := assuranceNode(t, store)
    if !assuranceVote(t, r, 1, "a") { t.Fatal("first vote rejected") }
    store.failKey = string(keyLastVoteCand)
    if assuranceVote(t, r, 2, "b") { t.Fatal("failed second write granted a vote") }
    store.failKey = ""
    r = assuranceNode(t, store)
    if assuranceVote(t, r, 2, "b") { t.Fatal("conflicting old durable candidate accepted") }
    if !assuranceVote(t, r, 2, "a") { t.Fatal("durable candidate retry rejected") }
    got, _ := store.Get(keyLastVoteCand)
    if !bytes.Equal(got, []byte("a")) { t.Fatal("unexpected durable candidate") }
}

// This is an explicit development regression, not an autonomous analysis result.
func TestAssuranceTrace(t *testing.T) {
    store := &assuranceStore{InmemStore: NewInmemStore()}
    r := assuranceNode(t, store)
    grantA, grantB := false, false
    observe := func(event string) {
        current, _ := store.GetUint64(keyCurrentTerm)
        voteTerm, _ := store.GetUint64(keyLastVoteTerm)
        candidate, _ := store.Get(keyLastVoteCand)
        candidateID := 0
        if bytes.Equal(candidate, []byte("a")) { candidateID = 1 }
        if bytes.Equal(candidate, []byte("b")) { candidateID = 2 }
        record := map[string]interface{}{"event":event, "state":map[string]interface{}{
            "current":current, "voteTerm":voteTerm, "voteCand":candidateID,
            "grantA":grantA, "grantB":grantB}}
        data, err := json.Marshal(record)
        if err != nil { t.Fatal(err) }
        fmt.Println("CA_EVENT " + string(data))
    }
    observe("initial")
    store.observe = func(){ observe("write_completed") }
    grantA = assuranceVote(t, r, 1, "a")
    observe("vote_response")
    r = assuranceNode(t, store)
    observe("reconstructed")
    grantB = assuranceVote(t, r, 1, "b")
    observe("vote_response")
    if !grantA || grantB { t.Fatal("unexpected same-term vote responses") }
}
