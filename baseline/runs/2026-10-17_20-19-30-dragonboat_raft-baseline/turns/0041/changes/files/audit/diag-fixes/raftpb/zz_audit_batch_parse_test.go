//go:build dragonboat_audit

// Audit-only check of MessageBatch.Unmarshal on malformed input. The batch
// header is parsed from untrusted network data before any deployment ID or
// bin-version validation, and the pre-sizing helper (messageCount) skips the
// bounds/overflow checks that the main parser performs.

package raftpb

import "testing"

func TestAuditMalformedMessageBatchDoesNotPanic(t *testing.T) {
	payload := []byte{
		0x0A, 0x00, // field 1 (Requests), length 0: one empty Message
		0x0A, // field 1 tag for the next entry
		// 10-byte varint ending with 0x01 at shift 63 -> negative int
		0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x01,
	}
	var mb MessageBatch
	func() {
		defer func() {
			if r := recover(); r != nil {
				t.Fatalf("MessageBatch.Unmarshal panicked on malformed input: %v", r)
			}
		}()
		if err := mb.Unmarshal(payload); err != nil {
			t.Logf("malformed batch rejected with an error: %v", err)
		}
	}()
}
