package epaxos

import (
	"bufio"
	"bytes"
	"encoding/binary"
	"fmt"
	"sync"
	"testing"

	"github.com/imdea-software/swiftpaxos/replica/defs"
	"github.com/imdea-software/swiftpaxos/state"
)

func TestAuditValueLengthBoundary(t *testing.T) {
	for _, n := range []int{65535, 65536, 65537} {
		t.Run(fmt.Sprint(n), func(t *testing.T) {
			original := state.Value(bytes.Repeat([]byte{0x41}, n))
			var wire bytes.Buffer
			original.Marshal(&wire)
			var decoded state.Value
			if err := decoded.Unmarshal(&wire); err != nil {
				t.Fatal(err)
			}
			t.Logf("input=%d decoded=%d unconsumed=%d", n, len(decoded), wire.Len())
			if !bytes.Equal(decoded, original) || wire.Len() != 0 {
				t.Error("Value round trip silently truncates and leaves payload in stream")
			}
		})
	}
}

func TestAuditScanReplyLengthOverflow(t *testing.T) {
	r, _ := auditReplica(0)
	for k := state.Key(10); k <= 11; k++ {
		cmd := state.Command{Op: state.PUT, K: k, V: state.Value(bytes.Repeat([]byte{0x41}, 32768))}
		// Each write individually survives the production command codec.
		var wire bytes.Buffer
		cmd.Marshal(&wire)
		var decoded state.Command
		if err := decoded.Unmarshal(&wire); err != nil {
			t.Fatal(err)
		}
		if len(decoded.V) != 32768 || wire.Len() != 0 {
			t.Fatal("write fixture did not round trip")
		}
		decoded.Execute(r.State)
	}
	count := make([]byte, 8)
	binary.LittleEndian.PutUint64(count, 1)
	scan := state.Command{Op: state.SCAN, K: 10, V: count}
	expected := scan.Execute(r.State)
	if len(expected) != 65536 {
		t.Fatalf("bad fixture: expected full scan size, got %d", len(expected))
	}
	var replyWire bytes.Buffer
	proposal := &defs.GPropose{Propose: &defs.Propose{CommandId: 7, Command: scan, Timestamp: 123}, Reply: bufio.NewWriter(&replyWire), Mutex: new(sync.Mutex)}
	inst := r.newInstance(0, 0, []state.Command{scan}, 0, 0, COMMITTED, 0, []int32{-1, -1, -1})
	inst.lb = r.newLeaderBookkeepingDefault()
	inst.lb.clientProposals = []*defs.GPropose{proposal}
	r.InstanceSpace[0][0] = inst
	if !r.exec.executeCommand(0, 0) {
		t.Fatal("scan failed to execute")
	}
	reply := new(defs.ProposeReplyTS)
	if err := reply.Unmarshal(&replyWire); err != nil {
		t.Fatal(err)
	}
	t.Logf("executed scan bytes=%d; client decoded OK=%d command=%d bytes=%d timestamp=%d remaining-stream-bytes=%d", len(expected), reply.OK, reply.CommandId, len(reply.Value), reply.Timestamp, replyWire.Len())
	if !bytes.Equal(reply.Value, expected) || reply.Timestamp != 123 || replyWire.Len() != 0 {
		t.Error("successful scan reply lost its result and corrupted framing")
	}
}
