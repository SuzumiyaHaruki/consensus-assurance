package epaxos

import (
	"encoding/binary"
	"fmt"
	"io"
	"os"
	"testing"

	"github.com/imdea-software/swiftpaxos/replica"
)

// TestAssuranceDurableMetaBallot observes the byte record that
// recordInstanceMetadata writes for an instance whose bal and vbal differ,
// using an os.Pipe as the StableStore so no filesystem is touched.
func TestAssuranceDurableMetaBallot(t *testing.T) {
	pr, pw, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}

	base := &replica.Replica{N: 3, Id: 0, Durable: true, StableStore: pw}
	r := &Replica{Replica: base}

	inst := &Instance{
		bal:    7,
		vbal:   2,
		Status: ACCEPTED,
		Seq:    5,
		Deps:   []int32{-1, -1, -1},
	}

	r.recordInstanceMetadata(inst)
	pw.Close()
	data, rerr := io.ReadAll(pr)
	pr.Close()
	if rerr != nil {
		t.Fatalf("read: %v", rerr)
	}

	fmt.Printf("CA_EVENT {\"event\":\"record\",\"len\":%d}\n", len(data))
	if len(data) < 9 {
		fmt.Printf("CA_EVENT {\"event\":\"short_record\",\"len\":%d}\n", len(data))
		return
	}

	first := binary.LittleEndian.Uint32(data[0:4])
	status := int8(data[4])
	seq := binary.LittleEndian.Uint32(data[5:9])
	fmt.Printf("CA_EVENT {\"event\":\"fields\",\"wrote_bal\":%d,\"injected_bal\":%d,\"injected_vbal\":%d,\"field0_4\":%d,\"field_status\":%d,\"field_seq\":%d,\"bal_persisted\":%t,\"vbal_persisted_at_bal_slot\":%t}\n",
		first, inst.bal, inst.vbal, first, status, seq, first == uint32(inst.bal), first == uint32(inst.vbal))

	_ = status
}
