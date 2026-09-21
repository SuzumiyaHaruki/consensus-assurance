package paxos

import (
	"bufio"
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	base "github.com/imdea-software/swiftpaxos/replica"
	fastrpc "github.com/imdea-software/swiftpaxos/rpc"
	"github.com/imdea-software/swiftpaxos/state"
	"testing"
)

func assayEvent(kind, variant string, values map[string]interface{}) {
	payload := map[string]interface{}{"event": kind, "operation": "commit-17-" + variant, "participant": "0-to-1", "context": "ballot-43", "metadata": map[string]interface{}{"variant": variant, "legal": true}, "state": values}
	raw, _ := json.Marshal(payload)
	fmt.Println("CA_EVENT " + string(raw))
}

func TestAssuranceCommitWire(t *testing.T) {
	command := []state.Command{{Op: state.PUT, K: 7, V: state.Value("abc")}}
	for _, variant := range []string{"full", "short", "actual"} {
		var wire bytes.Buffer
		baseReplica := &base.Replica{N: 2, Id: 0, Alive: []bool{false, true}, PreferredPeerOrder: []int32{1, 0}, PeerWriters: []*bufio.Writer{nil, bufio.NewWriter(&wire)}, RPC: fastrpc.NewTableId(30)}
		replica := &Replica{Replica: baseReplica}
		replica.commitRPC = baseReplica.RPC.Register(new(Commit), make(chan fastrpc.Serializable, 1))
		replica.commitShortRPC = baseReplica.RPC.Register(new(CommitShort), make(chan fastrpc.Serializable, 1))
		switch variant {
		case "full":
			replica.SendMsg(1, replica.commitRPC, &Commit{LeaderId: 0, Instance: 17, Ballot: 43, Command: command})
		case "short":
			replica.SendMsg(1, replica.commitShortRPC, &CommitShort{LeaderId: 0, Instance: 17, Ballot: 43, Count: int32(len(command))})
		case "actual":
			replica.bcastCommit(17, 43, command)
		}
		replica.SendMsg(1, replica.commitRPC, &Commit{LeaderId: 0, Instance: 18, Ballot: 44, Command: command})
		data := wire.Bytes()
		assayEvent("sent", variant, map[string]interface{}{"ballot": 43, "next_code": int(replica.commitRPC), "wire_hex": hex.EncodeToString(data)})
		reader := bytes.NewReader(data)
		code, _ := reader.ReadByte()
		pair, registered := baseReplica.RPC.Get(code)
		if !registered {
			t.Fatalf("unregistered first code %d", code)
		}
		obj := pair.Obj.New()
		before := reader.Len()
		err := obj.Unmarshal(reader)
		consumed := before - reader.Len()
		nextCode, nextError := reader.ReadByte()
		decodedBallot := int32(-1)
		switch decoded := obj.(type) {
		case *Commit:
			decodedBallot = decoded.Ballot
		case *CommitShort:
			decodedBallot = decoded.Ballot
		}
		values := map[string]interface{}{"code": int(code), "ballot": int(decodedBallot), "consumed": consumed, "next_code": int(nextCode), "remaining": reader.Len(), "decoder_error": fmt.Sprint(err), "next_error": fmt.Sprint(nextError)}
		assayEvent("decoded", variant, values)
		if err != nil || nextError != nil {
			t.Errorf("%s decoder: %v; next code: %v", variant, err, nextError)
		}
		if variant != "actual" && (decodedBallot != 43 || nextCode != replica.commitRPC) {
			t.Errorf("%s control did not preserve its input ballot and following code", variant)
		}
	}
}
