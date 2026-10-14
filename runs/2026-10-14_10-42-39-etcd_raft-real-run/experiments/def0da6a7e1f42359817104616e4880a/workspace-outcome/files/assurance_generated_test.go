package raft

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"testing"
	"time"

	"google.golang.org/protobuf/proto"

	pb "go.etcd.io/raft/v3/raftpb"
)

// emitAssurance writes one CA_EVENT line to the selected test's output stream.
func emitAssurance(t *testing.T, event string, fields map[string]any) {
	t.Helper()
	rec := map[string]any{"event": event}
	for k, v := range fields {
		rec[k] = v
	}
	b, err := json.Marshal(rec)
	if err != nil {
		t.Fatalf("cannot marshal CA_EVENT: %v", err)
	}
	t.Logf("CA_EVENT %s", string(b))
}

type assuranceNode struct {
	id      uint64
	n       *node
	storage *MemoryStorage
}

// assuranceCluster drives several real raft nodes (Node API, no async storage
// writes) in one process: READY handling, storage appends, conf-change
// application and message delivery.
type assuranceCluster struct {
	t       *testing.T
	mu      sync.Mutex
	nodes   map[uint64]*assuranceNode
	applied map[uint64][]*pb.Entry
}

func newAssuranceCluster(t *testing.T, ids ...uint64) *assuranceCluster {
	c := &assuranceCluster{
		t:       t,
		nodes:   map[uint64]*assuranceNode{},
		applied: map[uint64][]*pb.Entry{},
	}
	for _, id := range ids {
		s := newTestMemoryStorage(withPeers(ids...))
		rn := newTestRawNode(id, 10, 1, s)
		nd := newNode(rn)
		c.nodes[id] = &assuranceNode{id: id, n: &nd, storage: s}
	}
	for _, cn := range c.nodes {
		go cn.n.run()
		go c.drive(cn)
	}
	t.Cleanup(c.stop)
	return c
}

func (c *assuranceCluster) drive(cn *assuranceNode) {
	for {
		select {
		case <-cn.n.done:
			return
		case rd := <-cn.n.Ready():
			if !IsEmptyHardState(rd.HardState) {
				cn.storage.SetHardState(rd.HardState)
			}
			if !IsEmptySnap(rd.Snapshot) {
				cn.storage.ApplySnapshot(rd.Snapshot)
			}
			cn.storage.Append(rd.Entries)
			c.mu.Lock()
			c.applied[cn.id] = append(c.applied[cn.id], rd.CommittedEntries...)
			c.mu.Unlock()
			for _, e := range rd.CommittedEntries {
				c.applyConfChange(cn, e)
			}
			for _, m := range rd.Messages {
				c.deliver(m)
			}
			cn.n.Advance()
		}
	}
}

func (c *assuranceCluster) applyConfChange(cn *assuranceNode, e *pb.Entry) {
	switch e.GetType() {
	case pb.EntryConfChange:
		cc := &pb.ConfChange{}
		if err := proto.Unmarshal(e.GetData(), cc); err != nil {
			c.t.Errorf("unmarshal ConfChange: %v", err)
			return
		}
		cn.n.ApplyConfChange(cc)
	case pb.EntryConfChangeV2:
		cc := &pb.ConfChangeV2{}
		if err := proto.Unmarshal(e.GetData(), cc); err != nil {
			c.t.Errorf("unmarshal ConfChangeV2: %v", err)
			return
		}
		cn.n.ApplyConfChange(cc)
	}
}

func (c *assuranceCluster) deliver(m *pb.Message) {
	if IsLocalMsgTarget(m.GetTo()) {
		return
	}
	c.mu.Lock()
	target := c.nodes[m.GetTo()]
	c.mu.Unlock()
	if target == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = target.n.Step(ctx, m)
}

func (c *assuranceCluster) stop() {
	for _, cn := range c.nodes {
		cn.n.Stop()
	}
}

func (c *assuranceCluster) appliedEntries(id uint64) []*pb.Entry {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]*pb.Entry(nil), c.applied[id]...)
}

func (c *assuranceCluster) waitUntil(what string, pred func() bool) bool {
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if pred() {
			return true
		}
		time.Sleep(2 * time.Millisecond)
	}
	c.t.Errorf("timed out waiting for %s", what)
	return false
}

func assuranceConfKind(t pb.ConfChangeType) string {
	switch t {
	case pb.ConfChangeAddNode:
		return "add"
	case pb.ConfChangeRemoveNode:
		return "remove"
	case pb.ConfChangeAddLearnerNode:
		return "add_learner"
	case pb.ConfChangeUpdateNode:
		return "update"
	}
	return fmt.Sprintf("unknown_%d", int(t))
}

// confChangeIn reports the index of the first applied conf change matching kind
// and target.
func confChangeIn(ents []*pb.Entry, kind string, target uint64) (uint64, bool) {
	for _, e := range ents {
		switch e.GetType() {
		case pb.EntryConfChange:
			cc := &pb.ConfChange{}
			if proto.Unmarshal(e.GetData(), cc) != nil {
				continue
			}
			if assuranceConfKind(cc.GetType()) == kind && cc.GetNodeId() == target {
				return e.GetIndex(), true
			}
		case pb.EntryConfChangeV2:
			cc := &pb.ConfChangeV2{}
			if proto.Unmarshal(e.GetData(), cc) != nil {
				continue
			}
			for _, ch := range cc.GetChanges() {
				if assuranceConfKind(ch.GetType()) == kind && ch.GetNodeId() == target {
					return e.GetIndex(), true
				}
			}
		}
	}
	return 0, false
}

func payloadPresent(ents []*pb.Entry, payload string) bool {
	for _, e := range ents {
		if e.GetType() == pb.EntryNormal && string(e.GetData()) == payload {
			return true
		}
	}
	return false
}

func (c *assuranceCluster) nodesWithPayload(payload string) []uint64 {
	var ids []uint64
	for id := range c.nodes {
		if payloadPresent(c.appliedEntries(id), payload) {
			ids = append(ids, id)
		}
	}
	return ids
}

func assuranceVoter(nd *node, id uint64) bool {
	cfg := nd.Status().Config
	if _, ok := cfg.Voters[0][id]; ok {
		return true
	}
	_, ok := cfg.Voters[1][id]
	return ok
}

func assuranceErrf(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

// TestAssuranceReaddedVoterPropose invokes Node.Propose on a voter that was
// removed and then re-added by committed configuration changes, while the same
// leader stays in place, and compares it with (a) a proposal by a member that
// was never removed, and (b) the same node's proposal after a leader change.
func TestAssuranceReaddedVoterPropose(t *testing.T) {
	const (
		opWitness = "readd-propose-witness"
		opControl = "member-propose-control"
		opRepair  = "rearm-propose-after-leader-change"
	)
	witnessPayload := "witness-payload-readded-voter"
	unboundedPayload := "unbounded-payload-readded-voter"
	controlPayload := "control-payload-member"
	repairPayload := "repair-payload-after-leader-change"
	const witnessWindowMs = 1200
	const witnessDeadlineMs = 2500
	const opUnbounded = "readd-propose-unbounded-context"

	c := newAssuranceCluster(t, 1, 2, 3)
	bg := context.Background()

	if err := c.nodes[1].n.Campaign(bg); err != nil {
		t.Fatalf("campaign: %v", err)
	}
	c.waitUntil("node 1 leader", func() bool { return c.nodes[1].n.Status().SoftState.Lead == 1 })
	c.waitUntil("every node sees leader 1", func() bool {
		for id := range c.nodes {
			if c.nodes[id].n.Status().SoftState.Lead != 1 {
				return false
			}
		}
		return true
	})
	c.waitUntil("node 1 applied initial entry", func() bool { return c.nodes[1].n.Status().Applied >= 1 })
	emitAssurance(t, "cluster_ready", map[string]any{
		"leader": 1, "term": c.nodes[1].n.Status().GetTerm(),
		"voters": []uint64{1, 2, 3},
	})

	// Prefix: remove node 3, then re-add it, both through committed conf changes
	// proposed on the leader and applied on every node.
	removeCC := &pb.ConfChange{Type: pb.ConfChangeRemoveNode.Enum(), NodeId: new(uint64(3))}
	emitAssurance(t, "conf_change_proposed", map[string]any{
		"operation_id": "remove-3", "node": 1, "change": "remove", "target": 3,
	})
	if err := c.nodes[1].n.ProposeConfChange(bg, removeCC); err != nil {
		t.Fatalf("propose remove: %v", err)
	}
	var removeIndex uint64
	c.waitUntil("node 3 applied its own removal", func() bool {
		idx, ok := confChangeIn(c.appliedEntries(3), "remove", 3)
		if ok {
			removeIndex = idx
		}
		return ok
	})
	c.waitUntil("node 3 config excludes itself", func() bool { return !assuranceVoter(c.nodes[3].n, 3) })
	emitAssurance(t, "remove_applied", map[string]any{
		"operation_id": "remove-3", "node": 3, "change": "remove", "target": 3, "ok": true,
		"applied_index": int(removeIndex), "voter": assuranceVoter(c.nodes[3].n, 3),
		"leader": c.nodes[3].n.Status().SoftState.Lead, "term": c.nodes[3].n.Status().GetTerm(),
	})

	addCC := &pb.ConfChange{Type: pb.ConfChangeAddNode.Enum(), NodeId: new(uint64(3))}
	emitAssurance(t, "conf_change_proposed", map[string]any{
		"operation_id": "readd-3", "node": 1, "change": "add", "target": 3,
	})
	if err := c.nodes[1].n.ProposeConfChange(bg, addCC); err != nil {
		t.Fatalf("propose readd: %v", err)
	}
	var readdIndex uint64
	c.waitUntil("node 3 applied its own re-admission", func() bool {
		idx, ok := confChangeIn(c.appliedEntries(3), "add", 3)
		if ok {
			readdIndex = idx
		}
		return ok
	})
	c.waitUntil("node 3 config includes itself again", func() bool { return assuranceVoter(c.nodes[3].n, 3) })
	emitAssurance(t, "readd_applied", map[string]any{
		"operation_id": opWitness, "change": "add", "target": 3, "node": 3, "ok": true,
		"applied_index": int(readdIndex), "voter": assuranceVoter(c.nodes[3].n, 3),
		"leader": c.nodes[3].n.Status().SoftState.Lead, "term": c.nodes[3].n.Status().GetTerm(),
	})
	emitAssurance(t, "witness_context", map[string]any{
		"operation_id": opWitness, "node": 3,
		"voter":  assuranceVoter(c.nodes[3].n, 3),
		"leader": c.nodes[3].n.Status().SoftState.Lead,
		"term":   c.nodes[3].n.Status().GetTerm(),
	})

	// Case 1 (witness): propose on the re-added voter while the leader is stable.
	emitAssurance(t, "witness_invocation", map[string]any{
		"operation_id": opWitness, "node": 3, "phase": "after_readmission",
		"leader": c.nodes[3].n.Status().SoftState.Lead, "voter": assuranceVoter(c.nodes[3].n, 3),
		"deadline_ms": witnessDeadlineMs, "payload": witnessPayload,
	})
	ctxW, cancelW := context.WithTimeout(context.Background(), witnessDeadlineMs*time.Millisecond)
	defer cancelW()
	wErrCh := make(chan error, 1)
	startW := time.Now()
	go func() { wErrCh <- c.nodes[3].n.Propose(ctxW, []byte(witnessPayload)) }()
	var wReturned bool
	var wErr error
	select {
	case wErr = <-wErrCh:
		wReturned = true
	case <-time.After(witnessWindowMs * time.Millisecond):
	}
	emitAssurance(t, "witness_result", map[string]any{
		"operation_id": opWitness, "node": 3, "phase": "after_readmission",
		"returned": wReturned, "err": assuranceErrf(wErr),
		"elapsed_ms": int(time.Since(startW).Milliseconds()), "window_ms": witnessWindowMs,
		"deadline_ms": witnessDeadlineMs, "voter": assuranceVoter(c.nodes[3].n, 3),
		"leader": c.nodes[3].n.Status().SoftState.Lead, "payload": witnessPayload,
	})
	if !wReturned {
		select {
		case wErr = <-wErrCh:
			emitAssurance(t, "witness_release", map[string]any{
				"operation_id": opWitness, "node": 3, "err": assuranceErrf(wErr),
				"elapsed_ms": int(time.Since(startW).Milliseconds()),
			})
		case <-time.After(3 * time.Second):
			emitAssurance(t, "witness_release", map[string]any{
				"operation_id": opWitness, "node": 3, "err": "still not returned",
				"elapsed_ms": int(time.Since(startW).Milliseconds()),
			})
		}
	}
	witnessNodes := c.nodesWithPayload(witnessPayload)
	emitAssurance(t, "witness_commit", map[string]any{
		"operation_id": opWitness, "payload": witnessPayload,
		"present": len(witnessNodes) > 0, "observed_nodes": witnessNodes,
		"checked_after_ms": witnessWindowMs,
	})

	// Case 2 (unbounded context): the same invocation issued with a context that
	// never expires is still pending after a fixed observation window.
	emitAssurance(t, "unbounded_invocation", map[string]any{
		"operation_id": opUnbounded, "node": 3, "phase": "after_readmission",
		"leader": c.nodes[3].n.Status().SoftState.Lead, "voter": assuranceVoter(c.nodes[3].n, 3),
		"context": "background", "payload": unboundedPayload,
	})
	startU := time.Now()
	uErrCh := make(chan error, 1)
	go func() { uErrCh <- c.nodes[3].n.Propose(context.Background(), []byte(unboundedPayload)) }()
	var uReturned bool
	var uErr error
	select {
	case uErr = <-uErrCh:
		uReturned = true
	case <-time.After(2000 * time.Millisecond):
	}
	emitAssurance(t, "unbounded_result", map[string]any{
		"operation_id": opUnbounded, "node": 3, "phase": "after_readmission",
		"returned": uReturned, "err": assuranceErrf(uErr),
		"elapsed_ms": int(time.Since(startU).Milliseconds()), "window_ms": 2000,
		"context": "background", "voter": assuranceVoter(c.nodes[3].n, 3),
		"leader": c.nodes[3].n.Status().SoftState.Lead, "payload": unboundedPayload,
	})
	emitAssurance(t, "unbounded_commit", map[string]any{
		"operation_id": opUnbounded, "payload": unboundedPayload,
		"present": len(c.nodesWithPayload(unboundedPayload)) > 0,
		"observed_nodes": c.nodesWithPayload(unboundedPayload),
	})

	// Case 3 (control): the same kind of invocation on a member that was never
	// removed, with the same leader, must complete and be committed.
	emitAssurance(t, "control_invocation", map[string]any{
		"operation_id": opControl, "node": 2, "phase": "after_readmission",
		"leader": c.nodes[2].n.Status().SoftState.Lead, "voter": assuranceVoter(c.nodes[2].n, 2),
		"deadline_ms": 5000, "payload": controlPayload,
	})
	ctxC, cancelC := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancelC()
	startC := time.Now()
	cErr := c.nodes[2].n.Propose(ctxC, []byte(controlPayload))
	emitAssurance(t, "control_result", map[string]any{
		"operation_id": opControl, "node": 2, "phase": "after_readmission",
		"returned": true, "err": assuranceErrf(cErr),
		"elapsed_ms": int(time.Since(startC).Milliseconds()), "window_ms": 5000,
		"deadline_ms": 5000, "voter": assuranceVoter(c.nodes[2].n, 2),
		"leader": c.nodes[2].n.Status().SoftState.Lead, "payload": controlPayload,
	})
	c.waitUntil("control payload committed", func() bool {
		return len(c.nodesWithPayload(controlPayload)) > 0
	})
	controlNodes := c.nodesWithPayload(controlPayload)
	emitAssurance(t, "control_commit", map[string]any{
		"operation_id": opControl, "payload": controlPayload,
		"present": len(controlNodes) > 0, "observed_nodes": controlNodes,
	})

	// Case 3 (retry cycle): while the leader stays stable, repeated invocations on
	// the re-added voter do not make progress, although the cluster keeps
	// committing proposals made by another member in the same intervals.
	for attempt := 1; attempt <= 2; attempt++ {
		retryOp := fmt.Sprintf("readd-retry-attempt-%d", attempt)
		progressOp := fmt.Sprintf("progress-during-retry-%d", attempt)
		retryPayload := fmt.Sprintf("retry-payload-%d", attempt)
		progressPayload := fmt.Sprintf("progress-payload-%d", attempt)
		invocationEvent := fmt.Sprintf("retry%d_invocation", attempt)
		resultEvent := fmt.Sprintf("retry%d_result", attempt)
		progressInvocationEvent := fmt.Sprintf("progress%d_invocation", attempt)
		progressResultEvent := fmt.Sprintf("progress%d_result", attempt)
		progressCommitEvent := fmt.Sprintf("progress%d_commit", attempt)

		emitAssurance(t, invocationEvent, map[string]any{
			"operation_id": retryOp, "node": 3, "attempt": attempt, "phase": "after_readmission",
			"leader": c.nodes[3].n.Status().SoftState.Lead, "voter": assuranceVoter(c.nodes[3].n, 3),
			"deadline_ms": 900, "payload": retryPayload,
		})
		ctxT, cancelT := context.WithTimeout(bg, 900*time.Millisecond)
		defer cancelT()
		tErrCh := make(chan error, 1)
		startT := time.Now()
		go func() { tErrCh <- c.nodes[3].n.Propose(ctxT, []byte(retryPayload)) }()
		var tReturned bool
		var tErr error
		select {
		case tErr = <-tErrCh:
			tReturned = true
		case <-time.After(800 * time.Millisecond):
		}
		emitAssurance(t, resultEvent, map[string]any{
			"operation_id": retryOp, "node": 3, "attempt": attempt, "phase": "after_readmission",
			"returned": tReturned, "err": assuranceErrf(tErr),
			"elapsed_ms": int(time.Since(startT).Milliseconds()), "window_ms": 800, "deadline_ms": 900,
			"voter": assuranceVoter(c.nodes[3].n, 3), "leader": c.nodes[3].n.Status().SoftState.Lead,
			"payload": retryPayload,
		})

		emitAssurance(t, progressInvocationEvent, map[string]any{
			"operation_id": progressOp, "node": 2, "attempt": attempt, "phase": "during_retry",
			"leader": c.nodes[2].n.Status().SoftState.Lead, "voter": assuranceVoter(c.nodes[2].n, 2),
			"deadline_ms": 3000, "payload": progressPayload,
		})
		ctxP, cancelP := context.WithTimeout(bg, 3*time.Second)
		pErr := c.nodes[2].n.Propose(ctxP, []byte(progressPayload))
		cancelP()
		pCommitted := c.waitUntil("progress payload committed", func() bool {
			return len(c.nodesWithPayload(progressPayload)) > 0
		})
		emitAssurance(t, progressResultEvent, map[string]any{
			"operation_id": progressOp, "node": 2, "attempt": attempt, "phase": "during_retry",
			"returned": true, "err": assuranceErrf(pErr),
			"voter": assuranceVoter(c.nodes[2].n, 2), "leader": c.nodes[2].n.Status().SoftState.Lead,
			"payload": progressPayload,
		})
		emitAssurance(t, progressCommitEvent, map[string]any{
			"operation_id": progressOp, "payload": progressPayload,
			"present": pCommitted, "observed_nodes": c.nodesWithPayload(progressPayload),
		})
	}

	// Case 4 (repair): the source-reachable re-arm is a leader change; after it,
	// the same node's invocation completes and is committed.
	if err := c.nodes[2].n.Campaign(bg); err != nil {
		t.Fatalf("campaign 2: %v", err)
	}
	c.waitUntil("node 3 sees a new leader", func() bool {
		l := c.nodes[3].n.Status().SoftState.Lead
		return l != 0 && l != 1
	})
	newLeader := c.nodes[3].n.Status().SoftState.Lead
	emitAssurance(t, "repair_leader_change", map[string]any{
		"operation_id": opRepair, "node": 3, "from": 1, "to": newLeader,
		"term": c.nodes[3].n.Status().GetTerm(),
	})
	emitAssurance(t, "repair_invocation", map[string]any{
		"operation_id": opRepair, "node": 3, "phase": "after_leader_change",
		"leader": newLeader, "voter": assuranceVoter(c.nodes[3].n, 3),
		"deadline_ms": 5000, "payload": repairPayload,
	})
	ctxR, cancelR := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancelR()
	rErrCh := make(chan error, 1)
	startR := time.Now()
	go func() { rErrCh <- c.nodes[3].n.Propose(ctxR, []byte(repairPayload)) }()
	var rReturned bool
	var rErr error
	select {
	case rErr = <-rErrCh:
		rReturned = true
	case <-time.After(2000 * time.Millisecond):
	}
	emitAssurance(t, "repair_result", map[string]any{
		"operation_id": opRepair, "node": 3, "phase": "after_leader_change",
		"returned": rReturned, "err": assuranceErrf(rErr),
		"elapsed_ms": int(time.Since(startR).Milliseconds()), "window_ms": 2000,
		"deadline_ms": 5000, "voter": assuranceVoter(c.nodes[3].n, 3),
		"leader": c.nodes[3].n.Status().SoftState.Lead, "payload": repairPayload,
	})
	c.waitUntil("repair payload committed", func() bool {
		return len(c.nodesWithPayload(repairPayload)) > 0
	})
	repairNodes := c.nodesWithPayload(repairPayload)
	emitAssurance(t, "repair_commit", map[string]any{
		"operation_id": opRepair, "payload": repairPayload,
		"present": len(repairNodes) > 0, "observed_nodes": repairNodes,
	})

	// The invocation issued before the leader change is not rescued by it: its
	// channel was captured when the gate was nil, so it stays pending until the
	// caller's context or the node stop. Node 3 is then stopped, which is the
	// only remaining documented exit for a context-free invocation.
	pending := true
	select {
	case uErr = <-uErrCh:
		pending = false
	default:
	}
	emitAssurance(t, "unbounded_after_repair", map[string]any{
		"operation_id": opUnbounded, "node": 3, "pending": pending,
		"returned": !pending, "err": assuranceErrf(uErr),
		"elapsed_ms": int(time.Since(startU).Milliseconds()),
		"leader": c.nodes[3].n.Status().SoftState.Lead, "payload": unboundedPayload,
	})
	c.waitUntil("unbounded payload committed after re-arm", func() bool {
		return len(c.nodesWithPayload(unboundedPayload)) > 0
	})
	emitAssurance(t, "unbounded_commit_after_repair", map[string]any{
		"operation_id": opUnbounded, "payload": unboundedPayload,
		"present": len(c.nodesWithPayload(unboundedPayload)) > 0,
		"observed_nodes": c.nodesWithPayload(unboundedPayload),
	})
}
