//go:build dragonboat_audit

// Audit-only check that a malformed streamed-snapshot chunk is rejected rather
// than panicking the receiving goroutine.

package transport

import (
	"testing"

	"github.com/lni/dragonboat/v3/internal/vfs"
	"github.com/lni/dragonboat/v3/raftio"
	pb "github.com/lni/dragonboat/v3/raftpb"
)

func TestAuditShortFirstChunkDoesNotPanic(t *testing.T) {
	c := NewChunk(func(pb.MessageBatch) {}, func(uint64, uint64, uint64) {},
		func(uint64, uint64) string { return "audit-snapshot-root" }, 1,
		vfs.DefaultFS)
	defer c.Close()
	chunk := pb.Chunk{
		DeploymentId: 1,
		BinVer:       raftio.TransportBinVersion,
		ChunkId:      0,
		Data:         make([]byte, 10), // shorter than the 1024-byte header
	}
	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("Chunk.Add panicked on a short first chunk: %v", r)
		}
	}()
	if c.Add(chunk) {
		t.Fatalf("short first chunk was accepted")
	}
}

// A first chunk that claims to carry file info skips the snapshot validator
// and is written with OpenChunkFileForAppend; if the target file does not
// exist the save error is turned into a panic.
func TestAuditChunkWithUnexpectedFileChunkIDDoesNotPanic(t *testing.T) {
	root := t.TempDir()
	c := NewChunk(func(pb.MessageBatch) {}, func(uint64, uint64, uint64) {},
		func(uint64, uint64) string { return root }, 1,
		vfs.DefaultFS)
	defer c.Close()
	chunk := pb.Chunk{
		DeploymentId: 1,
		BinVer:       raftio.TransportBinVersion,
		ChunkId:      0,
		FileChunkId:  3, // not the first chunk of a file
		HasFileInfo:  true,
		Filepath:     "snapshot-0000000000000001.gbsnap",
		Data:         make([]byte, 16),
		ChunkCount:   2,
	}
	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("Chunk.Add panicked on a chunk with an unexpected file chunk id: %v", r)
		}
	}()
	c.Add(chunk)
}
