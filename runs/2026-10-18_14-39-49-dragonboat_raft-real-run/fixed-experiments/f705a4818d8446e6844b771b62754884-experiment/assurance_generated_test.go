package dragonboat

import (
	"encoding/json"
	"errors"
	"math"
	"sync"
	"testing"

	"github.com/lni/dragonboat/v3/config"
	dragonraft "github.com/lni/dragonboat/v3/internal/raft"
	pb "github.com/lni/dragonboat/v3/raftpb"
)

var (
	errAssuranceCompacted   = errors.New("assurance log compacted")
	errAssuranceOutOfDate   = errors.New("assurance snapshot out of date")
	errAssuranceUnavailable = errors.New("assurance log unavailable")
)

type assuranceLogDB struct {
	entries     []pb.Entry
	markerIndex uint64
	markerTerm  uint64
	snapshot    pb.Snapshot
	state       pb.State
}

func newAssuranceLogDB() *assuranceLogDB {
	return &assuranceLogDB{}
}

func (db *assuranceLogDB) firstIndex() uint64 {
	return db.markerIndex + 1
}

func (db *assuranceLogDB) lastIndex() uint64 {
	return db.markerIndex + uint64(len(db.entries))
}

func (db *assuranceLogDB) GetRange() (uint64, uint64) {
	return db.firstIndex(), db.lastIndex()
}

func (db *assuranceLogDB) SetRange(index uint64, length uint64) {}

func (db *assuranceLogDB) NodeState() (pb.State, pb.Membership) {
	return db.state, db.snapshot.Membership
}

func (db *assuranceLogDB) SetState(state pb.State) {
	db.state = state
}

func (db *assuranceLogDB) CreateSnapshot(snapshot pb.Snapshot) error {
	if db.snapshot.Index >= snapshot.Index {
		return errAssuranceOutOfDate
	}
	db.snapshot = snapshot
	return nil
}

func (db *assuranceLogDB) ApplySnapshot(snapshot pb.Snapshot) error {
	if db.snapshot.Index >= snapshot.Index {
		return errAssuranceOutOfDate
	}
	db.snapshot = snapshot
	db.markerIndex = snapshot.Index
	db.markerTerm = snapshot.Term
	db.entries = nil
	return nil
}

func (db *assuranceLogDB) Term(index uint64) (uint64, error) {
	if index == 0 {
		return 0, nil
	}
	if index == db.markerIndex {
		return db.markerTerm, nil
	}
	if index < db.firstIndex() {
		return 0, errAssuranceCompacted
	}
	if index > db.lastIndex() {
		return 0, errAssuranceUnavailable
	}
	return db.entries[index-db.firstIndex()].Term, nil
}

func (db *assuranceLogDB) Entries(low uint64, high uint64, maxSize uint64) ([]pb.Entry, error) {
	if low <= db.markerIndex {
		return nil, errAssuranceCompacted
	}
	if high > db.lastIndex()+1 {
		return nil, errAssuranceUnavailable
	}
	if low >= high {
		return nil, nil
	}
	entries := append([]pb.Entry(nil), db.entries[low-db.firstIndex():high-db.firstIndex()]...)
	if maxSize == math.MaxUint64 || len(entries) == 0 {
		return entries, nil
	}
	total := 0
	for i := range entries {
		total += entries[i].SizeUpperLimit()
		if uint64(total) > maxSize {
			return entries[:i], nil
		}
	}
	return entries, nil
}

func (db *assuranceLogDB) Snapshot() pb.Snapshot {
	return db.snapshot
}

func (db *assuranceLogDB) Compact(index uint64) error {
	return nil
}

func (db *assuranceLogDB) Append(entries []pb.Entry) error {
	if len(entries) == 0 {
		return nil
	}
	offset := entries[0].Index - db.markerIndex
	if uint64(len(db.entries)+1) > offset {
		db.entries = db.entries[:offset-1]
	}
	db.entries = append(db.entries, entries...)
	return nil
}

type assuranceCluster struct {
	peers   map[uint64]*dragonraft.Peer
	logs    map[uint64]*assuranceLogDB
	applied map[uint64]uint64
	commit  map[uint64]uint64
	ready   map[uint64][]pb.ReadyToRead
}

func newAssuranceCluster(t *testing.T) *assuranceCluster {
	t.Helper()
	c := &assuranceCluster{
		peers:   make(map[uint64]*dragonraft.Peer),
		logs:    make(map[uint64]*assuranceLogDB),
		applied: make(map[uint64]uint64),
		commit:  make(map[uint64]uint64),
		ready:   make(map[uint64][]pb.ReadyToRead),
	}
	addresses := []dragonraft.PeerAddress{
		{NodeID: 1, Address: "assurance-1"},
		{NodeID: 2, Address: "assurance-2"},
		{NodeID: 3, Address: "assurance-3"},
	}
	for id := uint64(1); id <= 3; id++ {
		db := newAssuranceLogDB()
		cfg := config.Config{
			ClusterID:       7,
			NodeID:          id,
			ElectionRTT:     10,
			HeartbeatRTT:    1,
			MaxInMemLogSize: 0,
		}
		c.logs[id] = db
		c.peers[id] = dragonraft.Launch(cfg, db, nil, addresses, true, true)
		c.applied[id] = uint64(len(addresses))
		c.peers[id].NotifyRaftLastApplied(c.applied[id])
	}
	return c
}

func (c *assuranceCluster) pump(id uint64) []pb.Message {
	update := c.peers[id].GetUpdate(true, c.applied[id])
	c.ready[id] = append(c.ready[id], update.ReadyToReads...)
	if update.State.Commit > c.commit[id] {
		c.commit[id] = update.State.Commit
	}
	messages := append([]pb.Message(nil), update.Messages...)
	if len(update.EntriesToSave) > 0 {
		if err := c.logs[id].Append(update.EntriesToSave); err != nil {
			panic(err)
		}
	}
	c.peers[id].Commit(update)
	return messages
}

func (c *assuranceCluster) deliver(message pb.Message) []pb.Message {
	c.peers[message.To].Handle(message)
	return c.pump(message.To)
}

func (c *assuranceCluster) drain(messages []pb.Message) {
	queue := append([]pb.Message(nil), messages...)
	for len(queue) > 0 {
		message := queue[0]
		queue = queue[1:]
		queue = append(queue, c.deliver(message)...)
	}
}

func (c *assuranceCluster) deliverTo(id uint64, messages []pb.Message) []pb.Message {
	var produced []pb.Message
	for _, message := range messages {
		if message.To == id {
			produced = append(produced, c.deliver(message)...)
		}
	}
	return produced
}

func findAssuranceMessage(messages []pb.Message,
	messageType pb.MessageType, to uint64, hint uint64) (pb.Message, bool) {
	for _, message := range messages {
		if message.Type == messageType && message.To == to &&
			(hint == 0 || message.Hint == hint) {
			return message, true
		}
	}
	return pb.Message{}, false
}

func emitObserverEndpointEvent(t *testing.T, event map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("failed to marshal assurance event: %v", err)
	}
	t.Logf("CA_EVENT %s", b)
}

// registerAssuranceObserver records node 4 as an observer in every voter's
// raft membership, which is the state produced by an applied AddObserver
// config change.
func registerAssuranceObserver(t *testing.T, c *assuranceCluster) {
	t.Helper()
	for id := uint64(1); id <= 3; id++ {
		c.peers[id].ApplyConfigChange(pb.ConfigChange{
			Type:    pb.AddObserver,
			NodeID:  4,
			Address: "assurance-4",
		})
		if messages := c.pump(id); len(messages) > 0 {
			c.drain(messages)
		}
	}
	if c.commit[1] < 4 {
		t.Fatalf("observer registration disturbed the leader commit, commit=%d",
			c.commit[1])
	}
}

// newAssuranceObserver launches a real observer Raft peer for node 4. Its log
// DB carries the committed voter membership {1,2,3}, which is what an observer
// learns from the replicated bootstrap entries or a snapshot, and a leader
// heartbeat teaches it the current leader.
func newAssuranceObserver(t *testing.T) *dragonraft.Peer {
	t.Helper()
	db := newAssuranceLogDB()
	db.snapshot.Membership = pb.Membership{
		ConfigChangeId: 1,
		Addresses: map[uint64]string{
			1: "assurance-1",
			2: "assurance-2",
			3: "assurance-3",
		},
	}
	cfg := config.Config{
		ClusterID:       7,
		NodeID:          4,
		ElectionRTT:     10,
		HeartbeatRTT:    1,
		MaxInMemLogSize: 0,
		IsObserver:      true,
	}
	observer := dragonraft.Launch(cfg, db, nil, nil, false, true)
	observer.Handle(pb.Message{
		From: 1,
		To:   4,
		Type: pb.Heartbeat,
		Term: 1,
	})
	update := observer.GetUpdate(true, 0)
	observer.Commit(update)
	return observer
}

// admitObserverRead registers an observer-local ReadIndex request and returns
// the pending-read bookkeeping together with the ReadIndex message that the
// observer's real raft peer forwarded to its leader.
func admitObserverRead(t *testing.T, observer *dragonraft.Peer,
	reads *pendingReadIndex, req *RequestState,
	ctx pb.SystemCtx) pb.Message {
	t.Helper()
	reads.add(ctx, []*RequestState{req})
	observer.ReadIndex(ctx)
	update := observer.GetUpdate(true, 0)
	forwarded := append([]pb.Message(nil), update.Messages...)
	observer.Commit(update)
	message, ok := findAssuranceMessage(forwarded, pb.ReadIndex, 1, ctx.Low)
	if !ok {
		t.Fatalf("observer did not forward its ReadIndex request; messages=%+v",
			forwarded)
	}
	return message
}

// consumeObserverReady feeds the observer peer's real ReadyToRead output into
// the node-level pending read registry and returns the ready index.
func consumeObserverReady(t *testing.T, observer *dragonraft.Peer,
	reads *pendingReadIndex) []pb.ReadyToRead {
	t.Helper()
	update := observer.GetUpdate(true, 0)
	ready := append([]pb.ReadyToRead(nil), update.ReadyToReads...)
	observer.Commit(update)
	reads.addReady(ready)
	return ready
}

func completedFlag(req *RequestState) int {
	select {
	case <-req.CompletedC:
		return 1
	default:
		return 0
	}
}

func TestAssuranceObserverLocalReadIndexCompletion(t *testing.T) {
	c := newAssuranceCluster(t)
	for i := 0; i < 100 && c.commit[1] < uint64(4); i++ {
		c.peers[1].Tick()
		c.drain(c.pump(1))
	}
	if c.commit[1] < 4 {
		t.Fatalf("leader failed to commit its current-term no-op, commit=%d",
			c.commit[1])
	}
	registerAssuranceObserver(t, c)
	observer := newAssuranceObserver(t)

	pool := &sync.Pool{New: func() interface{} { return &RequestState{} }}
	reads4 := newPendingReadIndex(pool, newReadIndexQueue(16))
	req4, err := reads4.read(50)
	if err != nil {
		t.Fatalf("failed to create observer read: %v", err)
	}
	ctxA := reads4.nextCtx()
	ctxB := pb.SystemCtx{Low: 202, High: 2003}

	forwardedA := admitObserverRead(t, observer, reads4, req4, ctxA)
	emitObserverEndpointEvent(t, map[string]interface{}{
		"event":      "observer_local_readindex_forwarded",
		"request_id": "observer-read-A",
		"node_id":    uint64(4),
		"leader_id":  forwardedA.To,
		"ctx_low":    ctxA.Low,
		"ctx_high":   ctxA.High,
	})

	// The real leader admits the observer's forwarded request.
	leaderMessagesA := c.deliver(forwardedA)
	// A later voter-originated request is queued behind the observer's request.
	c.peers[3].ReadIndex(ctxB)
	leaderMessagesB := c.deliverTo(1, c.pump(3))
	if len(leaderMessagesB) == 0 {
		t.Fatal("leader produced no confirmation heartbeat for the later context")
	}
	emitObserverEndpointEvent(t, map[string]interface{}{
		"event":            "later_voter_readindex_queued",
		"request_id":       "voter-read-B",
		"node_id":          uint64(3),
		"leader_id":        uint64(1),
		"ctx_low":          ctxB.Low,
		"ctx_high":         ctxB.High,
		"admitted_ctx_low": ctxA.Low,
	})

	heartbeatB, ok := findAssuranceMessage(leaderMessagesB, pb.Heartbeat, 3, ctxB.Low)
	if !ok {
		t.Fatalf("no heartbeat carrying the later context was sent to node 3; messages=%+v",
			leaderMessagesB)
	}
	node3Output := c.deliver(heartbeatB)
	leaderReplies := c.deliverTo(1, node3Output)
	observerReply, ok := findAssuranceMessage(leaderReplies, pb.ReadIndexResp, 4, 0)
	if !ok {
		t.Fatalf("leader produced no ReadIndex response for observer 4; messages=%+v",
			leaderReplies)
	}
	emitObserverEndpointEvent(t, map[string]interface{}{
		"event":              "observer_readindex_reply",
		"request_id":         "observer-read-A",
		"reply_to":           observerReply.To,
		"admitted_ctx_low":   ctxA.Low,
		"admitted_ctx_high":  ctxA.High,
		"trigger_from":       uint64(3),
		"trigger_ctx_low":    ctxB.Low,
		"trigger_ctx_high":   ctxB.High,
		"response_ctx_low":   observerReply.Hint,
		"response_ctx_high":  observerReply.HintHigh,
		"response_log_index": observerReply.LogIndex,
	})

	// Feed the reply through the observer's real handler and the node-level
	// pending-read registry.
	observer.Handle(observerReply)
	ready := consumeObserverReady(t, observer, reads4)
	reads4.applied(observerReply.LogIndex)
	batch, exists := reads4.batches[ctxA]
	batchIndex := uint64(0)
	if exists {
		batchIndex = batch.index
	}
	readyCtxLow := uint64(0)
	readyIndex := uint64(0)
	if len(ready) > 0 {
		readyCtxLow = ready[0].SystemCtx.Low
		readyIndex = ready[0].Index
	}
	emitObserverEndpointEvent(t, map[string]interface{}{
		"event":                 "observer_read_completion_state",
		"request_id":            "observer-read-A",
		"ready_count":           len(ready),
		"ready_ctx_low":         readyCtxLow,
		"ready_index":           readyIndex,
		"applied_index":         observerReply.LogIndex,
		"original_batch_exists": exists,
		"original_batch_index":  batchIndex,
		"completed_after_reply": completedFlag(req4),
	})

	// A late confirmation of the observer's own context cannot repair it: the
	// leader already removed the queued entry.
	if heartbeatA, ok := findAssuranceMessage(
		leaderMessagesA, pb.Heartbeat, 2, ctxA.Low); ok {
		lateOutputs := c.deliverTo(1, c.deliver(heartbeatA))
		correct := 0
		for _, message := range lateOutputs {
			if message.Type == pb.ReadIndexResp && message.To == 4 &&
				message.Hint == ctxA.Low && message.HintHigh == ctxA.High {
				correct++
			}
		}
		emitObserverEndpointEvent(t, map[string]interface{}{
			"event":                       "observer_late_confirmation",
			"request_id":                  "observer-read-A",
			"context_correct_reply_count": correct,
			"completed_after_late_reply":  completedFlag(req4),
		})
	}
}

func TestAssuranceObserverLocalReadIndexControl(t *testing.T) {
	c := newAssuranceCluster(t)
	for i := 0; i < 100 && c.commit[1] < uint64(4); i++ {
		c.peers[1].Tick()
		c.drain(c.pump(1))
	}
	if c.commit[1] < 4 {
		t.Fatalf("leader failed to commit its current-term no-op, commit=%d",
			c.commit[1])
	}
	registerAssuranceObserver(t, c)
	observer := newAssuranceObserver(t)

	pool := &sync.Pool{New: func() interface{} { return &RequestState{} }}
	reads4 := newPendingReadIndex(pool, newReadIndexQueue(16))
	req4, err := reads4.read(50)
	if err != nil {
		t.Fatalf("failed to create observer read: %v", err)
	}
	ctxA := reads4.nextCtx()
	ctxB := pb.SystemCtx{Low: 202, High: 2003}

	forwardedA := admitObserverRead(t, observer, reads4, req4, ctxA)
	emitObserverEndpointEvent(t, map[string]interface{}{
		"event":      "control_observer_local_readindex_forwarded",
		"request_id": "control-observer-read-A",
		"node_id":    uint64(4),
		"leader_id":  forwardedA.To,
		"ctx_low":    ctxA.Low,
		"ctx_high":   ctxA.High,
	})
	leaderMessagesA := c.deliver(forwardedA)
	c.peers[3].ReadIndex(ctxB)
	_ = c.deliverTo(1, c.pump(3))

	// Confirm the observer's own admitted context first.
	heartbeatA, ok := findAssuranceMessage(leaderMessagesA, pb.Heartbeat, 2, ctxA.Low)
	if !ok {
		t.Fatalf("no heartbeat carrying the observer context was sent to node 2; messages=%+v",
			leaderMessagesA)
	}
	leaderReplies := c.deliverTo(1, c.deliver(heartbeatA))
	observerReply, ok := findAssuranceMessage(leaderReplies, pb.ReadIndexResp, 4, 0)
	if !ok {
		t.Fatalf("leader produced no ReadIndex response for observer 4; messages=%+v",
			leaderReplies)
	}
	emitObserverEndpointEvent(t, map[string]interface{}{
		"event":              "control_observer_readindex_reply",
		"request_id":         "control-observer-read-A",
		"reply_to":           observerReply.To,
		"admitted_ctx_low":   ctxA.Low,
		"admitted_ctx_high":  ctxA.High,
		"trigger_from":       uint64(2),
		"response_ctx_low":   observerReply.Hint,
		"response_ctx_high":  observerReply.HintHigh,
		"response_log_index": observerReply.LogIndex,
	})

	observer.Handle(observerReply)
	ready := consumeObserverReady(t, observer, reads4)
	reads4.applied(observerReply.LogIndex)
	batch, exists := reads4.batches[ctxA]
	batchIndex := uint64(0)
	if exists {
		batchIndex = batch.index
	}
	readyIndex := uint64(0)
	if len(ready) > 0 {
		readyIndex = ready[0].Index
	}
	emitObserverEndpointEvent(t, map[string]interface{}{
		"event":                 "control_observer_read_completion_state",
		"request_id":            "control-observer-read-A",
		"ready_count":           len(ready),
		"ready_index":           readyIndex,
		"applied_index":         observerReply.LogIndex,
		"original_batch_exists": exists,
		"original_batch_index":  batchIndex,
		"completed_after_reply": completedFlag(req4),
	})
}
