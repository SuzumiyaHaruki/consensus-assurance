package raft

import (
 "encoding/json"
 "errors"
 "fmt"
 "sync"
 "testing"
 "time"
)

func assurancePipelineEvent(v map[string]interface{}) {
 b, err := json.Marshal(v)
 if err != nil { panic(err) }
 fmt.Println("CA_EVENT " + string(b))
}

type assurancePipelineFuture struct {
 id string
 req *AppendEntriesRequest
 resp *AppendEntriesResponse
 err error
 start time.Time
 errorReturned bool
 stop chan struct{}
 stopOnce sync.Once
}

func (f *assurancePipelineFuture) Error() error {
 f.errorReturned = true
 return f.err
}
func (f *assurancePipelineFuture) Start() time.Time { return f.start }
func (f *assurancePipelineFuture) Request() *AppendEntriesRequest { return f.req }
func (f *assurancePipelineFuture) Response() *AppendEntriesResponse {
 assurancePipelineEvent(map[string]interface{}{
  "event": "response_access", "operation_id": f.id,
  "error_returned": f.errorReturned, "failed": f.err != nil,
 })
 // Stop only after the current decoder iteration has handled this response.
 f.stopOnce.Do(func() { close(f.stop) })
 return f.resp
}

type assurancePipeline struct { ready chan AppendFuture }
func (p *assurancePipeline) Consumer() <-chan AppendFuture { return p.ready }
func (p *assurancePipeline) AppendEntries(*AppendEntriesRequest, *AppendEntriesResponse) (AppendFuture, error) {
 return nil, errors.New("unused harness submission method")
}
func (p *assurancePipeline) Close() error { return nil }

func TestAssurancePipelineResponseValidity(t *testing.T) {
 cases := []struct { name string; failed bool; success bool }{
  {"successful_completion", false, true},
  {"failed_completion_false_response", true, false},
  {"failed_completion_true_response", true, true},
 }
 for _, tc := range cases {
  t.Run(tc.name, func(t *testing.T) {
   stop := make(chan struct{})
   finish := make(chan struct{})
   c := newCommitment(make(chan struct{}, 1), Configuration{Servers: []Server{
    {ID: ServerID("leader"), Address: ServerAddress("leader"), Suffrage: Voter},
    {ID: ServerID("follower"), Address: ServerAddress("follower"), Suffrage: Voter},
    {ID: ServerID("other"), Address: ServerAddress("other"), Suffrage: Voter},
   }}, 1)
   s := &followerReplication{
    currentTerm: 3, nextIndex: 1,
    peer: Server{ID: ServerID("follower"), Address: ServerAddress("follower"), Suffrage: Voter},
    commitment: c, notify: make(map[*verifyFuture]struct{}),
    stepDown: make(chan struct{}, 1),
   }
   f := &assurancePipelineFuture{
    id: tc.name, start: time.Now(), stop: stop,
    req: &AppendEntriesRequest{Term: 3, Entries: []*Log{{Index: 1, Term: 3, Type: LogCommand, Data: []byte("command")}}},
    resp: &AppendEntriesResponse{Term: 3, Success: tc.success},
   }
   if tc.failed { f.err = errors.New("controlled completed RPC failure") }
   c.Lock()
   initialMatch := c.matchIndexes[ServerID("follower")]
   c.Unlock()
   assurancePipelineEvent(map[string]interface{}{
    "event": "completed_input", "operation_id": f.id,
    "failed": f.err != nil, "response_success": f.resp.Success,
    "initial_match": initialMatch, "request_index": f.req.Entries[0].Index,
   })
   p := &assurancePipeline{ready: make(chan AppendFuture, 1)}
   p.ready <- f
   r := &Raft{noLegacyTelemetry: true}
   go r.pipelineDecode(s, p, stop, finish)
   select {
   case <-finish:
   case <-time.After(5 * time.Second):
    f.stopOnce.Do(func() { close(stop) })
    t.Fatal("pipeline decoder did not reach its stopping boundary")
   }
   c.Lock()
   finalMatch := c.matchIndexes[ServerID("follower")]
   c.Unlock()
   assurancePipelineEvent(map[string]interface{}{
    "event": "decoder_result", "operation_id": f.id,
    "failed": f.err != nil, "match_index": finalMatch,
    "error_returned": f.errorReturned,
   })
  })
 }
}
