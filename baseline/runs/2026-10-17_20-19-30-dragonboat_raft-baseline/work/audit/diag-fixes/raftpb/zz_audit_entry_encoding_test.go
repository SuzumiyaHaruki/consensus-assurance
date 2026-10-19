//go:build dragonboat_audit

// Audit-only property test of the hand-written colfer entry encoding used for
// raft log entries and messages.

package raftpb

import (
	"bytes"
	"math/rand"
	"testing"
)

func auditEntriesEqual(a, b Entry) bool {
	return a.Term == b.Term &&
		a.Index == b.Index &&
		a.Type == b.Type &&
		a.Key == b.Key &&
		a.ClientID == b.ClientID &&
		a.SeriesID == b.SeriesID &&
		a.RespondedTo == b.RespondedTo &&
		bytes.Equal(a.Cmd, b.Cmd)
}

func TestAuditEntryEncodingProperties(t *testing.T) {
	vals := []uint64{
		0, 1, 2, 127, 128, 255, 256, 16383, 16384, 1<<21 - 1, 1 << 21,
		1<<32 - 1, 1 << 32, 1<<49 - 1, 1 << 49, 1<<63 + 1, ^uint64(0),
	}
	rng := rand.New(rand.NewSource(20261017))
	for i := 0; i < 20000; i++ {
		cmd := make([]byte, rng.Intn(96))
		rng.Read(cmd)
		e := Entry{
			Term:        vals[rng.Intn(len(vals))],
			Index:       vals[rng.Intn(len(vals))],
			Type:        EntryType(rng.Intn(4)),
			Key:         vals[rng.Intn(len(vals))],
			ClientID:    vals[rng.Intn(len(vals))],
			SeriesID:    vals[rng.Intn(len(vals))],
			RespondedTo: vals[rng.Intn(len(vals))],
			Cmd:         cmd,
		}
		sz := e.Size()
		upper := e.SizeUpperLimit()
		if sz > upper {
			t.Fatalf("Size %d > SizeUpperLimit %d for %+v", sz, upper, e)
		}
		buf := make([]byte, upper)
		n, err := e.MarshalTo(buf)
		if err != nil {
			t.Fatalf("MarshalTo failed: %v, entry %+v", err, e)
		}
		if n != sz {
			t.Fatalf("MarshalTo wrote %d bytes, Size() reported %d, entry %+v", n, sz, e)
		}
		var got Entry
		if err := got.Unmarshal(buf[:n]); err != nil {
			t.Fatalf("Unmarshal failed: %v, entry %+v", err, e)
		}
		if !auditEntriesEqual(e, got) {
			t.Fatalf("round trip mismatch:\nwant %+v\ngot  %+v", e, got)
		}
		m, err := e.Marshal()
		if err != nil {
			t.Fatalf("Marshal failed: %v", err)
		}
		if !bytes.Equal(m, buf[:n]) {
			t.Fatalf("Marshal() and MarshalTo produced different encodings")
		}
	}
}
