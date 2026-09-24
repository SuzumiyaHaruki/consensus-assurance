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

func TestAssuranceNetworkResponsePrefixes(t *testing.T) {
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

	for cut := 0; cut <= len(encoded); cut++ {
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
		futureErr := f.Error()
		if err := <-peerDone; err != nil {
			pipeline.Close()
			t.Fatal(err)
		}
		errorText := ""
		if futureErr != nil {
			errorText = futureErr.Error()
		}
		event := map[string]interface{}{
			"event": "network_prefix_decoded", "operation_id": fmt.Sprintf("prefix-%d", cut),
			"prefix_bytes": cut, "full_bytes": len(encoded), "future_failed": futureErr != nil,
			"error_text": errorText, "raw_success": raw.Success, "raw_term": raw.Term,
			"raw_last_log": raw.LastLog, "completed": true,
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
