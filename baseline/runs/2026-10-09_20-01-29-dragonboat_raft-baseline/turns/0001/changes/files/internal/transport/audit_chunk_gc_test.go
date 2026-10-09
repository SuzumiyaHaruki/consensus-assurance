package transport

import (
	"bytes"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/lni/dragonboat/v3/internal/rsm"
	"github.com/lni/dragonboat/v3/internal/settings"
	"github.com/lni/dragonboat/v3/internal/vfs"
	pb "github.com/lni/dragonboat/v3/raftpb"
)

// No transport, network, validation bypass, or production edits. The test
// controls the scheduling gap between Add taking the snapshot lock and calling
// addLocked; that is exactly the critical section implemented by Add.
func TestAuditSnapshotRetrySurvivesOldGC(t *testing.T) {
	fs := vfs.DefaultFS
	root := t.TempDir()
	source := fs.PathJoin(root, "source.gbsnap")
	w, err := rsm.NewSnapshotWriter(source, pb.NoCompression, fs)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = w.Write(bytes.Repeat([]byte{42}, int(snapshotChunkSize*2))); err != nil {
		t.Fatal(err)
	}
	if err = w.Close(); err != nil {
		t.Fatal(err)
	}
	info, err := fs.Stat(source)
	if err != nil {
		t.Fatal(err)
	}
	received := 0
	dest := fs.PathJoin(root, "receiver")
	if err = fs.MkdirAll(dest, 0755); err != nil {
		t.Fatal(err)
	}
	c := NewChunk(func(pb.MessageBatch) { received++ }, func(uint64, uint64, uint64) {},
		func(uint64, uint64) string { return dest }, settings.UnmanagedDeploymentID, fs)
	defer c.Close()
	chunks := splitSnapshotMessage(pb.Message{Type: pb.InstallSnapshot, From: 1, To: 2, ClusterId: 100,
		Snapshot: pb.Snapshot{Index: 100, Term: 2, Filepath: source, FileSize: uint64(info.Size())}}, fs)
	for i := range chunks {
		chunks[i].DeploymentId = settings.UnmanagedDeploymentID
		chunks[i].Data, err = loadChunkData(chunks[i], nil, fs)
		if err != nil {
			t.Fatal(err)
		}
	}
	if len(chunks) < 2 {
		t.Fatal("need multipart snapshot")
	}
	if !c.Add(chunks[0]) {
		t.Fatal("valid initial chunk rejected")
	}
	// Reach the first GC tick at which the old transfer is expired.
	expiry := ((c.timeout + c.gcTick - 1) / c.gcTick) * c.gcTick
	for i := uint64(1); i < expiry; i++ {
		c.Tick()
	}
	key := chunkKey(chunks[0])
	lock := c.getSnapshotLock(key)
	lock.lock()
	// A retry has acquired Add's lock, but GC captures the old tracked pointer
	// before that retry executes record(). GC must wait for this lock.
	done := make(chan struct{})
	go func() { c.Tick(); close(done) }()
	deadline := time.Now().Add(3 * time.Second)
	observed := false
	for time.Now().Before(deadline) {
		b := make([]byte, 1<<16)
		n := runtime.Stack(b, true)
		for _, stack := range strings.Split(string(b[:n]), "\n\n") {
			if strings.Contains(stack, "(*Chunk).gc.func1") && strings.Contains(stack, "sync.(*Mutex).lockSlow") {
				observed = true
				break
			}
		}
		if observed {
			break
		}
		runtime.Gosched()
	}
	if !observed {
		lock.unlock()
		<-done
		t.Fatal("did not observe GC waiting on snapshot lock")
	}
	old := c.tracked[key]
	accepted := c.addLocked(chunks[0]) // Exact body of Add under its required lock.
	fresh := c.tracked[key]
	t.Logf("restart accepted=%v old tick=%d fresh tick=%d now=%d timeout=%d", accepted, old.tick, fresh.tick, c.getTick(), c.timeout)
	if !accepted || old == fresh {
		lock.unlock()
		<-done
		t.Fatal("retry setup failed")
	}
	lock.unlock()
	<-done
	_, tracked := c.getTracked()[key]
	t.Logf("after GC: fresh transfer tracked=%v temporary file present=%v", tracked, hasSnapshotTempFile(c, chunks[0]))
	for _, chunk := range chunks[1:] {
		if !c.Add(chunk) {
			t.Errorf("valid retry chunk %d rejected after stale GC", chunk.ChunkId)
			break
		}
	}
	if received != 1 {
		t.Errorf("restarted valid snapshot delivered %d times; want 1", received)
	}
	// Control: the identical complete transfer succeeds without the stale GC.
	for _, chunk := range chunks {
		if !c.Add(chunk) {
			t.Fatalf("control retry rejected chunk %d", chunk.ChunkId)
		}
	}
	t.Logf("control retry without concurrent GC: delivered=%d", received)
	if received != 1 {
		t.Fatalf("control retry did not complete")
	}
}
