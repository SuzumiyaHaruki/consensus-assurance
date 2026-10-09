package raft

import (
	"testing"
)

func TestZZFileSnapshotListAliasing(t *testing.T) {
	dir, snap := FileSnapTest(t)
	_ = dir
	_, trans := NewInmemTransport("")
	conf := Configuration{Servers: []Server{{Suffrage: Voter, ID: "x", Address: "x"}}}
	for i := uint64(1); i <= 3; i++ {
		sink, err := snap.Create(1, i, i, conf, i, trans)
		if err != nil {
			t.Fatalf("create %d: %v", i, err)
		}
		if _, err := sink.Write([]byte("data")); err != nil {
			t.Fatalf("write: %v", err)
		}
		if err := sink.Close(); err != nil {
			t.Fatalf("close: %v", err)
		}
	}
	list, err := snap.List()
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	for i, m := range list {
		t.Logf("list[%d] id=%s index=%d term=%d", i, m.ID, m.Index, m.Term)
	}
	if len(list) >= 2 && list[0].Index == list[1].Index {
		t.Errorf("ALIASING: list[0].Index=%d == list[1].Index=%d (ids %s,%s)", list[0].Index, list[1].Index, list[0].ID, list[1].ID)
	}
}
