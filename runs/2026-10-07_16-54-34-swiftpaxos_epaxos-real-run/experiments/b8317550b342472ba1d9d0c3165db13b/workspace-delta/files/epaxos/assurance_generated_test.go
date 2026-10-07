package epaxos

// Exploration harness: the wire form of a command carries its value length in a two-byte
// field. The client's command size is configurable, so values larger than that field allow
// are constructible. The harness marshals a large value through the real Command codec and
// reports what the decoder recovers.

import (
	"bytes"
	"encoding/json"
	"fmt"
	"testing"

	"github.com/imdea-software/swiftpaxos/state"
)

func lev(m map[string]any) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func TestAssuranceCommandValueLengthRoundTrip(t *testing.T) {
	payload := make([]byte, 70000)
	for i := range payload {
		payload[i] = byte(i % 251)
	}
	cmd := state.Command{Op: state.PUT, K: state.Key(1), V: state.Value(payload)}
	lev(map[string]any{"event": "value_marshalled", "subject": "value", "declared_bytes": len(payload),
		"op": int(cmd.Op), "key": int(cmd.K)})

	var buf bytes.Buffer
	cmd.Marshal(&buf)
	wire := buf.Bytes()
	lev(map[string]any{"event": "value_wire_length", "wire_bytes": len(wire)})

	decoded := state.Command{}
	if err := decoded.Unmarshal(&buf); err != nil {
		lev(map[string]any{"event": "value_roundtrip", "error": err.Error()})
		return
	}
	same := len(decoded.V) == len(payload)
	if same {
		for i := range payload {
			if decoded.V[i] != payload[i] {
				same = false
				break
			}
		}
	}
	lev(map[string]any{"event": "value_roundtrip", "subject": "value", "declared_bytes": len(payload),
		"decoded_bytes": len(decoded.V), "decoded_op": int(decoded.Op), "decoded_key": int(decoded.K),
		"value_matches": same, "wire_bytes_consumed": len(wire) - buf.Len()})
}

func TestAssuranceCommandStreamShift(t *testing.T) {
	big := make([]byte, 70000)
	for i := range big {
		big[i] = byte(i % 251)
	}
	first := state.Command{Op: state.PUT, K: state.Key(1), V: state.Value(big)}
	second := state.Command{Op: state.PUT, K: state.Key(2), V: state.Value([]byte{9, 9, 9})}

	var buf bytes.Buffer
	first.Marshal(&buf)
	second.Marshal(&buf)
	lev(map[string]any{"event": "stream_marshalled", "stream": "batch", "first_bytes": len(big),
		"second_key": int(second.K), "second_value_len": len(second.V), "wire_bytes": buf.Len()})

	decodedFirst := state.Command{}
	if err := decodedFirst.Unmarshal(&buf); err != nil {
		lev(map[string]any{"event": "stream_shifted", "error": "first: " + err.Error()})
		return
	}
	decodedSecond := state.Command{}
	err := decodedSecond.Unmarshal(&buf)
	errText := ""
	if err != nil {
		errText = err.Error()
	}
	matches := err == nil && decodedSecond.Op == second.Op && decodedSecond.K == second.K &&
		len(decodedSecond.V) == len(second.V)
	lev(map[string]any{"event": "stream_shifted", "stream": "batch",
		"first_decoded_bytes": len(decodedFirst.V),
		"second_op": int(decodedSecond.Op), "second_key": int(decodedSecond.K),
		"second_value_len": len(decodedSecond.V), "second_matches": matches,
		"error": errText, "bytes_left": buf.Len()})
}
