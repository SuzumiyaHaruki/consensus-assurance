package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"
	"testing"
	"time"
)

func caEvent(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

// countingTrans counts InstallSnapshot calls the leader makes to its peers.
type countingTrans struct {
	*InmemTransport
	mu    sync.Mutex
	snaps int
}

func (c *countingTrans) InstallSnapshot(id ServerID, target ServerAddress, args *InstallSnapshotRequest, resp *InstallSnapshotResponse, data io.Reader) error {
	c.mu.Lock()
	c.snaps++
	c.mu.Unlock()
	return c.InmemTransport.InstallSnapshot(id, target, args, resp, data)
}

func (c *countingTrans) SnapshotCount() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.snaps
}

func waitState(t *testing.T, r *Raft, want RaftState, limit time.Duration) bool {
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if r.State() == want {
			return true
		}
		time.Sleep(5 * time.Millisecond)
	}
	return false
}

func TestAssurance_SnapshotBoundaryLoop(t *testing.T) {
	for _, stale := range []bool{false, true} {
		t.Run(fmt.Sprintf("stale_index_entry=%v", stale), func(t *testing.T) {
			// --- Leader A: single-voter cluster, becomes leader on its own.
			addrA, rawA := NewInmemTransport("server-A")
			transA := &countingTrans{InmemTransport: rawA}
			confA := inmemConfig(t)
			confA.LocalID = ServerID("server-A")
			confA.ProtocolVersion = 3
			confA.TrailingLogs = 0
			confA.SnapshotThreshold = 1 << 20
			confA.SnapshotInterval = time.Hour
			storeA := NewInmemStore()
			snapsA := NewInmemSnapshotStore()
			fsmA := &MockFSM{}
			cfgA := Configuration{Servers: []Server{{Suffrage: Voter, ID: ServerID("server-A"), Address: addrA}}}
			if err := BootstrapCluster(confA, storeA, storeA, snapsA, transA, cfgA); err != nil {
				t.Fatalf("bootstrap A: %v", err)
			}
			leader, err := NewRaft(confA, fsmA, storeA, storeA, snapsA, transA)
			if err != nil {
				t.Fatalf("NewRaft A: %v", err)
			}
			defer leader.Shutdown()
			if !waitState(t, leader, Leader, 5*time.Second) {
				t.Fatalf("A never became leader")
			}
			for i := 0; i < 6; i++ {
				if err := leader.Apply([]byte(fmt.Sprintf("cmd-%d", i)), 2*time.Second).Error(); err != nil {
					t.Fatalf("apply: %v", err)
				}
			}
			sf := leader.Snapshot()
			if err := sf.Error(); err != nil {
				t.Fatalf("snapshot: %v", err)
			}
			meta, rc, err := sf.Open()
			if err != nil {
				t.Fatalf("snapshot open: %v", err)
			}
			snapIdx := meta.Index
			rc.Close()
			firstA, _ := storeA.FirstIndex()
			caEvent(map[string]interface{}{"event": "leader_snapshot", "snapshot_index": snapIdx, "leader_first_index": firstA,
				"leader_last_index": leader.LastIndex(), "leader_commit_index": leader.CommitIndex()})

			// --- Follower B: Nonvoter in A's configuration so it never campaigns.
			addrB, rawB := NewInmemTransport("server-B")
			confB := inmemConfig(t)
			confB.LocalID = ServerID("server-B")
			confB.ProtocolVersion = 3
			confB.SnapshotThreshold = 1 << 20
			confB.SnapshotInterval = time.Hour
			storeB := NewInmemStore()
			snapsB := NewInmemSnapshotStore()
			fsmB := &MockFSM{}
			cfgB := Configuration{Servers: []Server{
				{Suffrage: Voter, ID: ServerID("server-A"), Address: addrA},
				{Suffrage: Nonvoter, ID: ServerID("server-B"), Address: addrB},
			}}
			if err := BootstrapCluster(confB, storeB, storeB, snapsB, rawB, cfgB); err != nil {
				t.Fatalf("bootstrap B: %v", err)
			}
			follower, err := NewRaft(confB, fsmB, storeB, storeB, snapsB, rawB)
			if err != nil {
				t.Fatalf("NewRaft B: %v", err)
			}
			defer follower.Shutdown()
			time.Sleep(50 * time.Millisecond)

			// Seed B with earlier-term (term 1) entries up to snapIdx (defect)
			// or snapIdx-1 (control), delivered as a legal AppendEntries.
			target := snapIdx
			if !stale {
				target = snapIdx - 1
			}
			addrD, rawD := NewInmemTransport("dummy")
			rawD.Connect(addrB, rawB)
			rawB.Connect(addrD, rawD)
			var entries []*Log
			for i := uint64(2); i <= target; i++ {
				entries = append(entries, &Log{Index: i, Term: 1, Type: LogCommand, Data: []byte("old")})
			}
			encA := rawD.EncodePeer("server-A", addrA)
			seed := &AppendEntriesRequest{
				RPCHeader:         RPCHeader{ProtocolVersion: 3, ID: []byte("server-A"), Addr: encA},
				Term:              1,
				Leader:            encA,
				PrevLogEntry:      1,
				PrevLogTerm:       1,
				Entries:           entries,
				LeaderCommitIndex: 1,
			}
			var seedResp AppendEntriesResponse
			if err := rawD.AppendEntries(ServerID("server-B"), addrB, seed, &seedResp); err != nil {
				t.Fatalf("seed: %v", err)
			}
			if !seedResp.Success {
				t.Fatalf("seed rejected: %+v", seedResp)
			}
			time.Sleep(50 * time.Millisecond)

			// --- Connect A and B, then add B as a voter of A.
			rawA.Connect(addrB, rawB)
			rawB.Connect(addrA, rawA)
			_ = leader.AddVoter(ServerID("server-B"), addrB, 0, time.Second)

			time.Sleep(300 * time.Millisecond)
			early := transA.SnapshotCount()
			time.Sleep(1200 * time.Millisecond)
			late := transA.SnapshotCount()
			caEvent(map[string]interface{}{
				"event": "loop_observe", "stale_index_entry": stale,
				"snapshot_index": snapIdx, "install_snapshot_calls_early": early, "install_snapshot_calls_late": late,
				"follower_applied_index": follower.AppliedIndex(), "follower_last_index": follower.LastIndex(),
				"leader_last_index": leader.LastIndex(), "leader_commit_index": leader.CommitIndex(),
			})
		})
	}
}
