package raft

import (
    "bytes"
    "encoding/json"
    "fmt"
    "io"
    "testing"
)

type assuranceBoundaryFSM struct { restored []byte }
func (f *assuranceBoundaryFSM) Apply(l *Log) interface{} { return string(l.Data) }
func (f *assuranceBoundaryFSM) Snapshot() (FSMSnapshot, error) { return nil, fmt.Errorf("snapshot creation not used") }
func (f *assuranceBoundaryFSM) Restore(r io.ReadCloser) error {
    defer r.Close()
    b, err := io.ReadAll(r)
    f.restored = b
    return err
}
func TestAssuranceExploreSnapshotBoundary(t *testing.T) {
    for _, oldTerm := range []uint64{1, 2} {
        t.Run(fmt.Sprintf("retained_term_%d", oldTerm), func(t *testing.T) {
            cfg := DefaultConfig()
            cfg.LocalID = "f"
            cfg.skipStartup = true
            cfg.TrailingLogs = 100
            store := NewInmemStore()
            conf := Configuration{Servers: []Server{
                {ID:"f", Address:"f", Suffrage:Voter},
                {ID:"l", Address:"l", Suffrage:Voter},
                {ID:"q", Address:"q", Suffrage:Voter},
            }}
            if err := store.StoreLog(&Log{Index:1, Term:1, Type:LogConfiguration, Data:EncodeConfiguration(conf)}); err != nil { t.Fatal(err) }
            for idx := uint64(2); idx <= 5; idx++ {
                if err := store.StoreLog(&Log{Index:idx, Term:oldTerm, Type:LogCommand, Data:[]byte("retained")}); err != nil { t.Fatal(err) }
            }
            if err := store.SetUint64(keyCurrentTerm, oldTerm); err != nil { t.Fatal(err) }
            _, trans := NewInmemTransport("f")
            defer trans.Close()
            fsm := &assuranceBoundaryFSM{}
            r, err := NewRaft(cfg, fsm, store, store, NewInmemSnapshotStore(), trans)
            if err != nil { t.Fatal(err) }
            r.goFunc(r.runFSM)
            defer func() { _ = r.Shutdown().Error() }()
            payload := []byte("snapshot-prefix-at-five")
            req := &InstallSnapshotRequest{
                RPCHeader:RPCHeader{ProtocolVersion:cfg.ProtocolVersion, ID:[]byte("l"), Addr:[]byte("l")},
                SnapshotVersion:1, Term:3, LastLogIndex:5, LastLogTerm:2,
                Configuration:EncodeConfiguration(conf), ConfigurationIndex:1, Size:int64(len(payload)),
            }
            replies := make(chan RPCResponse, 1)
            r.installSnapshot(RPC{Command:req, Reader:bytes.NewReader(payload), RespChan:replies}, req)
            install := <-replies
            if install.Error != nil { t.Fatal(install.Error) }
            installed := install.Response.(*InstallSnapshotResponse).Success
            if !installed || string(fsm.restored) != string(payload) { t.Fatalf("snapshot prerequisite failed: success=%v restored=%q", installed, fsm.restored) }
            entryIndex, entryTerm := r.getLastEntry()
            snapIndex, snapTerm := r.getLastSnapshot()
            next := &AppendEntriesRequest{
                RPCHeader:req.RPCHeader, Term:3, PrevLogEntry:5, PrevLogTerm:2,
                Entries:[]*Log{{Index:6, Term:3, Type:LogCommand, Data:[]byte("next")}},
                LeaderCommitIndex:5,
            }
            r.appendEntries(RPC{Command:next, RespChan:replies}, next)
            appendReply := <-replies
            if appendReply.Error != nil { t.Fatal(appendReply.Error) }
            event := map[string]interface{}{
                "kind":"snapshot_boundary", "old_term":oldTerm, "installed":installed,
                "restored_payload":string(fsm.restored), "last_entry_index":entryIndex,
                "last_entry_term":entryTerm, "snapshot_index":snapIndex, "snapshot_term":snapTerm,
                "append_success":appendReply.Response.(*AppendEntriesResponse).Success,
                "final_last_index":r.getLastIndex(),
            }
            b, err := json.Marshal(event)
            if err != nil { t.Fatal(err) }
            fmt.Println("CA_EVENT " + string(b))
        })
    }
}
