package raft

import (
 "encoding/json"
 "errors"
 "fmt"
 "testing"
 "time"
)

func assuranceFutureEvent(v map[string]interface{}) {
 b, err := json.Marshal(v)
 if err != nil { panic(err) }
 fmt.Println("CA_EVENT " + string(b))
}

type assuranceObservedFuture struct {
 id string
 req AppendEntriesRequest
 resp AppendEntriesResponse
 err error
 started time.Time
 errorCalls int
 responseCalls int
 requestCalls int
 validated bool
}

func (f *assuranceObservedFuture) Error() error {
 f.errorCalls++
 f.validated = f.err == nil
 assuranceFutureEvent(map[string]interface{}{"event":"error_return", "operation_id":f.id, "error_nil":f.err == nil})
 return f.err
}
func (f *assuranceObservedFuture) Start() time.Time { return f.started }
func (f *assuranceObservedFuture) Request() *AppendEntriesRequest {
 f.requestCalls++
 assuranceFutureEvent(map[string]interface{}{"event":"request_access", "operation_id":f.id})
 return &f.req
}
func (f *assuranceObservedFuture) Response() *AppendEntriesResponse {
 f.responseCalls++
 assuranceFutureEvent(map[string]interface{}{"event":"response_access", "operation_id":f.id, "error_returned_nil_before_access":f.errorCalls > 0 && f.validated, "error_calls":f.errorCalls})
 return &f.resp
}

type assuranceObservedPipeline struct { ready chan AppendFuture }
func (p *assuranceObservedPipeline) Consumer() <-chan AppendFuture { return p.ready }
func (p *assuranceObservedPipeline) Close() error { return nil }
func (p *assuranceObservedPipeline) AppendEntries(*AppendEntriesRequest, *AppendEntriesResponse) (AppendFuture, error) {
 return nil, errors.New("unused fixture submission method")
}

func TestAssurancePipelineFutureResponseContract(t *testing.T) {
 cases := []struct { id string; err error; success bool }{
  {"completed_nil_error", nil, true},
  {"completed_non_nil_error", errors.New("controlled completed RPC error"), false},
 }
 for _, tc := range cases {
  t.Run(tc.id, func(t *testing.T) {
   f := &assuranceObservedFuture{id:tc.id, req:AppendEntriesRequest{Term:1}, resp:AppendEntriesResponse{Term:1, Success:tc.success}, err:tc.err, started:time.Now()}
   p := &assuranceObservedPipeline{ready:make(chan AppendFuture)}
   s := &followerReplication{currentTerm:1, nextIndex:1}
   r := &Raft{}
   stop := make(chan struct{})
   finish := make(chan struct{})
   assuranceFutureEvent(map[string]interface{}{"event":"input_ready", "operation_id":f.id, "completed":true, "error_nil":f.err == nil, "response_success":f.resp.Success, "entry_count":len(f.req.Entries)})
   go r.pipelineDecode(s, p, stop, finish)
   select {
   case p.ready <- f:
    assuranceFutureEvent(map[string]interface{}{"event":"future_delivered", "operation_id":f.id})
   case <-time.After(3*time.Second):
    close(stop)
    t.Fatal("future delivery timeout; prerequisite unresolved")
   }
   // The unbuffered send establishes selection of this future. Stopping
   // depends on that handoff, independently of Response or Error calls.
   close(stop)
   select {
   case <-finish:
   case <-time.After(3*time.Second):
    t.Fatal("decoder completion timeout; result incomplete")
   }
   assuranceFutureEvent(map[string]interface{}{"event":"decoder_completed", "operation_id":f.id, "error_calls":f.errorCalls, "request_calls":f.requestCalls, "response_calls":f.responseCalls, "next_index":s.nextIndex, "last_contact_set":!s.lastContact.IsZero()})
   if f.errorCalls == 0 && f.requestCalls == 0 && f.responseCalls == 0 {
    t.Fatal("no observed future processing; result unresolved")
   }
  })
 }
}
