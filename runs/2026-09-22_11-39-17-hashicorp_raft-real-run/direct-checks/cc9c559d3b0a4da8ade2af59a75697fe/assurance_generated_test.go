package raft

import (
 "encoding/json"
 "fmt"
 "testing"
 "time"
)

func assuranceEmit(v map[string]interface{}) {
 b, err := json.Marshal(v)
 if err != nil { panic(err) }
 fmt.Println("CA_EVENT " + string(b))
}

type assuranceResponseBoundary struct{}

type assuranceObservedFuture struct {
 operation string
 req AppendEntriesRequest
 completionError error
 stop <-chan struct{}
 requestObserved bool
 errorReturned bool
 responseObserved bool
}

func (f *assuranceObservedFuture) Error() error {
 defer func() { f.errorReturned = true }()
 return f.completionError
}
func (f *assuranceObservedFuture) Start() time.Time { return time.Time{} }
func (f *assuranceObservedFuture) Request() *AppendEntriesRequest {
 f.requestObserved = true
 assuranceEmit(map[string]interface{}{
  "event": "future_received", "operation_id": f.operation,
  "required_error_returned": true,
 })
 return &f.req
}
func (f *assuranceObservedFuture) Response() *AppendEntriesResponse {
 f.responseObserved = true
 stopOpen := true
 select {
 case <-f.stop:
  stopOpen = false
 default:
 }
 assuranceEmit(map[string]interface{}{
  "event": "response_invoked", "operation_id": f.operation,
  "error_returned": f.errorReturned,
  "request_observed": f.requestObserved,
  "stop_open": stopOpen,
  "completion_error_nil": f.completionError == nil,
 })
 panic(assuranceResponseBoundary{})
}

type assuranceObservedPipeline struct { results chan AppendFuture }
func (p *assuranceObservedPipeline) AppendEntries(*AppendEntriesRequest, *AppendEntriesResponse) (AppendFuture, error) {
 panic("unexpected AppendEntries call outside this experiment endpoint")
}
func (p *assuranceObservedPipeline) Consumer() <-chan AppendFuture { return p.results }
func (p *assuranceObservedPipeline) Close() error { return nil }

func TestAssurancePipelineResponsePrecondition(t *testing.T) {
 stop := make(chan struct{})
 finish := make(chan struct{})
 f := &assuranceObservedFuture{operation: "pipeline-future-1", stop: stop}
 p := &assuranceObservedPipeline{results: make(chan AppendFuture, 1)}
 p.results <- f
 r := new(Raft)
 s := new(followerReplication)
 reachedBoundary := false
 func() {
  defer func() {
   if recovered := recover(); recovered != nil {
    if _, ok := recovered.(assuranceResponseBoundary); !ok { panic(recovered) }
    reachedBoundary = true
   }
  }()
  r.pipelineDecode(s, p, stop, finish)
 }()
 if !reachedBoundary || !f.responseObserved {
  t.Fatal("Response observation boundary was not reached")
 }
 select {
 case <-finish:
 default:
  t.Fatal("pipelineDecode did not unwind its finish notification")
 }
}
