package client

import (
	"bufio"
	"os"
	"path/filepath"
	"testing"

	"github.com/imdea-software/swiftpaxos/dlog"
	"github.com/imdea-software/swiftpaxos/replica/defs"
	"github.com/imdea-software/swiftpaxos/state"
)

// The fallback after the co-located replica is dead iterates over c.Ping and
// assigns the Ping-slice index to ClosestId.  When a dead replica was skipped,
// that index is not the replica id.
func TestAuditFindClosestSkipsDeadReplica(t *testing.T) {
	dir := t.TempDir()
	ping := filepath.Join(dir, "ping")
	script := "#!/bin/sh\necho 'rtt min/avg/max/mdev = 0.1/1.0/1.0/0.1 ms'\n"
	if err := os.WriteFile(ping, []byte(script), 0755); err != nil {
		t.Fatal(err)
	}
	oldPath := os.Getenv("PATH")
	if err := os.Setenv("PATH", dir+string(os.PathListSeparator)+oldPath); err != nil {
		t.Fatal(err)
	}
	defer os.Setenv("PATH", oldPath)

	c := &Client{
		Logger:    dlog.New("", false),
		replicas:  []string{"10.0.0.1", "10.0.0.2", "10.0.0.3"},
		server:    "10.0.0.1", // co-located replica is dead
		ClosestId: -1,
	}
	alive := []bool{false, true, true}
	if err := c.findClosest(alive); err != nil {
		t.Fatal(err)
	}
	t.Logf("replicas=%v alive=%v ClosestId=%d Ping=%v", c.replicas, alive, c.ClosestId, c.Ping)
	if c.ClosestId < 0 || c.ClosestId >= len(alive) || !alive[c.ClosestId] {
		t.Errorf("ClosestId=%d selects a dead or invalid replica; want one of the alive ids 1 or 2", c.ClosestId)
	}
}

// Once the fallback has selected a dead replica id, SendProposal indexes the
// nil writer for that replica.
func TestAuditSendProposalToDeadClosestDoesNotPanic(t *testing.T) {
	c := &Client{
		Logger:     dlog.New("", false),
		Leaderless: true,
		ClosestId:  0,
		writers:    make([]*bufio.Writer, 3),
	}
	defer func() {
		if p := recover(); p != nil {
			t.Errorf("SendProposal panicked for a dead ClosestId: %v", p)
		}
	}()
	c.SendProposal(defs.Propose{
		CommandId: 1, ClientId: 1,
		Command: state.Command{Op: state.PUT, K: 1, V: state.Value("x")},
	})
}
