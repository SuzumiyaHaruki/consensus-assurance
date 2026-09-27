package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"testing"
	"time"
)

func assuranceOrderEvent(v map[string]interface{}) {
	raw, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	fmt.Println("CA_EVENT " + string(raw))
}

type assuranceOrderFuture struct {
	AppendFuture
	mu                  sync.Mutex
	errorReturned       bool
	responseCalled      bool
	errorBeforeResponse bool
	seen                chan struct{}
}

func (f *assuranceOrderFuture) Error() error {
	err := f.AppendFuture.Error()
	f.mu.Lock()
	f.errorReturned = true
	f.mu.Unlock()
	return err
}
func (f *assuranceOrderFuture) Response() *AppendEntriesResponse {
	f.mu.Lock()
	if !f.responseCalled {
		f.responseCalled = true
		f.errorBeforeResponse = f.errorReturned
		close(f.seen)
	}
	f.mu.Unlock()
	return f.AppendFuture.Response()
}

type assuranceOrderPipeline struct {
	AppendPipeline
	ready chan AppendFuture
}

func (p *assuranceOrderPipeline) Consumer() <-chan AppendFuture { return p.ready }

func TestAssurancePipelineResponseOrder(t *testing.T) {
	for _, scenario := range []string{"decoder_timeout", "decoder_success", "permitted_control"} {
		t.Run(scenario, func(t *testing.T) {
			_, sender := NewInmemTransportWithTimeout("order-sender", 100*time.Millisecond)
			_, receiver := NewInmemTransportWithTimeout("order-receiver", 100*time.Millisecond)
			defer sender.Close()
			defer receiver.Close()
			sender.Connect(receiver.LocalAddr(), receiver)
			if scenario != "decoder_timeout" {
				conf := DefaultConfig()
				conf.LocalID = "order-receiver"
				conf.LogOutput = io.Discard
				store := NewInmemStore()
				node, err := NewRaft(conf, &MockFSM{}, store, store, NewInmemSnapshotStore(), receiver)
				if err != nil {
					t.Fatal(err)
				}
				defer func() {
					if err := node.Shutdown().Error(); err != nil {
						t.Error(err)
					}
				}()
			}
			pipeline, err := sender.AppendEntriesPipeline("order-receiver", receiver.LocalAddr())
			if err != nil {
				t.Fatal(err)
			}
			defer pipeline.Close()
			req := &AppendEntriesRequest{RPCHeader: RPCHeader{ProtocolVersion: ProtocolVersionMax, ID: []byte("order-sender"), Addr: []byte("order-sender")}, Term: 1}
			responseStorage := new(AppendEntriesResponse)
			original, err := pipeline.AppendEntries(req, responseStorage)
			if err != nil {
				t.Fatal(err)
			}
			var ready AppendFuture
			select {
			case ready = <-pipeline.Consumer():
			case <-time.After(3 * time.Second):
				t.Fatal("producer did not publish future")
			}
			if ready != original || ready.Request() != req {
				t.Fatal("future/request association changed")
			}
			observed := &assuranceOrderFuture{AppendFuture: ready, seen: make(chan struct{})}
			assuranceOrderEvent(map[string]interface{}{"event": "order_admitted", "operation": scenario, "consumer": scenario, "producer": "inmemPipeline", "same_future": ready == original})
			if scenario == "permitted_control" {
				if err := observed.Error(); err != nil {
					t.Fatal(err)
				}
				if !observed.Response().Success {
					t.Fatal("real follower did not accept control request")
				}
			} else {
				proxy := &assuranceOrderPipeline{AppendPipeline: pipeline, ready: make(chan AppendFuture, 1)}
				proxy.ready <- observed
				// Only the decoder is exercised. Empty requests cannot add log match support.
				consumer := &Raft{noLegacyTelemetry: true}
				state := &followerReplication{peer: Server{ID: "order-receiver", Address: receiver.LocalAddr()}, notify: make(map[*verifyFuture]struct{})}
				stop, finish := make(chan struct{}), make(chan struct{})
				go consumer.pipelineDecode(state, proxy, stop, finish)
				select {
				case <-observed.seen:
				case <-finish:
				case <-time.After(3 * time.Second):
					close(stop)
					t.Fatal("decoder did not complete or access response")
				}
				close(stop)
				select {
				case <-finish:
				case <-time.After(3 * time.Second):
					t.Fatal("decoder did not stop")
				}
			}
			observed.mu.Lock()
			called, before := observed.responseCalled, observed.errorBeforeResponse
			observed.mu.Unlock()
			// Read completion status only after the measured consumer has stopped.
			finalErr := ready.Error()
			finalResponse := responseStorage
			assuranceOrderEvent(map[string]interface{}{"event": "order_result", "operation": scenario, "consumer": scenario, "response_accessed": called, "error_returned_before_response": before, "rpc_error": fmt.Sprint(finalErr), "response_success": finalResponse.Success, "completed": true})
		})
	}
}
