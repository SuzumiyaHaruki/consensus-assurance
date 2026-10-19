//go:build dragonboat_audit

// Audit-only randomised model check of inMemory (the "unstable" raft log the
// protocol reads from). Not part of the captured implementation.

package raft

import (
	"math/rand"
	"testing"

	pb "github.com/lni/dragonboat/v3/raftpb"
)

type memLogModel struct {
	mk      uint64
	ents    []pb.Entry
	applied uint64
	applT   uint64
	savedTo uint64
	snapIx  uint64
	snapT   uint64
	hasSnap bool
}

func newMemLogModel(lastIndex uint64) *memLogModel {
	return &memLogModel{mk: lastIndex + 1, savedTo: lastIndex}
}

func (m *memLogModel) lastIndex() uint64 {
	if len(m.ents) == 0 {
		return m.mk - 1
	}
	return m.ents[len(m.ents)-1].Index
}

func (m *memLogModel) term(i uint64) (uint64, bool) {
	if i > 0 && i == m.applied {
		return m.applT, true
	}
	if i < m.mk {
		if m.hasSnap && m.snapIx == i {
			return m.snapT, true
		}
		return 0, false
	}
	if i > m.lastIndex() || len(m.ents) == 0 {
		return 0, false
	}
	return m.ents[i-m.mk].Term, true
}

func (m *memLogModel) restore(ss pb.Snapshot) {
	m.snapIx, m.snapT, m.hasSnap = ss.Index, ss.Term, true
	m.mk = ss.Index + 1
	m.applied, m.applT = ss.Index, ss.Term
	m.ents = nil
	m.savedTo = ss.Index
}

func (m *memLogModel) merge(ents []pb.Entry) {
	first := ents[0].Index
	if first == m.mk+uint64(len(m.ents)) {
		m.ents = append(m.ents, ents...)
	} else if first <= m.mk {
		m.mk = first
		m.ents = append([]pb.Entry{}, ents...)
		m.savedTo = first - 1
	} else {
		m.ents = append([]pb.Entry{}, m.ents[:first-m.mk]...)
		m.ents = append(m.ents, ents...)
		if first-1 < m.savedTo {
			m.savedTo = first - 1
		}
	}
}

func (m *memLogModel) appliedLogTo(i uint64) {
	if i < m.mk || len(m.ents) == 0 || i > m.lastIndex() {
		return
	}
	e := m.ents[i-m.mk]
	m.applied, m.applT = e.Index, e.Term
	m.ents = append([]pb.Entry{}, m.ents[i-m.mk+1:]...)
	m.mk = i + 1
}

func (m *memLogModel) savedLogTo(i uint64, term uint64) {
	if i < m.mk || len(m.ents) == 0 {
		return
	}
	if i > m.lastIndex() || m.ents[i-m.mk].Term != term {
		return
	}
	m.savedTo = i
}

func (m *memLogModel) entriesToSave() []pb.Entry {
	idx := m.savedTo + 1
	if idx < m.mk || idx-m.mk > uint64(len(m.ents)) {
		return []pb.Entry{}
	}
	return m.ents[idx-m.mk:]
}

func TestAuditInMemoryLogModel(t *testing.T) {
	for seed := int64(1); seed <= 5; seed++ {
		rng := rand.New(rand.NewSource(seed * 7919))
		for round := 0; round < 400; round++ {
			im := newInMemory(uint64(rng.Intn(3)), nil)
			m := newMemLogModel(im.markerIndex - 1)
			for step := 0; step < 200; step++ {
				switch op := rng.Intn(10); {
				case op == 9 && rng.Intn(5) == 0:
					ix := m.lastIndex() + uint64(rng.Intn(4))
					ss := pb.Snapshot{Index: ix, Term: uint64(1 + rng.Intn(5))}
					im.restore(ss)
					m.restore(ss)
				case op < 5:
					// append or overwrite/truncate
					last := m.lastIndex()
					var first uint64
					r := rng.Intn(6)
					if r == 1 && len(m.ents) > 0 {
						first = m.mk + uint64(rng.Intn(len(m.ents)))
					} else {
						first = last + 1
					}
					n := 1 + rng.Intn(5)
					base := uint64(1)
					if first > m.mk {
						// production never rewrites applied entries, so the
						// preceding entry is always present in the log
						base = m.ents[first-1-m.mk].Term
					}
					ents := make([]pb.Entry, n)
					for i := 0; i < n; i++ {
						ents[i] = pb.Entry{
							Index: first + uint64(i),
							Term:  base + uint64(rng.Intn(2)),
						}
					}
					// checkEntriesToAppend requires non-decreasing terms
					for i := 1; i < n; i++ {
						if ents[i].Term < ents[i-1].Term {
							ents[i].Term = ents[i-1].Term
						}
					}
					if len(im.entries) > 0 && first > im.markerIndex {
						prev := im.entries[first-1-im.markerIndex]
						if ents[0].Term < prev.Term {
							t.Fatalf("round %d step %d: harness generated term %d < existing %d "+
								"(mk %d, first %d, len %d, model mk %d)",
								round, step, ents[0].Term, prev.Term,
								im.markerIndex, first, len(im.entries), m.mk)
						}
					}
					im.merge(append([]pb.Entry{}, ents...))
					m.merge(ents)
				case op < 8:
					// save up to a known index
					if len(m.ents) > 0 {
						i := m.mk + uint64(rng.Intn(len(m.ents)))
						term := m.ents[i-m.mk].Term
						im.savedLogTo(i, term)
						m.savedLogTo(i, term)
					}
				default:
					// apply up to a known index
					if len(m.ents) > 0 {
						i := m.mk + uint64(rng.Intn(len(m.ents)))
						im.appliedLogTo(i)
						m.appliedLogTo(i)
					}
				}
				if got, want := im.markerIndex, m.mk; got != want {
					t.Fatalf("round %d step %d: marker %d, want %d", round, step, got, want)
				}
				if got, want := len(im.entries), len(m.ents); got != want {
					t.Fatalf("round %d step %d: entries len %d, want %d", round, step, got, want)
				}
				for i := range m.ents {
					if im.entries[i].Index != m.ents[i].Index || im.entries[i].Term != m.ents[i].Term {
						t.Fatalf("round %d step %d: entry %d = %+v, want %+v",
							round, step, i, im.entries[i], m.ents[i])
					}
				}
				if got, want := im.savedTo, m.savedTo; got != want {
					t.Fatalf("round %d step %d: savedTo %d, want %d", round, step, got, want)
				}
				gotSave := im.entriesToSave()
				wantSave := m.entriesToSave()
				if len(gotSave) != len(wantSave) {
					t.Fatalf("round %d step %d: entriesToSave len %d, want %d",
						round, step, len(gotSave), len(wantSave))
				}
				for i := range wantSave {
					if gotSave[i].Index != wantSave[i].Index || gotSave[i].Term != wantSave[i].Term {
						t.Fatalf("round %d step %d: entriesToSave[%d] = %+v, want %+v",
							round, step, i, gotSave[i], wantSave[i])
					}
				}
				lo := m.mk
				hi := m.lastIndex() + 1
				if hi > lo {
					got := im.getEntries(lo, hi)
					for i := range got {
						if got[i].Index != m.ents[i].Index || got[i].Term != m.ents[i].Term {
							t.Fatalf("round %d step %d: getEntries[%d] = %+v, want %+v",
								round, step, i, got[i], m.ents[i])
						}
					}
				}
				if got, want := m.hasSnap, im.snapshot != nil; got != want {
					t.Fatalf("round %d step %d: has snapshot %t, want %t", round, step, im.snapshot != nil, want)
				}
			}
		}
	}
}

func minU64(a, b uint64) uint64 {
	if a < b {
		return a
	}
	return b
}
