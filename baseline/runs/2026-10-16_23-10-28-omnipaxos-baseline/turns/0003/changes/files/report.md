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
| `cargo test -p omnipaxos --features "logging,toml_config" --no-fail-fast` | **37 passed, 0 failed, 4 ignored** (`executions/1ee4ab4dee6b4edb96aca473d302b394/stdout.txt`) |
| `cargo test -p omnipaxos --features "logging,toml_config,unicache" --all-targets --no-fail-fast` | **42 passed, 0 failed, 4 ignored** (`notes/core_unicache_tests.log`) |

The core suite's kompact harness binds TCP sockets, which the ordinary shell forbids
(`Failed to build a Network Thread ... PermissionDenied`), so it was run through the
isolated executor with a private network namespace; the run above is green. The two
suites together are the captured implementation's own test suite for the core and for the
async runtime layer, so **everything the captured tests cover passes**; the finding below
is outside their coverage.

Both ran against the unmodified captured source, so the finding below is *not* something
the captured suite already covers.

### Reproduce everything

```
# finding 1: 8 tests = 6 failing repros + 2 passing controls, ~20 s
cargo test -p omnipaxos_runtime --features tokio_runtime \
    --test audit_batch_alignment_test -- --nocapture --test-threads=1

# randomized soak + its batch_size=1 control, ~5 s
cargo test -p omnipaxos_runtime --features tokio_runtime \
    --test audit_batch_alignment_test soak -- --nocapture

# captured core suite (needs the isolated executor for its TCP harness)
cargo test -p omnipaxos --features "logging,toml_config" --no-fail-fast

# optional: same tests against the instrumented/fixed diagnostic copy
cd diag/omnipaxos_runtime
CARGO_NET_OFFLINE=true CARGO_TARGET_DIR=../../.runtime/cargo-target \
    cargo test --features tokio_runtime --test audit_batch_alignment_test -- --test-threads=1
```

The audit test file's outcome is bit-identical across runs
(`notes/repro_stability.log`: 4 runs give the same six per-test lines).

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

**Extent: every write queued behind the trigger at that moment is shifted by one.** The
stale advance is consumed once per `reconcile_unconfirmed` pass, but because the *victim's*
placeholder has been consumed, the victim's own advance in turn consumes the placeholder of
the write after it. With `batch_size = 4` and six `append_notify` calls issued in one tick
window (calls 1-3 buffered, call 4 fills the batch and is self-resolved, calls 5-6 buffered
behind it), the observed result is

```
[audit-cascade] returned indices for entries 1000..6000 = [1, 2, 3, 4, 4, 5]
[audit-cascade] decided log: [1000, 2000, 3000, 4000, 5000, 6000]
[audit-cascade] wrong (call#, reported idx, entry, actual entry at idx) =
                [(5, 4, 5000, 4000), (6, 5, 6000, 5000)]
```

i.e. calls 5 and 6 were both told the index of the write immediately before them. So the
defect is not a single-caller race: several concurrent callers can be misinformed in one
go (`notes/repro_cascade.log`).

**How easily an ordinary workload hits it (soak, executed).** Two randomised but
reproducible soak tests in the same file, each issuing 40 `append_notify` calls per seed
over 3 nodes (leader and followers alike, random 0-3 ms gaps, 20 ms ticks, batch flushed
after 10 ticks) and checking every `Ok(idx)` against the decided log:

| test | workload | result |
| --- | --- | --- |
| `soak_control_batch_size_one_all_indices_correct` | `batch_size = 1` (no batching) | 120/120 calls correct, 0 errors — **passes** |
| `soak_random_mixed_appends_report_only_true_indices` | `batch_size = 4` | **75 of 120 calls returned a wrong index** (62%), 0 errors — **fails** |

```
[audit-soak-control] batch_size 1: 120 Ok, 0 errors, 0 wrong-index, 0 not-decided
[audit-soak] TOTALS batch_size 4: 120 calls resolved Ok, 0 returned an error,
            75 wrong-index replies, 0 indices absent from every decided log
[audit-soak] WRONG-INDEX: seed 1 call #4 on pid 1: Ok(4) but entry at idx 4 is
            TestEntry(10003) (its entry TestEntry(10004) is at Some(5))
[audit-soak] WRONG-INDEX: seed 1 call #5 on pid 3: Ok(5) but entry at idx 5 is
            TestEntry(10004) (its entry TestEntry(10005) is at Some(6))
```

(`notes/repro_soak_runs.log` — three runs, 75/120 each; `notes/repro_soak2.log` — 63/120.
The exact count varies a little with scheduling, but the control is always exactly 0, so
the checker itself is sound and the failure is batching-dependent.) The victims include
calls issued on *followers* (`pid 1`, `pid 2` above), i.e. the leader's wrong index is
delivered over the wire by `Assigned`. So this is an ordinary-workload behaviour, not a
contrived interleaving: `append_notify` at any `batch_size > 1` cannot be relied on to
report the index of the entry it appended.

**Root cause confirmed at code level, and a candidate fix.** To turn the mechanism from an
inference into an observation, an instrumented *copy* of the crate was made under
`work/diag/omnipaxos_runtime/` (the audited source is untouched; the copy differs only by
`eprintln!` tracing in `append_tracked`/`reconcile_unconfirmed` plus the candidate fix
described below). Running the `batch_size = 2` repro against that copy prints the
bookkeeping directly (`notes/diag_run1.log`):

```
[diag pid 3] append_tracked: accepted 0->0, batched_len 0->1, intent Untracked
[diag pid 3] append_tracked: accepted 0->2, batched_len 1->0, intent Local(338fe42c-…)   <- flush of 2; resolved directly; NO placeholder queued
[diag pid 3] append_tracked: accepted 2->2, batched_len 0->1, intent Local(6da80a6a-…)   <- call 3 deferred; one placeholder queued
[diag pid 3] reconcile: accepted=2, last_seen=0, queue(2)=[("Untracked",1),("Local(6da80a6a-…)",1)]
[diag pid 3]   idx 1: popped Untracked (ballot n=1), cur_ballot n=1
[diag pid 3]   idx 2: popped Local(6da80a6a-…) (ballot n=1), cur_ballot n=1              <- call 3 assigned index 2
[audit] idx(2000) = 2, idx(3000) = 2
```

i.e. exactly one queued item for two advances, and the queued `Local` item is consumed by
the advance that the flush-triggering call had already resolved directly.

The candidate fix is the missing counterpart of `append_tracked`'s deferral branch: the
immediate-accept branch must also queue something for the advance it just caused, so that
`reconcile_unconfirmed`'s pop-per-advance loop does not consume a *later* write's
placeholder. Applied to the diagnostic copy only:

```rust
if accepted_after > accepted_before {
    let ballot = self.op.get_promise();
    if let TrackIntent::Local(id) = intent {
        self.record_assignment(id, accepted_after, ballot);
    }
    // keep the pop-per-advance accounting exact for this call's own advance
    self.unconfirmed_local
        .push_back((TrackIntent::Untracked, ballot));
    Ok(Some((accepted_after, ballot)))
}
```

| build | `audit_batch_alignment_test.rs` |
| --- | --- |
| captured source (`work/omnipaxos_runtime`) | **2 passed, 6 failed** (`notes/repro_run7.log`) |
| diagnostic copy + the fix above | **8 passed, 0 failed** (`notes/diag_fix_run2.log`) |

Every one of the six failing repros (the deterministic ones, the remote/follower one, the
multi-victim one and the randomised soak) passes with that one change, and the two controls
pass in both builds. That is strong evidence the accounting hole above is the whole cause
of the observed behaviour, and it gives a maintainer a concrete fix to evaluate. (The
repros were restructured while doing this: the earlier versions awaited the victim's reply
before flushing its batch, which only terminated because the buggy build replied early; the
current versions trigger every flush inside the same burst and were verified to pass on the
corrected build. The "reply arrives while the entry is not even accepted" observation from
the buggy build is preserved in `notes/repro_run5.log` and in the test's doc comment.)

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

The sixth test in the file pins the sharpest form of the consequence — the caller is told
"decided" while its entry has not been *accepted* by anyone yet:

```
test wrong_index_is_reported_while_the_entry_is_still_unaccepted ...
[audit-unaccepted] call 3 resolved Ok(2) (call 2 -> Ok(2));
                   decided_idx = 2, decided log = [TestEntry(1000), TestEntry(2000)]
panicked: call 3 was told its entry is decided at idx 2; at that moment the decided log is
          [TestEntry(1000), TestEntry(2000)] -- idx 2 holds TestEntry(2000) and entry 3000
          is not in the decided log at all
FAILED
```

Full-file result with every audit test in place (`notes/repro_run6.log`):

```
test append_notify_index_is_wrong_batch_size_four ... FAILED
test append_notify_index_is_wrong_when_a_flush_is_followed_by_a_batched_append ... FAILED
test control_same_calls_separated_by_a_tick_resolve_correctly ... ok
test follower_append_notify_gets_wrong_index_from_leader ... FAILED
test shift_propagates_to_multiple_pending_callers ... FAILED
test soak_control_batch_size_one_all_indices_correct ... ok
test soak_random_mixed_appends_report_only_true_indices ... FAILED
test wrong_index_is_reported_while_the_entry_is_still_unaccepted ... FAILED
test result: FAILED. 2 passed; 6 failed; 0 ignored; 0 measured; 0 filtered out
```

The two passing tests are the controls (an inserted tick; `batch_size = 1`).

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

The shipped example states the intended use of this return value in exactly the terms the
defect breaks (`examples/kv_store_async/src/main.rs:132-150`): `append_notify` is used for
"the one entry where the caller specifically needs to know its durable decided index
before proceeding", and the value is printed as "quota entry durably decided at log idx
{idx}, safe to announce". A caller that gates on this return value can be told that its
write is decided at an index that holds a *different* write's value, while its own entry is
still unflushed in the leader's batch buffer (it is normally accepted one index later, but
nothing has committed it at the moment the caller is told it is decided).

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

1. **Durability consequence of finding 1 (not demonstrated).** If the leader fails or is
   partitioned away between telling a caller `Ok(idx)` and flushing the batch that holds
   the caller's entry, the entry was never accepted by anyone while the caller was told it
   was decided. Demonstrating this needs a restart/partition harness the runtime's public
   API does not expose (storage ownership moves into the actor), so it is recorded as a
   source-based consequence, not an executed observation.
2. `push_to_sub` / `push_to_all_subs` (`omnipaxos_runtime/src/actor.rs:279-333`) advance a
   subscriber's `next_idx` once per *delivered item*, but `InternalStorage::read`
   (`omnipaxos/src/storage/internal_storage.rs:90-157`) returns a single
   `LogEntry::Trimmed/Snapshotted` item for the whole compacted prefix, so a subscription
   starting below `compacted_idx` should desync the cursor and re-deliver entries. Not
   reproduced: the actor exposes no trim/snapshot command, so compaction cannot be
   triggered through the runtime's API (reachable only if a caller drives the core
   `OmniPaxos` instance directly, which the actor API does not allow).
3. Stale placeholders in `unconfirmed_local` in the leadership-change / truncation cases
   (`AcceptSync` resync, buffered proposals being accepted on election): the ballot guard
   in `reconcile_unconfirmed` is supposed to cover these, and no counterexample was found
   by reading, but they were not exercised.
4. Core compaction paths (`try_trim`/`try_snapshot`/`create_diff_snapshot`) and the
   `unicache` encode/decode path: read, and the captured suites for them pass, but no
   adversarial cases were constructed.

## Files created by this audit

* `work/report.md` (this report)
* `work/omnipaxos_runtime/tests/audit_batch_alignment_test.rs` — reproduction + control
  (8 tests: 6 failing repros, 1 inserted-tick control, 1 `batch_size = 1` soak control)
* `work/diag/omnipaxos_runtime/` — **diagnostic-only copy** of the runtime crate: `eprintln!`
  tracing of the batching bookkeeping, plus the candidate fix kept in a clearly marked
  block. It has its own `[workspace]` and absolute path deps so the captured workspace is
  untouched; `diff -u omnipaxos_runtime/src/actor.rs diag/omnipaxos_runtime/src/actor.rs`
  shows every difference made for diagnosis.
* `work/notes/repro_run1.log`, `repro_run2.log`, `repro_run3.log`,
  `repro_run4.log`, `repro_run5.log`, `repro_run6.log`, `repro_cascade.log`,
  `repro_soak.log`, `repro_soak2.log`, `repro_soak_runs.log`, `repro_determinism.log`,
  `repro_remote_determinism.log`, `repro_stability.log`, `repro_run7.log`,
  `diag_run1.log`, `diag_fix_run.log`, `diag_fix_run2.log`, `rt_baseline.log`,
  `rt_allfeatures_build.log`, `rt_allfeatures_run.log`, `core_baseline.log`,
  `core_unicache_tests.log`, `build_tests.log`, `build_rt.log`
* `work/notes/diff_0.2.2_vs_work.txt` — diff of the captured `omnipaxos/src` against the
  published `omnipaxos` 0.2.2 crate (used only to tell genuine version drift apart from
  local edits; not a reference for the newer dev code)
* `work/ref/omnipaxos-0.2.2/` — extracted copy of the published 0.2.2 crate
