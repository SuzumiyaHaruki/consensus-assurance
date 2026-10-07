package epaxos

// Exploration harness: a real protocol message carries a command array. With the first
// command's value beyond the two-byte length field, does the message still decode with the
// commands that were written? Only the implementation's own message and command codecs run.

import (
	"bytes"
	"encoding/json"
	"fmt"
	"testing"

	"github.com/imdea-software/swiftpaxos/state"
)

func mev(m map[string]any) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func TestAssuranceMessageCommandArrayShift(t *testing.T) {
	big := make([]byte, 70000)
	for i := range big {
		big[i] = byte((i * 7) % 251)
	}
	first := state.Command{Op: state.PUT, K: state.Key(11), V: state.Value(big)}
	second := state.Command{Op: state.PUT, K: state.Key(22), V: state.Value([]byte{9, 9, 9})}
	msg := &PreAccept{LeaderId: 1, Replica: 0, Instance: 0, Ballot: 1,
		Command: []state.Command{first, second}, Seq: 1, Deps: []int32{-1, -1, -1}}

	var buf bytes.Buffer
	msg.Marshal(&buf)
	mev(map[string]any{"event": "message_marshalled", "message": "PreAccept",
		"commands": len(msg.Command), "first_bytes": len(big), "second_key": int(second.K),
		"wire_bytes": buf.Len()})

	decoded := &PreAccept{}
	panicked := false
	panicValue := ""
	errText := ""
	func() {
		defer func() {
			if v := recover(); v != nil {
				panicked = true
				panicValue = fmt.Sprint(v)
			}
		}()
		if err := decoded.Unmarshal(&buf); err != nil {
			errText = err.Error()
		}
	}()
	if panicked {
		mev(map[string]any{"event": "message_shifted", "message": "PreAccept",
			"panicked": true, "panic_value": panicValue, "second_matches": false,
			"bytes_left": buf.Len()})
		return
	}
	if errText != "" {
		mev(map[string]any{"event": "message_shifted", "message": "PreAccept", "panicked": false,
			"error": errText, "second_matches": false})
		return
	}
	matches := len(decoded.Command) == 2
	if matches {
		got := decoded.Command[1]
		matches = got.Op == second.Op && got.K == second.K && len(got.V) == len(second.V)
	}
	secondOp := -1
	secondKey := int64(0)
	secondLen := -1
	if len(decoded.Command) > 1 {
		secondOp = int(decoded.Command[1].Op)
		secondKey = int64(decoded.Command[1].K)
		secondLen = len(decoded.Command[1].V)
	}
	mev(map[string]any{"event": "message_shifted", "message": "PreAccept",
		"commands_decoded": len(decoded.Command), "first_decoded_bytes": len(decoded.Command[0].V),
		"second_op": secondOp, "second_key": secondKey, "second_value_len": secondLen,
		"second_matches": matches, "panicked": false, "bytes_left": buf.Len()})
}
