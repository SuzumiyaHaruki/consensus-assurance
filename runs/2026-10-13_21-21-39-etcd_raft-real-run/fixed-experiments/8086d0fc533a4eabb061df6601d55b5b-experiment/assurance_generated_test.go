package raft

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"testing"

	"go.etcd.io/raft/v3/quorum"
	pb "go.etcd.io/raft/v3/raftpb"
)

// caEvent emits a single machine-parsable event line.
func caEvent(t *testing.T, v map[string]any) {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal event: %v", err)
	}
	fmt.Println("CA_EVENT " + string(b))
}

func caEnc(v uint64) []byte {
	b := make([]byte, 8)
	binary.LittleEndian.PutUint64(b, v)
	return b
}

func caVoters3() quorum.JointConfig {
	return quorum.JointConfig{
		quorum.MajorityConfig{1: struct{}{}, 2: struct{}{}, 3: struct{}{}},
		nil,
	}
}

// TestAssuranceReadOnlyOversizedAck drives readOnly.maybeAdvance with a quorum of
// ack values that the leader's heartbeatCtx never emitted for the live instance.
func TestAssuranceReadOnlyOversizedAck(t *testing.T) {
	ro := newReadOnly(ReadOnlySafe)
	ro.addRequest(7, &pb.Message{})
	ro.recvAck(1, ro.heartbeatCtx()) // leader self-ack: position 1
	forged := uint64(1) << 40
	ro.recvAck(2, caEnc(forged))
	ro.recvAck(3, caEnc(forged))
	caEvent(t, map[string]any{
		"event":               "read_ack_setup",
		"alias":               "oversized",
		"read_requests":       1,
		"leader_ack_position": 1,
		"forged_ack_position": forged,
		"voters":              []uint64{1, 2, 3},
	})

	panicked := false
	var recovered string
	func() {
		defer func() {
			if r := recover(); r != nil {
				panicked = true
				recovered = fmt.Sprint(r)
			}
		}()
		_ = ro.maybeAdvance(caVoters3())
	}()

	ev := map[string]any{
		"event":    "read_ack_probe",
		"alias":    "oversized",
		"panicked": panicked,
	}
	if panicked {
		ev["panic"] = recovered
	} else {
		ev["confirmed_reads"] = ro.confirmedReads
	}
	caEvent(t, ev)
}

// TestAssuranceReadOnlyForgedAckConfirms admits two reads and supplies one acq
// value the leader never emitted, alongside the leader's own self-ack.
func TestAssuranceReadOnlyForgedAckConfirms(t *testing.T) {
	ro := newReadOnly(ReadOnlySafe)
	ro.addRequest(7, &pb.Message{})
	ro.addRequest(9, &pb.Message{})
	ro.recvAck(1, ro.heartbeatCtx()) // leader self-ack: position 2
	ro.recvAck(2, caEnc(1))          // honest peer: only the first heartbeat was seen
	ro.recvAck(3, caEnc(2))          // forged: this peer never saw a heartbeat with position 2
	caEvent(t, map[string]any{
		"event":                  "read_ack_setup",
		"alias":                  "forged",
		"read_requests":          2,
		"leader_ack_position":    2,
		"honest_ack_position":    1,
		"forged_ack_position":    2,
		"voters":                 []uint64{1, 2, 3},
	})

	adv := ro.maybeAdvance(caVoters3())
	caEvent(t, map[string]any{
		"event":           "read_ack_probe",
		"alias":           "forged",
		"advanced":        len(adv),
		"confirmed_reads": ro.confirmedReads,
	})
}
