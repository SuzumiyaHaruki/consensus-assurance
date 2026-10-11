// Package raftboltdb is a minimal OFFLINE stand-in for github.com/hashicorp/raft-boltdb.
// It exists only so the nested `fuzzy` harness can be compiled and run without
// network access (the real raft-boltdb and boltdb/bolt module zips are absent
// from the local module cache). It is backed by an in-memory raft store and is
// NOT a faithful persistence implementation; it is used for audit coverage only.
package raftboltdb

import "github.com/hashicorp/raft"

// BoltStore satisfies raft.LogStore and raft.StableStore (via InmemStore).
type BoltStore struct {
	*raft.InmemStore
}

// NewBoltStore mirrors the upstream signature; path is ignored.
func NewBoltStore(_ string) (*BoltStore, error) {
	return &BoltStore{InmemStore: raft.NewInmemStore()}, nil
}

// Close is a no-op for the in-memory backing.
func (b *BoltStore) Close() error { return nil }
