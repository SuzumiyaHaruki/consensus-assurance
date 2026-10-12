package raft

import (
	"bytes"
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func caEvent(m map[string]interface{}) {
	b, _ := json.Marshal(m)
	fmt.Println("CA_EVENT " + string(b))
}

// buildNode creates a node under test ("server-1") that is a Nonvoter in a
// configuration whose only Voter is a remote "server-2", so it never campaigns.
func buildNode(t *testing.T) (*Raft, *InmemTransport, ServerAddress) {
	addr1, trans1 := NewInmemTransport("server-1")
	addr2, trans2 := NewInmemTransport("server-2")
	trans1.Connect(addr2, trans2)
	trans2.Connect(addr1, trans1)

	conf := inmemConfig(t)
	conf.LocalID = ServerID("server-1")
	conf.ProtocolVersion = 3
	conf.SnapshotThreshold = 1 << 20
	conf.SnapshotInterval = time.Hour
	conf.skipStartup = false

	store := NewInmemStore()
	snaps := NewInmemSnapshotStore()
	fsm := &MockFSM{}

	configuration := Configuration{Servers: []Server{
		{Suffrage: Voter, ID: ServerID("server-2"), Address: addr2},
		{Suffrage: Nonvoter, ID: ServerID("server-1"), Address: addr1},
	}}
	if err := BootstrapCluster(conf, store, store, snaps, trans1, configuration); err != nil {
		t.Fatalf("bootstrap: %v", err)
	}
	r, err := NewRaft(conf, fsm, store, store, snaps, trans1)
	if err != nil {
		t.Fatalf("NewRaft: %v", err)
	}
	return r, trans2, addr1
}

func snapshotPayload(t *testing.T) []byte {
	buf, err := encodeMsgPack([][]byte{})
	if err != nil {
		t.Fatalf("encodeMsgPack: %v", err)
	}
	return buf.Bytes()
}

func TestAssurance_SnapshotBoundaryStaleEntry(t *testing.T) {
	for _, stale := range []bool{false, true} {
		name := fmt.Sprintf("stale_same_index_entry=%v", stale)
		t.Run(name, func(t *testing.T) {
			r, trans2, addr1 := buildNode(t)
			defer r.Shutdown()
			time.Sleep(50 * time.Millisecond) // let run()/runFSM() start

			id1 := ServerID("server-1")
			hdr := RPCHeader{ProtocolVersion: 3, ID: []byte("server-2"), Addr: trans2.EncodePeer("server-2", "server-2")}
			leader := trans2.EncodePeer("server-2", "server-2")

			// Step 1: a previous leader of term 2 stores a command at index 2.
			if stale {
				ae := &AppendEntriesRequest{
					RPCHeader:         hdr,
					Term:              2,
					Leader:            leader,
					PrevLogEntry:      1,
					PrevLogTerm:       1,
					Entries:           []*Log{{Index: 2, Term: 2, Type: LogCommand, Data: []byte("old-term")}},
					LeaderCommitIndex: 1,
				}
				var resp AppendEntriesResponse
				if err := trans2.AppendEntries(id1, addr1, ae, &resp); err != nil {
					t.Fatalf("appendEntries(seed): %v", err)
				}
				caEvent(map[string]interface{}{"event": "seed_append", "success": resp.Success, "term": resp.Term})
				if !resp.Success {
					t.Fatalf("seed append failed")
				}
				time.Sleep(50 * time.Millisecond)
			}

			// Step 2: a new leader of term 3 installs a snapshot whose last
			// included index is 2.
			payload := snapshotPayload(t)
			conf := Configuration{Servers: []Server{
				{Suffrage: Voter, ID: ServerID("server-2"), Address: "server-2"},
				{Suffrage: Nonvoter, ID: ServerID("server-1"), Address: "server-1"},
			}}
			isr := &InstallSnapshotRequest{
				RPCHeader:          hdr,
				SnapshotVersion:    1,
				Term:               3,
				Leader:             leader,
				LastLogIndex:       2,
				LastLogTerm:        3,
				Configuration:      EncodeConfiguration(conf),
				ConfigurationIndex: 1,
				Size:               int64(len(payload)),
			}
			var isResp InstallSnapshotResponse
			if err := trans2.InstallSnapshot(id1, addr1, isr, &isResp, bytes.NewReader(payload)); err != nil {
				t.Fatalf("installSnapshot: %v", err)
			}
			caEvent(map[string]interface{}{"event": "install_snapshot", "success": isResp.Success, "term": isResp.Term})
			time.Sleep(50 * time.Millisecond)

			li, lt := r.getLastLog()
			si, st := r.getLastSnapshot()
			ei, et := r.getLastEntry()
			caEvent(map[string]interface{}{
				"event": "state_after_snapshot", "last_log_index": li, "last_log_term": lt,
				"last_snapshot_index": si, "last_snapshot_term": st,
				"get_last_entry_index": ei, "get_last_entry_term": et,
				"get_last_index": r.getLastIndex(), "get_last_applied": r.getLastApplied(),
			})

			// Step 3: the leader replicates the entry right after the snapshot
			// boundary, whose PrevLogEntry/Term is exactly the snapshot's.
			ae2 := &AppendEntriesRequest{
				RPCHeader:         hdr,
				Term:              3,
				Leader:            leader,
				PrevLogEntry:      2,
				PrevLogTerm:       3,
				Entries:           []*Log{{Index: 3, Term: 3, Type: LogCommand, Data: []byte("new")}},
				LeaderCommitIndex: 2,
			}
			var resp2 AppendEntriesResponse
			if err := trans2.AppendEntries(id1, addr1, ae2, &resp2); err != nil {
				t.Fatalf("appendEntries(post-snapshot): %v", err)
			}
			caEvent(map[string]interface{}{
				"event": "post_snapshot_append", "stale_seed": stale,
				"success": resp2.Success, "no_retry_backoff": resp2.NoRetryBackoff,
				"resp_term": resp2.Term, "resp_last_log": resp2.LastLog,
			})
		})
	}
}
