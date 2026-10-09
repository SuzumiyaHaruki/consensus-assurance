package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"
)

// assuranceSpyTransport records the snapshot chosen by the leader's send path
// instead of forwarding the InstallSnapshot RPC to a peer.
type assuranceSpyTransport struct {
	*InmemTransport
	sent         bool
	sentIndex    uint64
	sentTerm     uint64
	sentSnapshot string
}

func (t *assuranceSpyTransport) InstallSnapshot(id ServerID, target ServerAddress, args *InstallSnapshotRequest,
	resp *InstallSnapshotResponse, data io.Reader) error {
	t.sent = true
	t.sentIndex = args.LastLogIndex
	t.sentTerm = args.LastLogTerm
	resp.Term = args.Term
	resp.Success = true
	return nil
}

type assuranceFSM3 struct{}

func (assuranceFSM3) Apply(*Log) interface{}         { return nil }
func (assuranceFSM3) Snapshot() (FSMSnapshot, error) { return assuranceSnapshot3{}, nil }
func (assuranceFSM3) Restore(io.ReadCloser) error    { return nil }

type assuranceSnapshot3 struct{}

func (assuranceSnapshot3) Persist(sink SnapshotSink) error { return sink.Close() }
func (assuranceSnapshot3) Release()                        {}

func assuranceEmit(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

func assuranceSeedSnapshot(t *testing.T, store *FileSnapshotStore, term, index uint64, cfg Configuration, trans Transport) {
	t.Helper()
	sink, err := store.Create(1, index, term, cfg, 1, trans)
	if err != nil {
		t.Fatalf("create snapshot (term=%d index=%d): %v", term, index, err)
	}
	if _, err := sink.Write([]byte("state")); err != nil {
		t.Fatalf("write snapshot: %v", err)
	}
	if err := sink.Close(); err != nil {
		t.Fatalf("close snapshot: %v", err)
	}
}

// TestAssuranceLeaderShipsNewestSnapshot checks the other consumer of the
// SnapshotStore order: the leader's sendLatestSnapshot chooses snapshots[0].
func TestAssuranceLeaderShipsNewestSnapshot(t *testing.T) {
	node := "n1"
	dir := t.TempDir()
	snaps, err := NewFileSnapshotStore(dir, 2, nil)
	if err != nil {
		t.Fatalf("NewFileSnapshotStore: %v", err)
	}
	base, trans := NewInmemTransport(NewInmemAddr())
	spy := &assuranceSpyTransport{InmemTransport: trans}
	cfg := Configuration{}
	assuranceSeedSnapshot(t, snaps, 9, 50, cfg, spy)
	assuranceSeedSnapshot(t, snaps, 4, 80, cfg, spy)
	metas, err := snaps.List()
	if err != nil {
		t.Fatalf("List: %v", err)
	}
	maxIndex := metas[0].Index
	for _, m := range metas {
		if m.Index > maxIndex {
			maxIndex = m.Index
		}
	}

	store := NewInmemStore()
	conf := DefaultConfig()
	conf.LocalID = ServerID(node)
	conf.ProtocolVersion = 3
	conf.HeartbeatTimeout = 100 * time.Millisecond
	conf.ElectionTimeout = 100 * time.Millisecond
	conf.LeaderLeaseTimeout = 100 * time.Millisecond
	conf.CommitTimeout = 5 * time.Millisecond
	conf.SnapshotThreshold = 100000
	conf.skipStartup = true

	r, err := NewRaft(conf, assuranceFSM3{}, store, store, snaps, spy)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}
	r.setState(Leader)
	r.setupLeaderState()
	repl := &followerReplication{
		peer:        Server{ID: "n2", Address: base},
		currentTerm: 5,
		commitment:  r.leaderState.commitment,
	}
	if _, err := r.sendLatestSnapshot(repl); err != nil {
		t.Fatalf("sendLatestSnapshot: %v", err)
	}
	newestSent := spy.sent && spy.sentIndex == maxIndex

	assuranceEmit(map[string]interface{}{
		"event": "snapshots_prepared", "node": node,
		"retained": len(metas), "max_index": maxIndex, "first_listed_index": metas[0].Index,
	})
	assuranceEmit(map[string]interface{}{
		"event": "snapshot_sent", "node": node,
		"sent": spy.sent, "sent_index": spy.sentIndex, "sent_term": spy.sentTerm,
		"max_index": maxIndex, "newest_sent": newestSent,
	})
}
