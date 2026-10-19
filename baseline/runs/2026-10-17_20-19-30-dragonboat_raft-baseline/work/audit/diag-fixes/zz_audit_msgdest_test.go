//go:build dragonboat_audit

// Audit-only check: a message batch from a peer with an unset To field must be
// dropped, not panic the process.

package dragonboat

import (
	"testing"

	"github.com/lni/dragonboat/v3/config"
	"github.com/lni/dragonboat/v3/internal/vfs"
	"github.com/lni/dragonboat/v3/raftio"
	pb "github.com/lni/dragonboat/v3/raftpb"
)

func TestAuditMessageWithoutDestinationDoesNotPanic(t *testing.T) {
	fs := vfs.GetTestFS()
	dir := singleNodeHostTestDir
	if err := fs.RemoveAll(dir); err != nil {
		t.Fatalf("%v", err)
	}
	defer func() {
		if err := fs.RemoveAll(dir); err != nil {
			t.Fatalf("%v", err)
		}
	}()
	nhc := &config.NodeHostConfig{
		WALDir:         dir,
		NodeHostDir:    dir,
		RTTMillisecond: 10,
		RaftAddress:    singleNodeHostTestAddr,
		Expert:         getTestExpertConfig(fs),
	}
	nh, err := NewNodeHost(*nhc)
	if err != nil {
		t.Fatalf("NewNodeHost: %v", err)
	}
	defer nh.Stop()
	mb := pb.MessageBatch{
		DeploymentId: nh.nhConfig.GetDeploymentID(),
		BinVer:       raftio.TransportBinVersion,
		Requests: []pb.Message{{
			Type: pb.Heartbeat,
			// To left unset (0)
		}},
	}
	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("HandleMessageBatch panicked on a peer message with To == 0: %v", r)
		}
	}()
	nh.msgHandler.HandleMessageBatch(mb)
}
