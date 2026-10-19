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
		// The bootstrap membership entries are committed by construction. The
		// application-owned RSM would confirm them as applied before normal use.
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

func findMessage(messages []pb.Message, messageType pb.MessageType, to uint64, hint uint64) (pb.Message, bool) {
	for _, message := range messages {
		if message.Type == messageType && message.To == to && (hint == 0 || message.Hint == hint) {
			return message, true
		}
	}
	return pb.Message{}, false
}

func emitNodeHostAssuranceEvent(t *testing.T, event map[string]interface{}) {
	t.Helper()
	b, err := json.Marshal(event)
	if err != nil {
		t.Fatalf("failed to marshal assurance event: %v", err)
	}
	t.Logf("CA_EVENT %s", b)
}

func TestAssuranceReadIndexReplyIdentityAndCompletion(t *testing.T) {
	c := newAssuranceCluster(t)

	// Tick only the first peer until its term's no-op is committed. The other
	// peers participate in the election and replication through real handlers.
	for i := 0; i < 100 && c.commit[1] < uint64(4); i++ {
		c.peers[1].Tick()
		c.drain(c.pump(1))
	}
	if c.commit[1] < 4 {
		t.Fatalf("leader failed to commit its current-term no-op, commit=%d", c.commit[1])
	}

	pool := &sync.Pool{New: func() interface{} { return &RequestState{} }}
	reads2 := newPendingReadIndex(pool, newReadIndexQueue(16))
	reads3 := newPendingReadIndex(pool, newReadIndexQueue(16))
	req2, err := reads2.read(50)
	if err != nil {
		t.Fatalf("failed to create node 2 read: %v", err)
	}
	req3, err := reads3.read(50)
	if err != nil {
		t.Fatalf("failed to create node 3 read: %v", err)
	}
	ctxA := reads2.nextCtx()
	ctxB := reads3.nextCtx()
	reads2.add(ctxA, []*RequestState{req2})
	reads3.add(ctxB, []*RequestState{req3})

	// Node 2's real Raft peer forwards its ReadIndex request to leader 1.
	c.peers[2].ReadIndex(ctxA)
	leaderMessagesA := c.deliverTo(1, c.pump(2))
	// Node 3's real Raft peer queues a later request at the leader.
	c.peers[3].ReadIndex(ctxB)
	leaderMessagesB := c.deliverTo(1, c.pump(3))
	if len(leaderMessagesA)+len(leaderMessagesB) == 0 {
		t.Fatal("leader did not produce heartbeat/confirmation messages")
	}

	emitNodeHostAssuranceEvent(t, map[string]interface{}{
		"event":      "readindex_requested",
		"request_id": "node2-read-A",
		"node_id":    uint64(2),
		"leader_id":  uint64(1),
		"ctx_low":    ctxA.Low,
		"ctx_high":   ctxA.High,
	})
	emitNodeHostAssuranceEvent(t, map[string]interface{}{
		"event":      "readindex_requested",
		"request_id": "node3-read-B",
		"node_id":    uint64(3),
		"leader_id":  uint64(1),
		"ctx_low":    ctxB.Low,
		"ctx_high":   ctxB.High,
	})

	// Deliver the newer heartbeat B to its follower and return the real
	// confirmation to the leader before delivering the earlier heartbeat A to
	// node 2. Heartbeats can be reordered; both carry the same leader term.
	heartbeatB, ok := findMessage(leaderMessagesB, pb.Heartbeat, 3, ctxB.Low)
	if !ok {
		t.Fatalf("no heartbeat carrying the later context was sent to node 3; messages=%+v", leaderMessagesB)
	}
	confirmMessages := c.deliver(heartbeatB)
	if _, ok := findMessage(confirmMessages, pb.HeartbeatResp, 1, ctxB.Low); !ok {
		t.Fatalf("node 3 did not confirm the later context; messages=%+v", confirmMessages)
	}
	leaderReplies := c.deliverTo(1, confirmMessages)
	if len(leaderReplies) == 0 {
		t.Fatal("leader produced no output after the later-context confirmation")
	}

	node2Reply, ok := findMessage(leaderReplies, pb.ReadIndexResp, 2, 0)
	if !ok {
		t.Fatalf("no ReadIndex response was produced for node 2; messages=%+v", leaderReplies)
	}
	emitNodeHostAssuranceEvent(t, map[string]interface{}{
		"event":                "readindex_reply",
		"request_id":           "node2-read-A",
		"reply_to":             node2Reply.To,
		"trigger_from":         uint64(3),
		"trigger_ctx_low":      ctxB.Low,
		"trigger_ctx_high":     ctxB.High,
		"response_ctx_low":     node2Reply.Hint,
		"response_ctx_high":    node2Reply.HintHigh,
		"response_log_index":   node2Reply.LogIndex,
		"leader_pending_after": int64(0),
	})

	// Feed the produced response through node 2's real follower handler and the
	// actual pending-read consumer.
	replyOutputs := c.deliver(node2Reply)
	_ = replyOutputs
	reads2.addReady(c.ready[2])
	batch, exists := reads2.batches[ctxA]
	batchIndex := uint64(0)
	if exists {
		batchIndex = batch.index
	}
	appliedIndex := uint64(0)
	if len(c.ready[2]) > 0 {
		appliedIndex = c.ready[2][0].Index
	}
	readyIndexApplied := appliedIndex > 0 && appliedIndex == c.ready[2][0].Index
	reads2.applied(appliedIndex)
	completed := 0
	select {
	case <-req2.CompletedC:
		completed = 1
	default:
	}
	emitNodeHostAssuranceEvent(t, map[string]interface{}{
		"event":                    "read_completion_state",
		"request_id":               "node2-read-A",
		"response_batch_present":   func() bool { _, ok := reads2.batches[ctxB]; return ok }(),
		"original_batch_exists":    exists,
		"original_batch_index":     batchIndex,
		"ready_index":              appliedIndex,
		"applied_index":            appliedIndex,
		"ready_index_applied":      readyIndexApplied,
		"completed_after_response": completed,
	})

	// The earlier A confirmation reaches the leader later. The queue entry was
	// already consumed by the B confirmation, so it cannot repair node 2's
	// outstanding batch through this path.
	heartbeatA, ok := findMessage(leaderMessagesA, pb.Heartbeat, 2, ctxA.Low)
	if ok {
		lateConfirms := c.deliver(heartbeatA)
		lateOutputs := c.deliverTo(1, lateConfirms)
		correct := 0
		for _, message := range lateOutputs {
			if message.Type == pb.ReadIndexResp && message.To == 2 &&
				message.Hint == ctxA.Low && message.HintHigh == ctxA.High {
				correct++
			}
		}
		emitNodeHostAssuranceEvent(t, map[string]interface{}{
			"event":                       "late_confirmation_processed",
			"request_id":                  "node2-read-A",
			"context_correct_reply_count": correct,
			"completed_after_late_reply": func() int {
				select {
				case <-req2.CompletedC:
					return 1
				default:
					return 0
				}
			}(),
		})
	}
}
