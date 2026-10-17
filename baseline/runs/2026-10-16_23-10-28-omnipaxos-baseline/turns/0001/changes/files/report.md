# OmniPaxos audit report

Source under audit: `work/` (mutable copy of `source/`, identified in the run brief as
`827f304846ab0c5aa40910b6f6cdce1d4ddf8e12`; `omnipaxos` v0.2.3 + `omnipaxos_runtime`
v0.1.0 + `omnipaxos_storage` + `omnipaxos_macros` + `omnipaxos_ui`).

Toolchain: `cargo 1.94.1` / `rustc 1.94.1`, offline. No source file of the captured
implementation was modified. All new files created by this audit are listed at the end.

## Baseline (executed)

| Command | Result |
| --- | --- |
| `cargo test -p omnipaxos_runtime --features tokio_runtime` | **24 passed, 0 failed** (`notes/rt_baseline.log`) |
| `cargo test -p omnipaxos --features "logging,toml_config" --no-run` | compiles (`notes/build_tests.log`) |

Both ran against the unmodified captured source, so the finding below is *not* something
the captured suite already covers.

---

## Finding 1 — `append_notify` can resolve with the log index of a *different* entry (runtime batching bookkeeping)

**Severity:** report-level correctness. `OmniPaxosHandle::append_notify` is documented as
returning "its decided log index"; under the conditions below it returns an index whose
decided entry is a different write — and it does so *before* the caller's own entry has
even been accepted.

**Where:**

* `omnipaxos_runtime/src/actor.rs:119` (`unconfirmed_local`), `:370-397`
  (`append_tracked`), `:438-479` (`reconcile_unconfirmed`).
* These are the only places that assign an index to a locally-originated
  `append_notify` (the leader-side path; `handle_runtime_msg`'s `TaggedProposal` path
  feeds the same `accept_as_leader`/`append_tracked` code).

**Expected behaviour and its basis.** `OmniPaxosHandle::append_notify` documents
(`omnipaxos_runtime/src/handle.rs:114-137`): "Append an entry and await its decided log
index ... resolves the future when the assigned log index is decided". The captured
suite itself encodes the checkable form of this contract
(`omnipaxos_runtime/tests/async_runtime_test.rs:1330-1380`): read the decided log back at
the returned index and compare its content with the entry the call appended.

**Mechanism (source-based, confirmed by execution).** `unconfirmed_local` is a FIFO of
one item per write that is sitting in the node's shared batch buffer
(`state_cache.batched_entries`), and `reconcile_unconfirmed` pops **one item per single
unit of `accepted_idx` advance** to learn which index each pending write got.

`append_tracked` pushes a placeholder in exactly one case — when the append was *deferred*
(`accepted_idx` unchanged, `batched_len` grew). When the append instead *fills* the batch,
the entry is accepted inside that same call and is resolved directly
(`record_assignment(id, accepted_after)`), so **no placeholder is pushed for it**, while
`accepted_idx` still advanced once per flushed entry (including one advance for the
triggering entry itself).

The missing placeholder is harmless only if it is the *last* advance of that flush and
nothing else is queued behind the other entries of the same flush at the next
`reconcile_unconfirmed` pass (the queue drains and the loop breaks). If instead a further
write is buffered *before the next tick*, that write's placeholder is consumed by the
stale advance of the flush-triggering entry, so it is resolved with the index that
actually belongs to the triggering entry. Concretely, with `batch_size = 2` and all calls
issued on the elected leader inside one tick window:

| call | effect on the batch buffer | placeholders pushed | `accepted_idx` |
| --- | --- | --- | --- |
| `append(1000)` | buffer `[1000]`, no flush | `U(1000)` | 0 |
| `append_notify(2000)` | buffer `[1000,1000]`→flush of 2; accepted in-call | *(none)* | 2 |
| `append_notify(3000)` | buffer `[3000]`, no flush | `Local(id₃₀₀₀)` | 2 |

Next tick: `reconcile_unconfirmed` sees `accepted_idx = 2` (two advances) but only two
queued items, and pops *both*: `U(1000)` for index 1 (correct) and `Local(id₃₀₀₀)` for
index 2 — index 2 is entry 2000. `drain_notifiers` then replies `Ok(2)` as soon as index 2
is decided, i.e. while entry 3000 is still sitting unflushed in the batch buffer.

**Necessary conditions.** `batch_size > 1`; a write buffered without being accepted, then
a write that fills the batch in the same call (so the flush and the direct resolution
coincide), then ≥1 further write (tracked, i.e. `append_notify`/remotely-tagged) buffered
before the next `tick()` so the stale advance finds a queued item to consume. A tick
between the flush and that further write removes the symptom (see the control test). The
same accounting is used for forwarded, remotely-tagged entries (`TrackIntent::Remote`),
which then get an `Assigned` carrying the wrong index to the originating node.

**What actually happens (executed).** `work/omnipaxos_runtime/tests/audit_batch_alignment_test.rs`
(added by this audit; the captured test file is untouched):

```
$ cargo test -p omnipaxos_runtime --features tokio_runtime \
      --test audit_batch_alignment_test -- --nocapture --test-threads=1

running 4 tests
test append_notify_index_is_wrong_batch_size_four ...
[audit-b4] idx(3000) = 3, idx(4000) = 4, idx(5000) = 4
[audit-b4] decided log: [TestEntry(1000), TestEntry(2000), TestEntry(3000),
                         TestEntry(4000), TestEntry(5000), TestEntry(6000),
                         TestEntry(7000), TestEntry(8000)]
panicked: append_notify(5000) returned idx 4, but the decided log has
          Some(TestEntry(4000)) at that index (its own entry is at idx Some(5))
FAILED
test append_notify_index_is_wrong_when_a_flush_is_followed_by_a_batched_append ...
[audit] idx(2000) = 2, idx(3000) = 2
[audit] decided log (1-based):
[audit]   idx 1 = TestEntry(1000)
[audit]   idx 2 = TestEntry(2000)
[audit]   idx 3 = TestEntry(3000)
[audit]   idx 4 = TestEntry(4000)
panicked: append_notify(3000) returned idx 2, but the decided log has
          Some(TestEntry(2000)) at that index (its own entry is at idx Some(3))
FAILED
test control_same_calls_separated_by_a_tick_resolve_correctly ...
[audit-control] idx(2000) = 2, idx(3000) = 3, idx(4000) = 4,
                log = [1000, 2000, 3000, 4000]
ok
test follower_append_notify_gets_wrong_index_from_leader ...
[audit-remote] follower idx(5000) = 4
[audit-remote] decided log: [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000]
panicked: follower's append_notify(5000) was told idx 4, but the decided log has
          Some(TestEntry(4000)) at that index (its own entry is at idx Some(5))
FAILED

test result: FAILED. 1 passed; 3 failed; 0 ignored; 0 measured; 0 filtered out
```

Full output: `notes/repro_run3.log` (re-run deterministically across separate runs —
`notes/repro_determinism.log`, `notes/repro_remote_determinism.log`, plus
`notes/repro_run1.log`, `notes/repro_run2.log`, `notes/repro_run4.log`).

All three failing cases fail reproducibly (3/3, and 5/5 for the remote case). The third
test is the control: identical
cluster (`batch_size = 2`), identical entries and call order, *only* difference being that
the third call is issued after a tick has run. It passes with `idx(3000) = 3`. That rules
out batching, leader election, entry forwarding and the core log as explanations and pins
the cause on the placeholder/pop accounting.

The fourth test reaches the same defect through the remote path a follower uses
(`TrackIntent::Remote` → `AsyncRuntimeMsg::Assigned`): the *leader* pops the follower's
placeholder one advance early and answers `Assigned { entries: [(id₅₀₀₀, 4)] }`, so the
follower's `append_notify(5000)` resolves `Ok(4)` — an index that holds entry 4000 —
while its own entry is decided at index 5. So the wrong index is not confined to the node
that issued the call.

**Alternative explanations checked.**

* *Core log corruption?* No. The decided log is `[1000, 2000, 3000, 4000]` — entries are
  in issue order and the other two returned indices are correct; only the index returned
  *to the caller* is wrong. The core accepts and decides the entry normally at index 3.
* *Standalone `batch_size` quirk?* No. It reproduces with `batch_size = 2` and 4.
* *`ProposalForward`/untracked-interleaving bug already covered by the captured suite?*
  No. That test (`append_notify_index_correct_when_batched_with_plain_append`) stops after
  the flush-triggering call, which is exactly the case the accounting happens to get
  right.
* *Timing/scheduling artifact?* The failing runs are bit-identical in outcome; the control
  differs only by an inserted tick.

**Impact.** A caller that trusts the returned index (e.g. reads the entry back, or maps a
client write to a log position, or acks with "decided at i") can observe a different value
at that index or believe the write is decided while it is still buffered and unaccepted.
No cluster-wide safety violation was demonstrated — the entry itself is normally accepted
one index later — but the API's stated per-call guarantee is broken. If the leader dies
before the deferred batch flushes, the caller has already been told its write was decided.

---

## Unresolved / next targets (not yet executed)

1. `push_to_sub` / `push_to_all_subs` (`omnipaxos_runtime/src/actor.rs:279-333`) advance a
   subscriber's `next_idx` once per *delivered item*, but `InternalStorage::read`
   (`omnipaxos/src/storage/internal_storage.rs:90-157`) returns a single
   `LogEntry::Trimmed/Snapshotted` item for the whole compacted prefix. Subscribing from an
   index below `compacted_idx` should therefore desync the cursor and re-deliver entries.
   Not yet reproduced.
2. Extent of the mis-alignment for a *sequence* of further writes: after the stale pop,
   every later write that shares the queue with a flush-triggering write should be shifted
   by one as well; the per-call bound of this "shift" is not yet characterised.
3. Core compaction paths (`try_trim`/`try_snapshot`/`create_diff_snapshot`) and the
   `unicache` encode/decode path have been read but not yet exercised.

## Files created by this audit

* `work/report.md` (this report)
* `work/omnipaxos_runtime/tests/audit_batch_alignment_test.rs` — reproduction + control
* `work/notes/repro_run1.log`, `repro_run2.log`, `repro_run3.log`,
  `repro_run4.log`, `repro_determinism.log`, `repro_remote_determinism.log`,
  `rt_baseline.log`, `build_tests.log`, `build_rt.log`
* `work/notes/diff_0.2.2_vs_work.txt` — diff of the captured `omnipaxos/src` against the
  published `omnipaxos` 0.2.2 crate (used only to tell genuine version drift apart from
  local edits; not a reference for the newer dev code)
* `work/ref/omnipaxos-0.2.2/` — extracted copy of the published 0.2.2 crate
