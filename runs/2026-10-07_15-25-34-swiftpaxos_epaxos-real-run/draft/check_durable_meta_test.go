package epaxos

import (
	"encoding/binary"
	"fmt"
	"io"
	"os"
	"testing"

	"github.com/imdea-software/swiftpaxos/replica"
)

// TestAssuranceDurableMetaBallotPersisted checks the obligation CLM-DURABLE-BAL:
// in a Durable replica the per-instance metadata record must carry bal as its own
// field, distinct from vbal. The harness calls the real recordInstanceMetadata on
// a fixed instance and reports the record bytes as CA_EVENT lines.
func TestAssuranceDurableMetaBallotPersisted(t *testing.T) {
	const (
		caseId = "bal7_vbal2"
		wantBal = int32(7)
		wantVBal = int32(2)
	)

	pr, pw, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}

	base := &replica.Replica{N: 3, Id: 0, Durable: true, StableStore: pw}
	r := &Replica{Replica: base}
	inst := &Instance{
		bal:    wantBal,
		vbal:   wantVBal,
		Status: ACCEPTED,
		Seq:    5,
		Deps:   []int32{-1, -1, -1},
	}

	fmt.Printf("CA_EVENT {\"event\":\"durable_meta_case\",\"case\":%q,\"durable\":true,\"bal\":%d,\"vbal\":%d}\n", caseId, inst.bal, inst.vbal)

	r.recordInstanceMetadata(inst)
	pw.Close()
	data, rerr := io.ReadAll(pr)
	pr.Close()
	if rerr != nil {
		t.Fatalf("read: %v", rerr)
	}

	if len(data) < 9 {
		fmt.Printf("CA_EVENT {\"event\":\"durable_meta_record\",\"case\":%q,\"durable\":true,\"len\":%d,\"bal_persisted\":false}\n", caseId, len(data))
		t.Errorf("record too short: %d bytes", len(data))
		return
	}

	field0 := binary.LittleEndian.Uint32(data[0:4])
	status := int8(data[4])
	seq := binary.LittleEndian.Uint32(data[5:9])
	balPersisted := field0 == uint32(inst.bal)
	fmt.Printf("CA_EVENT {\"event\":\"durable_meta_record\",\"case\":%q,\"durable\":true,\"len\":%d,\"field0_4\":%d,\"status\":%d,\"seq\":%d,\"bal_persisted\":%t,\"field0_equals_vbal\":%t}\n",
		caseId, len(data), field0, status, seq, balPersisted, field0 == uint32(inst.vbal))

	if !balPersisted {
		t.Errorf("bal not persisted: first field is %d, expected bal %d (vbal is %d)", field0, inst.bal, inst.vbal)
	}
}
