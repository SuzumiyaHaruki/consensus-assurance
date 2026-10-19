package epaxos

import (
	"bytes"
	"io"
	"reflect"
	"testing"

	"github.com/imdea-software/swiftpaxos/replica/defs"
	"github.com/imdea-software/swiftpaxos/state"
)

// Round-trip every EPaxos RPC message through its wire codec. This does not
// modify the implementation; it exercises the codec in defs.go directly.
func TestAuditRPCCodecRoundTrip(t *testing.T) {
	cmds := []state.Command{{Op: state.PUT, K: 7, V: state.Value("abc")}}
	deps := []int32{3, 1, -1, 9, 2}
	cdeps := []int32{4, 2, 0, 8, 1}

	check := func(name string, in interface{ Marshal(io.Writer) }, out interface{ Unmarshal(io.Reader) error }) {
		t.Helper()
		var buf bytes.Buffer
		in.Marshal(&buf)
		raw := append([]byte(nil), buf.Bytes()...)
		if err := out.Unmarshal(bytes.NewBuffer(raw)); err != nil {
			t.Fatalf("%s: Unmarshal: %v", name, err)
		}
		if !reflect.DeepEqual(in, out) {
			t.Errorf("%s: round trip mismatch\n in=%#v\nout=%#v", name, in, out)
		}
	}

	check("Prepare",
		&Prepare{LeaderId: 1, Replica: 2, Instance: 3, Ballot: 4},
		&Prepare{})
	check("PrepareReply",
		&PrepareReply{AcceptorId: 1, Replica: 2, Instance: 3, Ballot: 4,
			VBallot: 5, Status: COMMITTED, Command: cmds, Seq: 6, Deps: deps},
		&PrepareReply{})
	check("PreAccept",
		&PreAccept{LeaderId: 1, Replica: 2, Instance: 3, Ballot: 4,
			Command: cmds, Seq: 6, Deps: deps},
		&PreAccept{})
	check("PreAcceptReply",
		&PreAcceptReply{Replica: 2, Instance: 3, Ballot: 4, VBallot: 5,
			Seq: 6, Deps: deps, CommittedDeps: cdeps, Status: PREACCEPTED},
		&PreAcceptReply{})
	check("Accept",
		&Accept{LeaderId: 1, Replica: 2, Instance: 3, Ballot: 4, Seq: 6, Deps: deps},
		&Accept{})
	check("AcceptReply",
		&AcceptReply{Replica: 2, Instance: 3, Ballot: 4},
		&AcceptReply{})
	check("Commit",
		&Commit{LeaderId: 1, Replica: 2, Instance: 3, Ballot: 4,
			Command: cmds, Seq: 6, Deps: deps},
		&Commit{})
	check("TryPreAccept",
		&TryPreAccept{LeaderId: 1, Replica: 2, Instance: 3, Ballot: 4,
			Command: cmds, Seq: 6, Deps: deps},
		&TryPreAccept{})
	check("TryPreAcceptReply",
		&TryPreAcceptReply{AcceptorId: 1, Replica: 2, Instance: 3, Ballot: 4,
			VBallot: 5, ConflictReplica: 6, ConflictInstance: 7, ConflictStatus: ACCEPTED},
		&TryPreAcceptReply{})
}

// The client's commandSize is configurable and unchecked.  state.Value writes
// a 16-bit length into a 4-byte field, so values over 65535 bytes are
// silently truncated.
func TestAuditLargeCommandRoundTrip(t *testing.T) {
	payload := bytes.Repeat([]byte{0x5a}, 70000)
	in := &state.Command{Op: state.PUT, K: 7, V: state.Value(payload)}
	var buf bytes.Buffer
	in.Marshal(&buf)
	out := &state.Command{}
	if err := out.Unmarshal(bytes.NewReader(buf.Bytes())); err != nil {
		t.Fatalf("Unmarshal: %v", err)
	}
	t.Logf("input value length=%d decoded value length=%d (stream=%d)",
		len(in.V), len(out.V), buf.Len())
	if len(out.V) != len(in.V) || !bytes.Equal([]byte(out.V), payload) {
		t.Errorf("large command value was truncated: got %d bytes, want %d", len(out.V), len(in.V))
	}
}

// The same truncation inside a real Propose message should desynchronize the
// following Timestamp field as well.
func TestAuditLargeProposeRoundTrip(t *testing.T) {
	payload := bytes.Repeat([]byte{0x5a}, 70000)
	in := &defs.Propose{
		CommandId: 7,
		ClientId:  8,
		Command:   state.Command{Op: state.PUT, K: 1, V: state.Value(payload)},
		Timestamp: 123456789,
	}
	var buf bytes.Buffer
	in.Marshal(&buf)
	out := &defs.Propose{}
	if err := out.Unmarshal(bytes.NewReader(buf.Bytes())); err != nil {
		t.Fatalf("Unmarshal: %v", err)
	}
	t.Logf("timestamp in=%d out=%d value length in=%d out=%d stream=%d",
		in.Timestamp, out.Timestamp, len(in.Command.V), len(out.Command.V), buf.Len())
	if out.Timestamp != in.Timestamp || len(out.Command.V) != len(in.Command.V) {
		t.Errorf("large Propose desynchronized: timestamp %d -> %d, value length %d -> %d",
			in.Timestamp, out.Timestamp, len(in.Command.V), len(out.Command.V))
	}
}
