package epaxos

import (
	"bufio"
	"bytes"
	"github.com/imdea-software/swiftpaxos/replica/defs"
	"github.com/imdea-software/swiftpaxos/state"
	"sync"
	"testing"
	"time"

	fastrpc "github.com/imdea-software/swiftpaxos/rpc"
)

// Decode exactly one generated RPC before invoking its production handler.
func auditDeliver(t *testing.T, wire *bytes.Buffer, dst *Replica, msg fastrpc.Serializable) {
	t.Helper()
	if _, err := wire.ReadByte(); err != nil {
		t.Fatal(err)
	}
	if err := msg.Unmarshal(wire); err != nil {
		t.Fatal(err)
	}
	switch m := msg.(type) {
	case *PreAccept:
		dst.handlePreAccept(m)
	case *PreAcceptReply:
		dst.handlePreAcceptReply(m)
	case *Accept:
		dst.handleAccept(m)
	case *AcceptReply:
		dst.handleAcceptReply(m)
	case *Commit:
		dst.handleCommit(m)
	case *Prepare:
		dst.handlePrepare(m)
	case *PrepareReply:
		dst.handlePrepareReply(m)
	default:
		t.Fatalf("unsupported delivery %T", msg)
	}
}

func TestAuditUnseenDependencyNeverRecovered(t *testing.T) {
	leader, lo := auditReplica(0)
	waiting, wo := auditReplica(1)
	survivor, so := auditReplica(2)
	leader.PreferredPeerOrder = []int32{2, 1}
	// A: replica 0's write commits at replicas 0 and 2.
	leader.startPhase1(auditPut(10, "A"), 0, 0, 0, nil)
	auditDeliver(t, lo[2], survivor, new(PreAccept))
	auditDeliver(t, so[0], leader, new(PreAcceptReply))
	auditDeliver(t, lo[2], survivor, new(Commit))
	if survivor.InstanceSpace[0][0].Status != COMMITTED {
		t.Fatal("A must be committed")
	}
	// Replica 0 fails; its commit to replica 1 was not delivered.
	survivor.Alive[0] = false
	waiting.Alive[0] = false
	// B: a later conflicting write at the surviving replica reaches replica 1.
	survivor.crtInstance[2] = 0
	survivor.startPhase1(auditPut(10, "B"), 2, 0, 2, nil)
	auditDeliver(t, so[1], waiting, new(PreAccept))
	auditDeliver(t, wo[2], survivor, new(PreAcceptReply))
	auditDeliver(t, so[1], waiting, new(Commit))
	b := waiting.InstanceSpace[2][0]
	if b.Status != COMMITTED || b.Deps[0] != 0 {
		t.Fatalf("bad setup: B status=%d deps=%v", b.Status, b.Deps)
	}
	if waiting.exec.executeCommand(2, 0) {
		t.Fatal("B must block on absent A")
	}
	t.Logf("B committed with deps=%v; missing row0 instance0; crtInstance=%v", b.Deps, waiting.crtInstance)
	// A subsequent local read also commits, but cannot return to its client.
	var clientReply bytes.Buffer
	read := state.Command{Op: state.GET, K: 10}
	proposal := &defs.GPropose{Propose: &defs.Propose{CommandId: 9, Command: read}, Reply: bufio.NewWriter(&clientReply), Mutex: new(sync.Mutex)}
	waiting.crtInstance[1] = 0
	waiting.startPhase1([]state.Command{read}, 1, 0, 1, []*defs.GPropose{proposal})
	auditDeliver(t, wo[2], survivor, new(PreAccept))
	auditDeliver(t, so[1], waiting, new(PreAcceptReply))
	auditDeliver(t, wo[2], survivor, new(Commit))
	if waiting.InstanceSpace[1][0].Status != COMMITTED {
		t.Fatal("local read failed to commit")
	}
	waiting.instancesToRecover = make(chan *instanceId, 100)
	done := make(chan struct{})
	go func() { waiting.executeCommands(); close(done) }()
	// Longer than the original, unchanged 10-second recovery grace period.
	time.Sleep(13 * time.Second)
	waiting.Shutdown = true
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("executor did not stop")
	}
	t.Logf("after 13 seconds: B status=%d; local read status=%d reply bytes=%d; recovery requests=%d; missing-row bound=%d", b.Status, waiting.InstanceSpace[1][0].Status, clientReply.Len(), len(waiting.instancesToRecover), waiting.crtInstance[0])
	if len(waiting.instancesToRecover) == 0 {
		t.Error("committed command remains blocked but absent dependency is never scheduled for recovery")
	}
}
