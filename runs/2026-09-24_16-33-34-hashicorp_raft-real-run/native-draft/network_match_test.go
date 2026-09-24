package raft

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"net"
	"testing"
	"time"

	"github.com/hashicorp/go-msgpack/v2/codec"
)

type assuranceNetworkDelivery struct {
	AppendPipeline
	ready chan AppendFuture
}

func (p *assuranceNetworkDelivery) Consumer() <-chan AppendFuture { return p.ready }
func assuranceNetworkEvent(t *testing.T, e map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(e)
	if err != nil {
		t.Fatal(err)
	}
	fmt.Println("CA_EVENT " + string(b))
}
func TestAssuranceNetworkFailedFutureMatch(t *testing.T) {
	// Use the same encoder settings and envelope order as handleConn/handleCommand.
	var wire bytes.Buffer
	enc := codec.NewEncoder(&wire, &codec.MsgpackHandle{BasicHandle: codec.BasicHandle{TimeNotBuiltin: true}})
	if err := enc.Encode(""); err != nil {
		t.Fatal(err)
	}
	reply := &AppendEntriesResponse{RPCHeader: RPCHeader{ProtocolVersion: 3}, Term: 4, LastLog: 2, Success: true}
	if err := enc.Encode(reply); err != nil {
		t.Fatal(err)
	}
	encoded := append([]byte(nil), wire.Bytes()...)

	for _, cut := range []int{0, len(encoded) - 1, len(encoded)} {
		left, right := net.Pipe()
		conn := &netConn{
			conn: left,
			w:    bufio.NewWriter(left),
			dec:  codec.NewDecoder(bufio.NewReader(left), &codec.MsgpackHandle{}),
		}
		conn.enc = codec.NewEncoder(conn.w, &codec.MsgpackHandle{BasicHandle: codec.BasicHandle{TimeNotBuiltin: true}})
		pipeline := newNetPipeline(&NetworkTransport{timeout: time.Second}, conn, 2)
		peerDone := make(chan error, 1)
		prefix := encoded[:cut]
		go func() {
			defer right.Close()
			_ = right.SetDeadline(time.Now().Add(2 * time.Second))
			reader := bufio.NewReader(right)
			typ, err := reader.ReadByte()
			if err != nil {
				peerDone <- err
				return
			}
			if typ != rpcAppendEntries {
				peerDone <- fmt.Errorf("unexpected RPC type: %d", typ)
				return
			}
			var req AppendEntriesRequest
			if err := codec.NewDecoder(reader, &codec.MsgpackHandle{}).Decode(&req); err != nil {
				peerDone <- err
				return
			}
			if req.Term != 4 || len(req.Entries) != 1 || req.Entries[0].Index != 2 {
				peerDone <- fmt.Errorf("unexpected request identity")
				return
			}
			if len(prefix) > 0 {
				if _, err := right.Write(prefix); err != nil {
					peerDone <- err
					return
				}
			}
			peerDone <- nil
		}()
		req := &AppendEntriesRequest{Term: 4, Entries: []*Log{{Index: 2, Term: 4, Type: LogNoop}}}
		// Retain the caller-owned response allocation to inspect partial decoder writes.
		raw := new(AppendEntriesResponse)
		f, err := pipeline.AppendEntries(req, raw)
		if err != nil {
			pipeline.Close()
			t.Fatal(err)
		}
		select {
		case ready := <-pipeline.Consumer():
			if ready != f {
				pipeline.Close()
				t.Fatal("future identity changed")
			}
		case <-time.After(3 * time.Second):
			pipeline.Close()
			t.Fatal("network pipeline did not complete")
		}
		config := Configuration{Servers: []Server{{ID: "sender", Suffrage: Voter}, {ID: "peer", Suffrage: Voter}}}
		c := newCommitment(make(chan struct{}, 1), config, 1)
		s := &followerReplication{peer: Server{ID: "peer", Suffrage: Voter}, commitment: c, notify: make(map[*verifyFuture]struct{})}
		c.Lock()
		beforeMatch := c.matchIndexes["peer"]
		c.Unlock()
		op := fmt.Sprintf("prefix-%d", cut)
		assuranceNetworkEvent(t, map[string]interface{}{
			"event": "network_future_ready", "operation_id": op, "published": true,
			"before_match": beforeMatch, "prefix_bytes": cut, "full_bytes": len(encoded),
		})
		// This rejection is only a stopping input, not a measured network response.
		stopper := &appendFuture{args: &AppendEntriesRequest{Term: 4}, resp: &AppendEntriesResponse{Term: 4, Success: false}, start: time.Now()}
		stopper.init()
		stopper.respond(nil)
		delivery := &assuranceNetworkDelivery{AppendPipeline: pipeline, ready: make(chan AppendFuture, 2)}
		delivery.ready <- f
		delivery.ready <- stopper
		stop := make(chan struct{})
		finish := make(chan struct{})
		r := &Raft{noLegacyTelemetry: true}
		go r.pipelineDecode(s, delivery, stop, finish)
		select {
		case <-finish:
		case <-time.After(3 * time.Second):
			close(stop)
			pipeline.Close()
			t.Fatal("consumer did not finish")
		}
		// The independent error status is inspected after consumer completion.
		futureErr := f.Error()
		c.Lock()
		afterMatch := c.matchIndexes["peer"]
		c.Unlock()
		if err := <-peerDone; err != nil {
			pipeline.Close()
			t.Fatal(err)
		}
		errorText := ""
		if futureErr != nil {
			errorText = futureErr.Error()
		}
		event := map[string]interface{}{
			"event": "network_consumer_completed", "operation_id": fmt.Sprintf("prefix-%d", cut),
			"prefix_bytes": cut, "full_bytes": len(encoded), "future_failed": futureErr != nil,
			"error_text": errorText, "raw_success": raw.Success, "raw_term": raw.Term,
			"raw_last_log": raw.LastLog, "completed": true, "peer_match": afterMatch, "commit_index": c.getCommitIndex(),
		}
		b, err := json.Marshal(event)
		if err != nil {
			pipeline.Close()
			t.Fatal(err)
		}
		fmt.Println("CA_EVENT " + string(b))
		pipeline.Close()
	}
}
