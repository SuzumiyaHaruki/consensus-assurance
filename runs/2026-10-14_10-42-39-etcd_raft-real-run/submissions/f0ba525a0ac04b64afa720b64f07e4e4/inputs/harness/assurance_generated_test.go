package raft

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand"
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
	return newAssuranceClusterWith(t, nil, ids...)
}

// newAssuranceClusterWith builds the same cluster with an optional Config
// mutation, so scenarios can run under the recommended production flags.
func newAssuranceClusterWith(t *testing.T, mut func(*Config), ids ...uint64) *assuranceCluster {
	c := &assuranceCluster{
		t:       t,
		nodes:   map[uint64]*assuranceNode{},
		applied: map[uint64][]*pb.Entry{},
	}
	for _, id := range ids {
		s := newTestMemoryStorage(withPeers(ids...))
		cfg := newTestConfig(id, 10, 1, s)
		if mut != nil {
			mut(cfg)
		}
		rn, err := NewRawNode(cfg)
		if err != nil {
			t.Fatalf("new raw node: %v", err)
		}
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

// restart stops a node and rebuilds it from the same MemoryStorage, which the
// driver has kept up to date with the node's HardState and appended entries.
// The restarted instance therefore starts from what the storage holds, as a
// real process restart does.
func (c *assuranceCluster) restart(id uint64) {
	c.mu.Lock()
	old := c.nodes[id]
	c.mu.Unlock()
	old.n.Stop()
	rn := newTestRawNode(id, 10, 1, old.storage)
	nd := newNode(rn)
	nn := &assuranceNode{id: id, n: &nd, storage: old.storage}
	c.mu.Lock()
	c.nodes[id] = nn
	c.mu.Unlock()
	go nn.n.run()
	go c.drive(nn)
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
	const opConfProposal = "readd-propose-conf-change"
	const confProposalNode = 9

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
	// The removal goes through joint consensus with automatic leave: the member
	// stays a voter in the outgoing half while the config is joint and is
	// dropped from both halves only when the joint state is left.
	removeCC := &pb.ConfChangeV2{
		Transition: pb.ConfChangeTransitionJointImplicit.Enum(),
		Changes: []*pb.ConfChangeSingle{{
			Type: pb.ConfChangeRemoveNode.Enum(), NodeId: new(uint64(3)),
		}},
	}
	emitAssurance(t, "conf_change_proposed", map[string]any{
		"operation_id": "joint-remove-3", "node": 1, "change": "remove", "target": 3,
		"transition": "joint_implicit",
	})
	if err := c.nodes[1].n.ProposeConfChange(bg, removeCC); err != nil {
		t.Fatalf("propose remove: %v", err)
	}
	var removeIndex uint64
	c.waitUntil("node 3 applied its own removal", func() bool {
		var last uint64
		var count int
		for _, e := range c.appliedEntries(3) {
			if idx, ok := confChangeIn([]*pb.Entry{e}, "remove", 3); ok {
				last = idx
				count++
			}
		}
		if count > 0 {
			removeIndex = last
		}
		return count > 0
	})
	c.waitUntil("node 3 config excludes itself", func() bool { return !assuranceVoter(c.nodes[3].n, 3) })
	removalEntries := 0
	for _, e := range c.appliedEntries(3) {
		if _, ok := confChangeIn([]*pb.Entry{e}, "remove", 3); ok {
			removalEntries++
		}
	}
	emitAssurance(t, "removal_applied", map[string]any{
		"operation_id": opWitness, "node": 3, "change": "remove", "target": 3, "ok": true,
		"transition": "joint_implicit", "conf_change_entries": removalEntries,
		"last_applied_index": int(removeIndex), "voter": assuranceVoter(c.nodes[3].n, 3),
		"outgoing": func() bool {
			_, ok := c.nodes[3].n.Status().Config.Voters[1][3]
			return ok
		}(),
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

	// Case 2b (logical clock running): ticks reach every node while the pending
	// invocation is outstanding, so heartbeat and election timeouts advance as in
	// a live deployment. Ten rounds with delivery in between keep heartbeats
	// flowing, so no election should be triggered by the clock itself.
	for round := 0; round < 10; round++ {
		for id := range c.nodes {
			c.nodes[id].n.Tick()
		}
		time.Sleep(20 * time.Millisecond)
	}
	uPending := true
	select {
	case uErr = <-uErrCh:
		uPending = false
	default:
	}
	emitAssurance(t, "ticks_window", map[string]any{
		"operation_id": opUnbounded, "node": 3, "ticks": 10,
		"leader": c.nodes[3].n.Status().SoftState.Lead,
		"term":   c.nodes[3].n.Status().GetTerm(),
		"voter":  assuranceVoter(c.nodes[3].n, 3),
		"leader_state": c.nodes[1].n.Status().RaftState.String(),
		"pending": uPending, "payload": unboundedPayload,
	})

	// Case 3 (configuration proposal): the same gate also covers proposals of
	// configuration changes, so an administrative change proposed through the
	// re-added voter is held pending as well.
	confProposal := &pb.ConfChange{Type: pb.ConfChangeAddNode.Enum(), NodeId: new(uint64(confProposalNode))}
	emitAssurance(t, "confproposal_invocation", map[string]any{
		"operation_id": opConfProposal, "node": 3, "phase": "after_readmission",
		"leader": c.nodes[3].n.Status().SoftState.Lead, "voter": assuranceVoter(c.nodes[3].n, 3),
		"deadline_ms": 900, "change": "add", "target": confProposalNode,
	})
	ctxCC, cancelCC := context.WithTimeout(bg, 900*time.Millisecond)
	defer cancelCC()
	ccErrCh := make(chan error, 1)
	startCC := time.Now()
	go func() { ccErrCh <- c.nodes[3].n.ProposeConfChange(ctxCC, confProposal) }()
	var ccReturned bool
	var ccErr error
	select {
	case ccErr = <-ccErrCh:
		ccReturned = true
	case <-time.After(800 * time.Millisecond):
	}
	emitAssurance(t, "confproposal_result", map[string]any{
		"operation_id": opConfProposal, "node": 3, "phase": "after_readmission",
		"returned": ccReturned, "err": assuranceErrf(ccErr),
		"elapsed_ms": int(time.Since(startCC).Milliseconds()), "window_ms": 800, "deadline_ms": 900,
		"voter": assuranceVoter(c.nodes[3].n, 3), "leader": c.nodes[3].n.Status().SoftState.Lead,
		"change": "add", "target": confProposalNode,
	})
	confApplied := false
	for id := range c.nodes {
		if _, ok := confChangeIn(c.appliedEntries(id), "add", confProposalNode); ok {
			confApplied = true
		}
	}
	emitAssurance(t, "confproposal_commit", map[string]any{
		"operation_id": opConfProposal, "change": "add", "target": confProposalNode,
		"present": confApplied,
	})

	// Case 4 (control): the same kind of invocation on a member that was never
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
	pending := uPending
	if pending {
		select {
		case uErr = <-uErrCh:
			pending = false
		default:
		}
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

// TestAssuranceRandomizedSafety explores safety invariants of the captured
// TestAssuranceJointMembershipPropose is the positive control for the proposal
// TestAssuranceRestartRecovery exercises the recovery and resynchronization
// TestAssuranceReaddedVoterProposeChecked is the same witness scenario as the
// main test but under the recommended production configuration (PreVote and
// CheckQuorum) with the logical clock running, to check that the held proposal
// is not an artifact of default flags or of a clock that never advances.
func TestAssuranceReaddedVoterProposeChecked(t *testing.T) {
	const (
		opWitnessC = "checked-witness-propose"
		opControlC = "checked-control-propose"
	)
	witnessPayload := "checked-witness-payload"
	controlPayload := "checked-control-payload"
	c := newAssuranceClusterWith(t, func(cfg *Config) {
		cfg.PreVote = true
		cfg.CheckQuorum = true
	}, 1, 2, 3)
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

	removeCC := &pb.ConfChange{Type: pb.ConfChangeRemoveNode.Enum(), NodeId: new(uint64(3))}
	emitAssurance(t, "checked_removal_proposed", map[string]any{
		"operation_id": opWitnessC, "node": 1, "change": "remove", "target": 3,
	})
	if err := c.nodes[1].n.ProposeConfChange(bg, removeCC); err != nil {
		t.Fatalf("propose remove: %v", err)
	}
	c.waitUntil("node 3 excluded", func() bool { return !assuranceVoter(c.nodes[3].n, 3) })
	emitAssurance(t, "checked_removal_applied", map[string]any{
		"operation_id": opWitnessC, "node": 3, "voter": assuranceVoter(c.nodes[3].n, 3),
		"leader": c.nodes[3].n.Status().SoftState.Lead,
	})
	addCC := &pb.ConfChange{Type: pb.ConfChangeAddNode.Enum(), NodeId: new(uint64(3))}
	if err := c.nodes[1].n.ProposeConfChange(bg, addCC); err != nil {
		t.Fatalf("propose readd: %v", err)
	}
	c.waitUntil("node 3 readmitted", func() bool { return assuranceVoter(c.nodes[3].n, 3) })

	// Run the clock while the invocation is outstanding: heartbeat interval
	// reached, election interval not exceeded between rounds.
	for round := 0; round < 10; round++ {
		for id := range c.nodes {
			c.nodes[id].n.Tick()
		}
		time.Sleep(20 * time.Millisecond)
	}
	emitAssurance(t, "checked_context", map[string]any{
		"operation_id": opWitnessC, "node": 3, "voter": assuranceVoter(c.nodes[3].n, 3),
		"leader": c.nodes[3].n.Status().SoftState.Lead, "leader_state": c.nodes[1].n.Status().RaftState.String(),
	})
	emitAssurance(t, "checked_invocation", map[string]any{
		"operation_id": opWitnessC, "node": 3, "phase": "after_readmission_checked",
		"leader": c.nodes[3].n.Status().SoftState.Lead, "voter": assuranceVoter(c.nodes[3].n, 3),
		"deadline_ms": 1200, "payload": witnessPayload,
	})
	ctxW, cancelW := context.WithTimeout(bg, 1200*time.Millisecond)
	defer cancelW()
	wErrCh := make(chan error, 1)
	startW := time.Now()
	go func() { wErrCh <- c.nodes[3].n.Propose(ctxW, []byte(witnessPayload)) }()
	var wErr error
	var wReturned bool
	select {
	case wErr = <-wErrCh:
		wReturned = true
	case <-time.After(900 * time.Millisecond):
	}
	emitAssurance(t, "checked_result", map[string]any{
		"operation_id": opWitnessC, "node": 3, "phase": "after_readmission_checked",
		"returned": wReturned, "err": assuranceErrf(wErr),
		"elapsed_ms": int(time.Since(startW).Milliseconds()), "window_ms": 900, "deadline_ms": 1200,
		"voter": assuranceVoter(c.nodes[3].n, 3), "leader": c.nodes[3].n.Status().SoftState.Lead,
		"payload": witnessPayload,
	})
	emitAssurance(t, "checked_commit", map[string]any{
		"operation_id": opWitnessC, "payload": witnessPayload,
		"present": len(c.nodesWithPayload(witnessPayload)) > 0,
		"observed_nodes": c.nodesWithPayload(witnessPayload),
	})
	// Control under the same flags: a member that was never removed proposes.
	emitAssurance(t, "checked_control_invocation", map[string]any{
		"operation_id": opControlC, "node": 2, "phase": "after_readmission_checked",
		"leader": c.nodes[2].n.Status().SoftState.Lead, "voter": assuranceVoter(c.nodes[2].n, 2),
		"deadline_ms": 3000, "payload": controlPayload,
	})
	ctxC, cancelC := context.WithTimeout(bg, 3*time.Second)
	defer cancelC()
	cErr := c.nodes[2].n.Propose(ctxC, []byte(controlPayload))
	emitAssurance(t, "checked_control_result", map[string]any{
		"operation_id": opControlC, "node": 2, "returned": true, "err": assuranceErrf(cErr),
		"leader": c.nodes[2].n.Status().SoftState.Lead, "payload": controlPayload,
	})
	c.waitUntil("control payload committed under flags", func() bool {
		return len(c.nodesWithPayload(controlPayload)) > 0
	})
	emitAssurance(t, "checked_control_commit", map[string]any{
		"operation_id": opControlC, "payload": controlPayload,
		"present": len(c.nodesWithPayload(controlPayload)) > 0,
		"observed_nodes": c.nodesWithPayload(controlPayload),
	})
}

// path: a member is stopped, entries are committed while it is down, and it is
// restarted from its persisted storage. The test records whether it reaches the
// committed state, whether its applied entries agree with the rest of the group,
// and whether it can propose again after relearning the leader.
func TestAssuranceRestartRecovery(t *testing.T) {
	const opRestart = "restart-recovery"
	recoveredPayload := "restart-recovered-payload"
	freshPayload := "restart-fresh-payload"
	downPayload := "restart-down-payload"
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

	// Stop node 2, commit an entry while it is down, then restart it.
	if err := c.nodes[1].n.Propose(bg, []byte(freshPayload)); err != nil {
		t.Fatalf("propose before stop: %v", err)
	}
	c.waitUntil("first payload committed everywhere", func() bool { return len(c.nodesWithPayload(freshPayload)) == 3 })
	commitBefore := c.nodes[2].n.Status().GetCommit()
	appliedBefore := c.nodes[2].n.Status().Applied
	c.nodes[2].n.Stop()
	// Commit an entry while node 2 is down, so recovery must fetch it from the
	// leader rather than re-apply what the storage already holds.
	if err := c.nodes[1].n.Propose(bg, []byte(downPayload)); err != nil {
		t.Fatalf("propose while down: %v", err)
	}
	c.waitUntil("payload committed while node 2 is down", func() bool {
		return len(c.nodesWithPayload(downPayload)) > 0
	})
	c.restart(2)
	// Advance the logical clock so the leader issues heartbeats; without traffic
	// a restarted member would have no way to learn the current leader.
	for round := 0; round < 10; round++ {
		for id := range c.nodes {
			c.nodes[id].n.Tick()
		}
		time.Sleep(20 * time.Millisecond)
	}
	emitAssurance(t, "node_restarted", map[string]any{
		"operation_id": opRestart, "node": 2, "commit_before": int(commitBefore),
		"applied_before": int(appliedBefore), "leader": c.nodes[1].n.Status().SoftState.Lead,
		"payload_down": downPayload,
	})
	c.waitUntil("restarted node sees leader 1", func() bool { return c.nodes[2].n.Status().SoftState.Lead == 1 })
	c.waitUntil("restarted node recovered the payload committed while it was down", func() bool {
		return payloadPresent(c.appliedEntries(2), downPayload)
	})
	recovered := payloadPresent(c.appliedEntries(2), downPayload)
	emitAssurance(t, "restart_recovery", map[string]any{
		"operation_id": opRestart, "node": 2, "payload": downPayload,
		"recovered": recovered, "commit_after": int(c.nodes[2].n.Status().GetCommit()),
		"applied_after": int(c.nodes[2].n.Status().Applied),
		"leader":        c.nodes[2].n.Status().SoftState.Lead,
		"observed_nodes": c.nodesWithPayload(freshPayload),
	})
	// The restarted member relearns the leader, so its proposal gate is armed
	// again and it can propose.
	ctx, cancel := context.WithTimeout(bg, 3*time.Second)
	defer cancel()
	err := c.nodes[2].n.Propose(ctx, []byte(recoveredPayload))
	emitAssurance(t, "restart_propose", map[string]any{
		"operation_id": opRestart, "node": 2, "returned": true, "err": assuranceErrf(err),
		"leader": c.nodes[2].n.Status().SoftState.Lead,
	})
	c.waitUntil("restarted node's proposal committed", func() bool {
		return len(c.nodesWithPayload(recoveredPayload)) > 0
	})
	emitAssurance(t, "restart_propose_commit", map[string]any{
		"operation_id": opRestart, "node": 2, "payload": recoveredPayload,
		"present": len(c.nodesWithPayload(recoveredPayload)) > 0,
		"observed_nodes": c.nodesWithPayload(recoveredPayload),
	})
}

// gate: while the local member is still a participant of the configuration
// (here as a voter in the outgoing half of a joint config that is not left),
// its proposals are accepted and committed, so the held-proposal effect needs
// the disappearance of the local Progress entry rather than any conf change.
func TestAssuranceJointMembershipPropose(t *testing.T) {
	const opJoint = "joint-member-propose"
	const payload = "joint-member-payload"
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

	// Joint-explicit removal, so the configuration stays joint and the member
	// keeps a progress entry as an outgoing voter.
	jointRemove := &pb.ConfChangeV2{
		Transition: pb.ConfChangeTransitionJointExplicit.Enum(),
		Changes: []*pb.ConfChangeSingle{{
			Type: pb.ConfChangeRemoveNode.Enum(), NodeId: new(uint64(3)),
		}},
	}
	emitAssurance(t, "joint_conf_change_proposed", map[string]any{
		"operation_id": opJoint, "node": 1, "change": "remove", "target": 3,
		"transition": "joint_explicit",
	})
	if err := c.nodes[1].n.ProposeConfChange(bg, jointRemove); err != nil {
		t.Fatalf("propose joint remove: %v", err)
	}
	c.waitUntil("node 3 is an outgoing voter", func() bool {
		_, ok := c.nodes[3].n.Status().Config.Voters[1][3]
		return ok
	})
	outgoing := func() bool {
		_, ok := c.nodes[3].n.Status().Config.Voters[1][3]
		return ok
	}
	emitAssurance(t, "joint_membership", map[string]any{
		"operation_id": opJoint, "node": 3, "outgoing": outgoing(),
		"voter": assuranceVoter(c.nodes[3].n, 3), "leader": c.nodes[3].n.Status().SoftState.Lead,
		"term": c.nodes[3].n.Status().GetTerm(), "phase": "joint_no_leave",
	})
	emitAssurance(t, "jointpropose_invocation", map[string]any{
		"operation_id": opJoint, "node": 3, "phase": "joint_no_leave",
		"leader": c.nodes[3].n.Status().SoftState.Lead, "voter": assuranceVoter(c.nodes[3].n, 3),
		"deadline_ms": 3000, "payload": payload,
	})
	ctxP, cancelP := context.WithTimeout(bg, 3*time.Second)
	defer cancelP()
	startP := time.Now()
	pErr := c.nodes[3].n.Propose(ctxP, []byte(payload))
	emitAssurance(t, "jointpropose_result", map[string]any{
		"operation_id": opJoint, "node": 3, "phase": "joint_no_leave",
		"returned": true, "err": assuranceErrf(pErr),
		"elapsed_ms": int(time.Since(startP).Milliseconds()), "deadline_ms": 3000,
		"voter": assuranceVoter(c.nodes[3].n, 3), "outgoing": outgoing(),
		"leader": c.nodes[3].n.Status().SoftState.Lead, "payload": payload,
	})
	c.waitUntil("joint payload committed", func() bool {
		return len(c.nodesWithPayload(payload)) > 0
	})
	emitAssurance(t, "jointpropose_commit", map[string]any{
		"operation_id": opJoint, "payload": payload,
		"present": len(c.nodesWithPayload(payload)) > 0,
		"observed_nodes": c.nodesWithPayload(payload),
	})
}

// TestAssuranceRandomizedSafety explores safety invariants of the captured
// snapshot with real raft state machines, in-memory storage, random ticks,
// message loss, partition changes, elections, proposals and leader transfers.
// It reports, for every explored seed, what was exercised and whether any
// invariant monitor observed a violation.
func TestAssuranceRandomizedSafety(t *testing.T) {
	type entrySnapshot struct {
		term uint64
		data string
	}
	seeds := []int64{11, 23}
	const nodeCount = 3
	const steps = 300
	for _, seed := range seeds {
		rng := rand.New(rand.NewSource(seed))
		rafts := make([]*raft, 0, nodeCount)
		for i := uint64(1); i <= nodeCount; i++ {
			rafts = append(rafts, newTestRaft(i, 10, 1, newTestMemoryStorage(withPeers(1, 2, 3))))
		}
		appliedPerNode := make([]map[uint64]entrySnapshot, nodeCount)
		for i := range appliedPerNode {
			appliedPerNode[i] = map[uint64]entrySnapshot{}
		}
		appliedAnywhere := map[uint64]entrySnapshot{}
		leaderOfTerm := map[uint64]uint64{}
		reach := make([]uint64, nodeCount)
		for i := range reach {
			reach[i] = 0b111
		}
		var queue []*pb.Message
		proposals, campaigns, transfers, confChanges, delivered, dropped := 0, 0, 0, 0, 0, 0
		confChangeAttempts := 0
		violations := 0
		lastCommitted := make([]uint64, nodeCount)
		wasLeader := make([]bool, nodeCount)
		payload := 0

		note := func(violation, detail string) {
			violations++
			emitAssurance(t, "safety_violation", map[string]any{
				"operation_id": fmt.Sprintf("explore-%d", seed), "seed": seed,
				"invariant": violation, "detail": detail, "step": delivered,
			})
		}

		for step := 0; step < steps; step++ {
			if rng.Intn(25) == 0 {
				for i := range reach {
					reach[i] = uint64(rng.Intn(1 << nodeCount))
				}
			}
			for tick := 0; tick < rng.Intn(3); tick++ {
				for _, r := range rafts {
					r.tick()
				}
			}
			if rng.Intn(3) == 0 {
				id := uint64(1 + rng.Intn(nodeCount))
				r := rafts[id-1]
				if r.trk.Progress[r.id] != nil {
					payload++
					proposals++
					_ = r.Step(&pb.Message{Type: pb.MsgProp.Enum(), From: new(id),
						Entries: []*pb.Entry{{Data: []byte(fmt.Sprintf("payload-%d-%d", seed, payload))}}})
				}
			}
			if rng.Intn(30) == 0 {
				id := uint64(1 + rng.Intn(nodeCount))
				campaigns++
				_ = rafts[id-1].Step(&pb.Message{Type: pb.MsgHup.Enum()})
			}
			if rng.Intn(30) == 0 {
				id := uint64(1 + rng.Intn(nodeCount))
				to := uint64(1 + rng.Intn(nodeCount))
				transfers++
				_ = rafts[id-1].Step(&pb.Message{Type: pb.MsgTransferLeader.Enum(), From: new(to)})
			}
			if rng.Intn(12) == 0 {
				id := uint64(1 + rng.Intn(nodeCount))
				r := rafts[id-1]
				confChangeAttempts++
				if r.state == StateLeader && r.trk.Progress[r.id] != nil {
					learner := uint64(10 + rng.Intn(2))
					var cc pb.ConfChangeI
					switch rng.Intn(3) {
					case 0:
						cc = &pb.ConfChangeV2{Changes: []*pb.ConfChangeSingle{{
							Type: pb.ConfChangeAddLearnerNode.Enum(), NodeId: new(learner)}}}
					case 1:
						cc = &pb.ConfChangeV2{Changes: []*pb.ConfChangeSingle{{
							Type: pb.ConfChangeRemoveNode.Enum(), NodeId: new(learner)}}}
					default:
						typ := pb.ConfChangeRemoveNode
						if _, isVoter := r.trk.Config.Voters[0][3]; !isVoter {
							typ = pb.ConfChangeAddNode
						}
						cc = &pb.ConfChangeV2{Changes: []*pb.ConfChangeSingle{{
							Type: typ.Enum(), NodeId: new(uint64(3))}}}
					}
					entryType, data, err := pb.MarshalConfChange(cc)
					if err == nil {
						confChanges++
						_ = r.Step(&pb.Message{Type: pb.MsgProp.Enum(), From: new(id),
							Entries: []*pb.Entry{{Type: entryType.Enum(), Data: data}}})
					}
				}
			}

			// collect outbound messages
			for i, r := range rafts {
				r.advanceMessagesAfterAppend()
				msgs := r.readMessages()
				for _, m := range msgs {
					to := m.GetTo()
					if to < 1 || to > nodeCount {
						continue
					}
					from, target := uint64(i+1), to
					if reach[from-1]&(1<<(target-1)) == 0 || rng.Intn(10) == 0 {
						dropped++
						continue
					}
					queue = append(queue, m)
				}
			}
			// deliver a random prefix of the queue
			rng.Shuffle(len(queue), func(a, b int) { queue[a], queue[b] = queue[b], queue[a] })
			batch := len(queue)
			if batch > 3 {
				batch = 3
			}
			for _, m := range queue[:batch] {
				delivered++
				_ = rafts[m.GetTo()-1].Step(m)
			}
			queue = queue[batch:]

			// persist and apply, then check monitors
			for i, r := range rafts {
				r.advanceMessagesAfterAppend()
				ents := r.raftLog.nextCommittedEnts(true)
				for _, e := range ents {
					idx := e.GetIndex()
					snap := entrySnapshot{term: e.GetTerm(), data: string(e.GetData())}
					if prior, ok := appliedPerNode[i][idx]; ok && prior != snap {
						note("applied_entry_changed", fmt.Sprintf("node %d index %d was %+v and became %+v", i+1, idx, prior, snap))
					}
					appliedPerNode[i][idx] = snap
					if prior, ok := appliedAnywhere[idx]; ok && prior != snap {
						note("committed_entry_conflict", fmt.Sprintf("index %d was %+v on another node and is %+v on node %d", idx, prior, snap, i+1))
					}
					appliedAnywhere[idx] = snap
					switch e.GetType() {
					case pb.EntryConfChange, pb.EntryConfChangeV2:
						cc := &pb.ConfChangeV2{}
						if e.GetType() == pb.EntryConfChange {
							v1 := &pb.ConfChange{}
							if proto.Unmarshal(e.GetData(), v1) == nil {
								cc = v1.AsV2()
							}
						} else if err := proto.Unmarshal(e.GetData(), cc); err != nil {
							note("conf_change_unmarshal", fmt.Sprintf("node %d index %d: %v", i+1, idx, err))
							continue
						}
						func() {
							defer func() {
								if rec := recover(); rec != nil {
									note("conf_change_apply_panic", fmt.Sprintf("node %d index %d: %v", i+1, idx, rec))
								}
							}()
							r.applyConfChange(cc)
						}()
					}
				}
				if len(ents) > 0 {
					r.raftLog.appliedTo(r.raftLog.committed, 0)
				}
				if r.raftLog.committed < lastCommitted[i] {
					note("commit_regressed", fmt.Sprintf("node %d committed went from %d to %d", i+1, lastCommitted[i], r.raftLog.committed))
				}
				lastCommitted[i] = r.raftLog.committed
				if r.state == StateLeader {
					if other, ok := leaderOfTerm[r.Term]; ok && other != r.id {
						note("two_leaders_in_term", fmt.Sprintf("term %d claimed by %d and %d", r.Term, other, r.id))
					}
					leaderOfTerm[r.Term] = r.id
					// Completeness is owed by a newly elected leader for entries
					// committed before its election; a stale partitioned leader
					// that has not yet seen the higher term owes nothing.
					if !wasLeader[i] {
						for idx, snap := range appliedAnywhere {
							if !r.raftLog.matchTerm(entryID{term: snap.term, index: idx}) {
								note("leader_missing_committed_entry", fmt.Sprintf("new leader %d at term %d lacks index %d term %d", r.id, r.Term, idx, snap.term))
							}
						}
					}
					wasLeader[i] = true
				} else {
					wasLeader[i] = false
				}
			}
		}
		emitAssurance(t, "exploration_summary", map[string]any{
			"operation_id": fmt.Sprintf("explore-%d", seed), "seed": seed, "steps": steps,
			"nodes": nodeCount, "proposals": proposals, "campaigns": campaigns,
			"transfers": transfers, "delivered": delivered, "dropped": dropped,
			"conf_changes": confChanges,
			"conf_change_attempts": confChangeAttempts,
			"applied_indexes": len(appliedAnywhere), "violations": violations,
		})
	}
}
