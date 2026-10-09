package raft_test

import (
	"bytes"
	"context"
	raft "go.etcd.io/raft/v3"
	pb "go.etcd.io/raft/v3/raftpb"
	"testing"
	"time"
)

func auditNode(t *testing.T, maxMsg, quota uint64, customize ...func(*raft.Config)) (*raft.RawNode, *raft.MemoryStorage) {
	t.Helper()
	s := raft.NewMemoryStorage()
	if err := s.ApplySnapshot(pb.Snapshot{Metadata: pb.SnapshotMetadata{Index: 1, Term: 1, ConfState: pb.ConfState{Voters: []uint64{1}}}}); err != nil {
		t.Fatal(err)
	}
	if err := s.SetHardState(pb.HardState{Term: 1, Commit: 1}); err != nil {
		t.Fatal(err)
	}
	cfg := &raft.Config{ID: 1, ElectionTick: 10, HeartbeatTick: 1, Storage: s, MaxSizePerMsg: maxMsg, MaxInflightMsgs: 16, MaxUncommittedEntriesSize: quota}
	for _, f := range customize {
		f(cfg)
	}
	n, err := raft.NewRawNode(cfg)
	if err != nil {
		t.Fatal(err)
	}
	return n, s
}

func auditDrain(t *testing.T, n *raft.RawNode, s *raft.MemoryStorage) []pb.Entry {
	t.Helper()
	var applied []pb.Entry
	for i := 0; n.HasReady(); i++ {
		if i > 20 {
			t.Fatal("Ready failed to drain")
		}
		rd := n.Ready()
		if !raft.IsEmptySnap(rd.Snapshot) {
			if err := s.ApplySnapshot(rd.Snapshot); err != nil {
				t.Fatal(err)
			}
		}
		if err := s.Append(rd.Entries); err != nil {
			t.Fatal(err)
		}
		if !raft.IsEmptyHardState(rd.HardState) {
			if err := s.SetHardState(rd.HardState); err != nil {
				t.Fatal(err)
			}
		}
		applied = append(applied, rd.CommittedEntries...)
		n.Advance(rd)
	}
	return applied
}

// MaxSizePerMsg=0 explicitly means "at most one entry per message".
// Leaving MaxCommittedSizePerReady unset should not prevent application.
func TestAuditZeroMaxSizePerMsg(t *testing.T) {
	n, s := auditNode(t, 0, 0)
	if err := n.Campaign(); err != nil {
		t.Fatal(err)
	}
	applied := auditDrain(t, n, s)
	t.Logf("leader=%v commit=%d applied=%d returned=%v", n.BasicStatus().RaftState, n.BasicStatus().Commit, n.BasicStatus().Applied, applied)
	if n.BasicStatus().Applied != n.BasicStatus().Commit {
		t.Fatalf("committed leader entry never delivered for application")
	}
}

func TestAuditRejectedConfChangePoisonsRetry(t *testing.T) {
	n, s := auditNode(t, 1024, 8)
	if err := n.Campaign(); err != nil {
		t.Fatal(err)
	}
	auditDrain(t, n, s)
	if err := n.Propose(bytes.Repeat([]byte{'x'}, 8)); err != nil {
		t.Fatal(err)
	}
	cc := pb.ConfChange{Type: pb.ConfChangeAddLearnerNode, NodeID: 2}
	if err := n.ProposeConfChange(cc); err != raft.ErrProposalDropped {
		t.Fatalf("expected quota rejection, got %v", err)
	}
	auditDrain(t, n, s)
	if err := n.ProposeConfChange(cc); err != nil {
		t.Fatal(err)
	}
	applied := auditDrain(t, n, s)
	t.Logf("retry committed entries: %+v", applied)
	if len(applied) != 1 || applied[0].Type != pb.EntryConfChange {
		t.Fatalf("retry replaced by empty normal entry despite fully applied log and available quota")
	}
}

func TestAuditPositiveMessageLimit(t *testing.T) {
	n, s := auditNode(t, 1, 0)
	if err := n.Campaign(); err != nil {
		t.Fatal(err)
	}
	applied := auditDrain(t, n, s)
	if n.BasicStatus().Applied != n.BasicStatus().Commit || len(applied) != 1 {
		t.Fatalf("failed to apply: %+v", n.BasicStatus())
	}
	t.Logf("positive limit applied leader entry at %d", n.BasicStatus().Applied)
}

func TestAuditSnapshotOvertakesConfApply(t *testing.T) {
	for _, interleave := range []bool{false, true} {
		name := "ordered_control"
		if interleave {
			name = "snapshot_before_old_conf_application"
		}
		t.Run(name, func(t *testing.T) {
			s := raft.NewMemoryStorage()
			cs := pb.ConfState{Voters: []uint64{1, 2, 3}}
			if err := s.ApplySnapshot(pb.Snapshot{Metadata: pb.SnapshotMetadata{Index: 1, Term: 1, ConfState: cs}}); err != nil {
				t.Fatal(err)
			}
			s.SetHardState(pb.HardState{Term: 1, Commit: 1})
			n, err := raft.NewRawNode(&raft.Config{ID: 2, ElectionTick: 10, HeartbeatTick: 1, Storage: s, MaxSizePerMsg: 1024, MaxInflightMsgs: 16})
			if err != nil {
				t.Fatal(err)
			}
			cc := pb.ConfChange{Type: pb.ConfChangeAddNode, NodeID: 4}
			data, err := cc.Marshal()
			if err != nil {
				t.Fatal(err)
			}
			if err := n.Step(pb.Message{Type: pb.MsgApp, From: 1, To: 2, Term: 1, Index: 1, LogTerm: 1, Commit: 2, Entries: []pb.Entry{{Index: 2, Term: 1, Type: pb.EntryConfChange, Data: data}}}); err != nil {
				t.Fatal(err)
			}
			rd := n.Ready()
			if len(rd.CommittedEntries) != 1 {
				t.Fatalf("expected committed conf change: %+v", rd)
			}
			if err := s.Append(rd.Entries); err != nil {
				t.Fatal(err)
			}
			if err := s.SetHardState(rd.HardState); err != nil {
				t.Fatal(err)
			}
			// Leader subsequently commits removing voter 4 at index 3 and snapshots
			// index 4. Node 2 is behind in applying the already delivered index 2.
			snap := pb.Snapshot{Metadata: pb.SnapshotMetadata{Index: 4, Term: 1, ConfState: cs}}
			deliverSnapshot := func() {
				if err := n.Step(pb.Message{Type: pb.MsgSnap, From: 1, To: 2, Term: 1, Snapshot: &snap}); err != nil {
					t.Fatal(err)
				}
			}
			if interleave {
				deliverSnapshot()
			}
			n.ApplyConfChange(cc)
			n.Advance(rd)
			if !interleave {
				deliverSnapshot()
			}
			auditDrain(t, n, s)
			got := n.Status().Config.Voters.IDs()
			t.Logf("after snapshot: applied=%d voters=%v; snapshot voters=%v", n.BasicStatus().Applied, got, cs.Voters)
			if len(got) != 3 {
				t.Fatalf("old committed configuration overwrote newer snapshot configuration")
			}
		})
	}
}

func TestAuditNodeSnapshotOvertakesConfApply(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	s := raft.NewMemoryStorage()
	cs := pb.ConfState{Voters: []uint64{1, 2, 3}}
	if err := s.ApplySnapshot(pb.Snapshot{Metadata: pb.SnapshotMetadata{Index: 1, Term: 1, ConfState: cs}}); err != nil {
		t.Fatal(err)
	}
	if err := s.SetHardState(pb.HardState{Term: 1, Commit: 1}); err != nil {
		t.Fatal(err)
	}
	n := raft.RestartNode(&raft.Config{ID: 2, ElectionTick: 10, HeartbeatTick: 1, Storage: s, MaxSizePerMsg: 1024, MaxInflightMsgs: 16})
	defer n.Stop()
	cc := pb.ConfChange{Type: pb.ConfChangeAddNode, NodeID: 4}
	data, err := cc.Marshal()
	if err != nil {
		t.Fatal(err)
	}
	if err := n.Step(ctx, pb.Message{Type: pb.MsgApp, From: 1, To: 2, Term: 1, Index: 1, LogTerm: 1, Commit: 2, Entries: []pb.Entry{{Index: 2, Term: 1, Type: pb.EntryConfChange, Data: data}}}); err != nil {
		t.Fatal(err)
	}
	var rd raft.Ready
	select {
	case rd = <-n.Ready():
	case <-ctx.Done():
		t.Fatal(ctx.Err())
	}
	if len(rd.CommittedEntries) != 1 {
		t.Fatalf("expected committed conf change: %+v", rd)
	}
	if err := s.Append(rd.Entries); err != nil {
		t.Fatal(err)
	}
	if err := s.SetHardState(rd.HardState); err != nil {
		t.Fatal(err)
	}
	snap := pb.Snapshot{Metadata: pb.SnapshotMetadata{Index: 4, Term: 1, ConfState: cs}}
	if err := n.Step(ctx, pb.Message{Type: pb.MsgSnap, From: 1, To: 2, Term: 1, Snapshot: &snap}); err != nil {
		t.Fatal(err)
	}
	// Status is a barrier: the previous Step has now finished in Node.run.
	if got := n.Status().Commit; got != 4 {
		t.Fatalf("snapshot not processed: commit=%d", got)
	}
	updated := n.ApplyConfChange(cc)
	t.Logf("ApplyConfChange for outstanding index 2 returned voters=%v", updated.Voters)
	n.Advance()
	select {
	case rd = <-n.Ready():
	case <-ctx.Done():
		t.Fatal(ctx.Err())
	}
	if rd.Snapshot.Metadata.Index != 4 {
		t.Fatalf("expected snapshot: %+v", rd)
	}
	if err := s.ApplySnapshot(rd.Snapshot); err != nil {
		t.Fatal(err)
	}
	if err := s.Append(rd.Entries); err != nil {
		t.Fatal(err)
	}
	if !raft.IsEmptyHardState(rd.HardState) {
		if err := s.SetHardState(rd.HardState); err != nil {
			t.Fatal(err)
		}
	}
	n.Advance()
	status := n.Status()
	got := status.Config.Voters.IDs()
	t.Logf("after snapshot Ready/Advance: applied=%d voters=%v; snapshot voters=%v", status.Applied, got, cs.Voters)
	if len(got) != 3 {
		t.Fatalf("Node retains stale voter 4 after applying snapshot that removed it")
	}
}

func TestAuditZeroMessageWithExplicitApplyLimit(t *testing.T) {
	n, s := auditNode(t, 0, 0, func(c *raft.Config) { c.MaxCommittedSizePerReady = 1 })
	if err := n.Campaign(); err != nil {
		t.Fatal(err)
	}
	applied := auditDrain(t, n, s)
	if n.BasicStatus().Applied != n.BasicStatus().Commit || len(applied) != 1 {
		t.Fatalf("failed to apply: %+v", n.BasicStatus())
	}
	t.Logf("zero message limit with explicit apply limit successfully applied index %d", n.BasicStatus().Applied)
}
