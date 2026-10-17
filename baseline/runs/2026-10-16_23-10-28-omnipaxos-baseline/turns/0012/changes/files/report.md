# OmniPaxos audit report

Source under audit: `work/` (mutable copy of `source/`, identified in the run brief as
`827f304846ab0c5aa40910b6f6cdce1d4ddf8e12`; `omnipaxos` v0.2.3 + `omnipaxos_runtime`
v0.1.0 + `omnipaxos_storage` + `omnipaxos_macros` + `omnipaxos_ui`).

Toolchain: `cargo 1.94.1` / `rustc 1.94.1`, offline. No source file of the captured
implementation was modified. All new files created by this audit are listed at the end.

## Executive summary

Three findings, each with a reproduction that another engineer can run. Two are deterministic;
the third is deterministic in its core shape and only shows up as an intermittent stall in the
captured suite.

| # | Where | Defect | Evidence |
| --- | --- | --- | --- |
| 1 | `omnipaxos_runtime/src/actor.rs` (`append_tracked`, `reconcile_unconfirmed`) | `append_notify` can resolve with the log index of a *different* entry — and before its own entry is even accepted. Requires `batch_size > 1` and a flush-triggering write followed by another buffered write in the same tick window. | 6 repro tests (2 also random-workload soak: 63–75 of 120 calls wrong), 2 controls pass; a candidate fix (queue a placeholder for the call's own advance) makes all 8 pass and leaves the captured runtime suite green (24/24) |
| 2 | `omnipaxos_runtime/src/actor.rs` (`DecidedSub::next_idx`, `push_to_sub`, `push_to_all_subs`) | A subscription starting below `compacted_idx` re-delivers the collapsed prefix item once per tick and re-delivers decided entries (cursor counts items, not log positions). Reachable by compacting the core instance before `spawn_actor`. | 2 repro tests: prefix delivered 6× (6 positions) and `Decided(104)/Decided(105)` delivered twice |
| 3 | `omnipaxos/src/sequence_paxos/{leader,follower}.rs` (`resend_messages_leader`, `resend_messages_follower`, `handle_sequence_num`) | A follower that misses an accept (and the decide that follows) is never brought up to date by the protocol itself: the leader re-sends no accepts despite tracking each follower's accepted index, the follower re-sends nothing in `Phase::Accept`, and `Outdated` messages are dropped silently. The StopSign `Decide` re-send reuses an already-consumed sequence number, so it can never take effect (source-confirmed, trace-observed). | 1 deterministic repro (follower stranded at `accepted = decided = 0` for 5000 rounds; one `reconnected(1)` fixes it), 4 probes pass; the captured `sync_full_test` stalls under CPU load are a *slow-recovery* symptom (instrumented run: follower fully caught up just after the 120 s budget expired) and are reported separately, not as this permanent strand |

Also recorded: negative results (the four `#[ignore]`d crash-recovery tests pass when run;
stale-leader adoption; a 4000-round partition/leader-churn safety soak; the StopSign
subscription boundary; `unicache` and workspace sweeps) and evidence-base caveats (two captured
runtime tests assert nothing; recovery tests are `#[ignore]`d; my first mechanism guess for
finding 3 was disproved by execution and is documented as such).

## Baseline (executed)

| Command | Result |
| --- | --- |
| `cargo test -p omnipaxos_runtime --features tokio_runtime` | **28 passed, 0 failed** across 3 targets = 24 integration (the `async_runtime_test.rs` suite) + 4 unit tests (`notes/rt_baseline.log`) |
| `cargo test -p omnipaxos --features "logging,toml_config" --no-run` | compiles (`notes/build_tests.log`) |
| `cargo test -p omnipaxos --features "logging,toml_config" --no-fail-fast` | **34 passed, 0 failed, 4 ignored** across 17 targets (`executions/1ee4ab4dee6b4edb96aca473d302b394/stdout.txt`); **37 passed** once the 3 audit core probes are included (`notes/core_baseline2.log`) |
| `cargo test -p omnipaxos --features "logging,toml_config,unicache" --all-targets --no-fail-fast` | **41 passed, 0 failed, 4 ignored** across 16 targets (`notes/core_unicache_tests.log`) |
| `cargo test -p omnipaxos --features "logging,toml_config" --test recovery_test -- --ignored` | **4 passed** (see the negative-results section) |
| `cargo test --workspace --all-targets --features "logging,toml_config" --no-fail-fast` | **1 failure: `sync_full_test`** (plus the 6 expected finding-1 replays and the 2 expected finding-2 replays) → finding 3 (`notes/workspace_tests.log`) |

The core suite's kompact harness binds TCP sockets, which the ordinary shell forbids
(`Failed to build a Network Thread ... PermissionDenied`), so it was run through the
isolated executor with a private network namespace; the run above is green. The two
suites together are the captured implementation's own test suite for the core and for the
async runtime layer, so **everything the captured tests cover passes** when it runs alone:
the findings below are outside that coverage, apart from finding 3, which is a captured test
that fails only under artificial CPU starvation. All of the above ran against the unmodified
captured source.
The three test files added by this audit are feature-gated the same way the captured suite
gates its own scaffolding (`tokio_runtime` on for the two runtime files, `unicache` off for
all three), still compile under `cargo test -p omnipaxos_runtime --all-features --no-run`
and `cargo test -p omnipaxos --features "logging,toml_config,unicache" --all-targets
--no-run`, and leave both `--all-features` runs green, so they do not disturb the captured
baseline.

### Reproduce everything

Final verification of all four audit test files against the unmodified captured source
(re-run at the end of the audit; each line is the whole-file result):

| file | result |
| --- | --- |
| `omnipaxos_runtime/tests/audit_batch_alignment_test.rs` (finding 1) | **2 passed, 6 failed** |
| `omnipaxos_runtime/tests/audit_subscription_compaction_test.rs` (finding 2) | **0 passed, 2 failed** |
| `omnipaxos_runtime/tests/audit_reconfiguration_boundary_test.rs` (negative result) | **1 passed, 0 failed** |
| `omnipaxos/tests/audit_leader_change_adoption_test.rs` (finding 3 + negative results) | **4 passed, 1 failed** |

Every failure is an assertion about behaviour the implementation's own documentation promises;
all controls (inserted tick, `batch_size = 1`, `reconnected()` remedy, adoption and soak probes)
pass.

```
# finding 1: 8 tests = 6 failing repros + 2 passing controls, ~20 s
cargo test -p omnipaxos_runtime --features tokio_runtime \
    --test audit_batch_alignment_test -- --nocapture --test-threads=1

# randomized soak + its batch_size=1 control, ~5 s
cargo test -p omnipaxos_runtime --features tokio_runtime \
    --test audit_batch_alignment_test soak -- --nocapture

# finding 2: compacted-log subscription, ~1 s
cargo test -p omnipaxos_runtime --features tokio_runtime \
    --test audit_subscription_compaction_test -- --nocapture --test-threads=1

# reconfiguration/StopSign boundary probe (negative result), ~1 s
cargo test -p omnipaxos_runtime --features tokio_runtime \
    --test audit_reconfiguration_boundary_test -- --nocapture

# captured core suite (needs the isolated executor for its TCP harness)
cargo test -p omnipaxos --features "logging,toml_config" --no-fail-fast

# the #[ignore]d crash-recovery tests (isolated executor: PersistentStorage + TCP)
cargo test -p omnipaxos --features "logging,toml_config" --test recovery_test \
    -- --ignored --nocapture --test-threads=1

# finding 3 (deterministic core repro: follower left behind, and the reconnected() remedy)
cargo test -p omnipaxos --features "logging,toml_config" \
    --test audit_leader_change_adoption_test -- --nocapture --test-threads=1

# finding 3 (timing-dependent symptom: stall of a lagging follower under CPU pressure)
cargo test -p omnipaxos --features "logging,toml_config" --test sync_test --no-run
# then run the freshly built binary from the two config dirs while 8 CPU hogs run:
#   (cd omnipaxos        && $BIN sync_full_test)   # captured 8 s budget
#   (cd diag/sync_harness && $BIN sync_full_test)  # 120 s budget

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

The fix is also compatible with the captured behaviour: the *captured* runtime suite
(`async_runtime_test.rs`) passes unchanged against the diagnostic copy with the fix applied
— **24 passed, 0 failed** (`notes/diag_captured_suite.log`).

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

## Finding 2 — `subscribe_decided` re-delivers already-delivered log positions when the subscription starts below `compacted_idx`

**Severity:** report-level. A subscriber (the documented way to feed a state machine) can be
handed the same decided entry twice, and in the fully-compacted case the same
prefix item once per tick.

**Where (runtime layer):** `omnipaxos_runtime/src/actor.rs` —
`DecidedSub::next_idx` (documented as "the next log index the actor must deliver",
:123-131), `push_to_sub` (:279-295, "`sub.next_idx += 1`" per delivered *item*),
`push_to_all_subs` (:301-333, same, plus `let start = sub.next_idx.saturating_sub(min_next)`
which skips *items*, not positions). The core side that makes item count differ from
position count is `InternalStorage::read`
(`omnipaxos/src/storage/internal_storage.rs:90-157`): for a read starting below
`compacted_idx` it returns a *single* `LogEntry::Trimmed`/`LogEntry::Snapshotted` item
standing for the whole compacted prefix, plus one item per entry after it.

**Expected behaviour and its basis.** `OmniPaxosHandle::subscribe_decided` documents
(`omnipaxos_runtime/src/handle.rs:261-270`) a receiver that "emits [`LogEntry`]s in log
order — both the backlog already decided at subscription time and entries decided later",
with "`next_idx` is the next log index the actor must deliver". Delivering the same log
position twice is not "in log order", and nothing in the docs asks subscribers to
de-duplicate.

**Mechanism.** `push_to_sub` / `push_to_all_subs` advance the cursor once per *delivered
item*. When the read starts below the compacted index, the returned vector covers far more
log positions than it has items (the whole compacted prefix is one item), so the cursor
ends up *behind* the positions it has already delivered; the next tick reads from there
again and re-delivers. Only reads starting at or after `compacted_idx` are unaffected,
because there item count == position count.

**Necessary conditions.** A subscriber with `from < compacted_idx` on an actor whose log was
already compacted when `spawn_actor` was called. The actor itself exposes no trim/snapshot
command, so compaction must happen on the core instance before it is handed over — e.g. a
restart that snapshots its recovered/decided log (`OmniPaxos::snapshot(idx, local_only)`
is public API and legal on a follower too). This is the reachability qualifier for the
item I previously listed as unreachable; it is reachable through the public API after all.

**What actually happens (executed).**
`work/omnipaxos_runtime/tests/audit_subscription_compaction_test.rs` hand-drives a two-node
core cluster (no actor, no network, `batch_size = 1`, no `append_notify` anywhere) until
6 entries are decided, snapshots node 2's log locally (`snapshot(Some(3), true)` /
`snapshot(Some(6), true)`), then hands that instance to `spawn_actor` and subscribes from
index 0:

```
$ cargo test -p omnipaxos_runtime --features tokio_runtime \
      --test audit_subscription_compaction_test -- --nocapture --test-threads=1

test subscriber_below_fully_compacted_log_gets_the_prefix_repeatedly ...
[audit-subs] fully compacted (compacted=6, decided=6), subscriber from 0 received 6 items:
             ["Snapshotted(trimmed_idx=6)", "Snapshotted(trimmed_idx=6)",
              "Snapshotted(trimmed_idx=6)", "Snapshotted(trimmed_idx=6)",
              "Snapshotted(trimmed_idx=6)", "Snapshotted(trimmed_idx=6)"]
panicked: the compacted prefix must be delivered once, but 6 prefix items were delivered
FAILED
test subscriber_below_partially_compacted_log_gets_entries_twice ...
[audit-subs] partially compacted (compacted=3, decided=6), subscriber from 0 received 6 items:
             ["Snapshotted(trimmed_idx=3)", "Decided(103)", "Decided(104)", "Decided(105)",
              "Decided(104)", "Decided(105)"]
panicked: decided entries delivered more than once: [104, 105]
FAILED

test result: FAILED. 0 passed; 2 failed; 0 ignored; 0 measured; 0 filtered out
```

`Decided(104)` and `Decided(105)` are each delivered twice (the cursor stopped at 4
instead of 6 after the catch-up), and the fully-compacted subscriber receives the same
prefix item six times — once per tick. Bit-identical across runs
(`notes/repro_subs_determinism.log`).

**Alternative explanations checked.**

* *Same root cause as finding 1?* No. Different code (subscriber cursor vs. the batching
  placeholder queue), different symptom (duplicate delivery vs. a wrong index), and this
  repro uses `batch_size = 1` with no `append_notify` call at all — the entries are appended
  through the core API by the harness.
* *Core log corrupt?* No. The harness asserts both nodes decided exactly 6 entries, and the
  duplicated values come from re-reading positions the subscriber already consumed.
* *Is the collapsed prefix item itself the bug?* It is by design of
  `InternalStorage::read` (one `Trimmed`/`Snapshotted` item for the compacted prefix, which
  callers of `read`/`read_decided_suffix` are expected to handle). The defect is the actor
  treating that item as one *position* when advancing its cursor.

**Fix direction.** Advance the cursor by the log positions the read covered (e.g. set
`next_idx` to the index the read ended at, i.e. the decided index for a full read) rather
than by item count, and express the per-subscriber skip
(`start = sub.next_idx - min_next`) in positions too — that same item-count arithmetic is
what would mis-slice a *second* subscriber whose cursor sits inside the collapsed prefix
while another subscriber trails it (not separately reproduced). Not applied here; the
captured source is untouched.

## Finding 3 — a lagging follower is never brought up to date by the consensus layer itself (missing accepts are not re-sent, and a re-sent `Decide` can never take effect)

**Summary.** `omnipaxos/tests/audit_leader_change_adoption_test.rs` reproduces this
deterministically, with no timing dependence: node 3 receives neither the `AcceptDecide` for
an entry nor the `Decide` that follows it; the leader and node 2 decide the entry, and node 3
stays at `accepted = decided = 0` for 5000 rounds (~250 resend periods). One
`OmniPaxos::reconnected(1)` call on the follower fixes it immediately. So the implementation
does not recover this on its own — recovery depends on an *external* nudge.

**Expected behaviour and its basis.** The resend machinery is the documented mechanism for
lost messages ("Detects if a Prepare, Promise, AcceptStopSign, Decide of a Stopsign, or
PrepareReq message has been sent but not been received. If so resends them",
`omnipaxos/src/sequence_paxos/mod.rs:229-237`), the leader already tracks each follower's
accepted index (`LeaderState::accepted_indexes`), and the captured suite asserts convergence
for a reconnected follower (`sync_full_test`).

**What actually happens (executed).**

```
$ cargo test -p omnipaxos --features "logging,toml_config" \
      --test audit_leader_change_adoption_test -- --nocapture --test-threads=1

test lost_acceptdecide_leaves_a_lagging_follower_behind_forever ...
[audit-lost-accept] round 10:  n1 decided 1 accepted 1 | n3 decided 0 accepted 0 leader Some((1, true))
[audit-lost-accept] round 120: n1 decided 1 accepted 1 | n3 decided 0 accepted 0 leader Some((1, true))
[audit-lost-accept] after 5000 rounds: decided 1=1 [1], 2=1 [1], 3=0 []
panicked: node 3 must eventually be synced up to the leader's log
FAILED
test lost_acceptdecide_is_repaired_by_reconnected ...
[audit-lost-accept-fix] after reconnected(1): node 3 decided 1 [1]
ok
```

(`notes/repro_lost_accept_final.log`; the harness is the in-process three-node `Net` used by
the other core probes — public API only, no kompact, no sockets, no sleeps.)

**Why nothing rescues it (source, with the one exception traced).** Both roles' resend paths
were read; one of the two paths I had suspected was then *disproved by execution*:

* *Leader* (`resend_messages_leader`, `sequence_paxos/leader.rs:371-403`): in `Phase::Accept`
  it re-sends only `Prepare` (to peers that never promised) and, when a StopSign exists,
  `AcceptStopSign`/`Decide`. There is no path that re-sends `AcceptDecide`/`AcceptSync` to a
  follower whose `accepted_idx` is behind, even though that index is tracked — the only
  consumer of `get_accepted_idx(follower)` is the StopSign comparison.
* *Follower* (`resend_messages_follower`, `sequence_paxos/follower.rs:240-269`): `Phase::Accept
  => ()` — a follower sitting in the accept phase re-sends nothing and has no notion of being
  behind. Its only detection is an incoming message with a *higher* sequence number
  (`handle_sequence_num`, `follower.rs:230-238`: `DroppedPreceding => self.reconnected(from)`;
  `Outdated => ()` — silently dropped, no resync).
* *Corrected by execution*: I first predicted that even a *single* lost `AcceptDecide` would
  strand a follower. That is **false** — instrumenting the message flow shows the leader's
  subsequent `Decide` then carries the *next* sequence number, which the follower classifies as
  `DroppedPreceding`, so it re-requests the log and heals itself:
  `["1->2 AcceptDecide", "1->3 AcceptDecide", "2->1 Accepted", "1->2 Decide", "1->3 Decide",
  "3->1 PrepareReq", "1->3 Prepare", "3->1 Promise", "1->3 AcceptSync", "3->1 Accepted"]`
  (`notes/repro_lost_accept_trace.log`). Recovery therefore hinges entirely on *some later
  message to that follower carrying a higher counter*. If the lost accept is the last thing
  the leader had to send (or the follower's counter has already reached the value the leader
  re-uses, so re-sends are `Outdated`), no such message ever arrives and the follower stays
  behind — which is exactly the state reproduced above.

**Necessary conditions.** A follower misses an `AcceptDecide` *and* the `Decide` that follows
it (or receives them only as `Outdated` messages), and the leader has no further traffic for
it — e.g. nothing else is appended, no StopSign resend applies, or the re-sent `Decide`
carries the counter the follower has already consumed. Two of three nodes remain able to
decide, so the cluster looks healthy while one replica is stale.

**Instrumented trace of the stall (diagnostic core copy only).** `work/diag/omnipaxos_liveness/`
is a copy of the core crate with tracing added to `resend_messages_leader`,
`resend_messages_follower` and `handle_sequence_num` (nothing else changed; the package is
renamed so it can share the build directory). 2 of 3 runs stalled at 122.91 s
(`notes/diag_stall_attempt_2.log`, `diag_stall_attempt_3.log`). The trace establishes:

* the leader (pid 2) sat for the whole stall at `state=(Leader, Accept) accepted_idx=9
  decided_idx=9 accepted_indexes=[5, 9, 10] promised=[1, 3] stopsign=true stopsign_decided=true`
  — it *knew* a follower was at accepted 5 while it had 9, and its only resend was the StopSign
  `Decide`;
* the follower those resends were addressed to classified them as out of date and dropped them,
  repeatedly, right to the end: `[diag pid 3] seq: from=2 msg=SequenceNumber { session: 3,
  counter: 1 } current=SequenceNumber { session: 3, counter: 1 } -> Outdated (accepted=10
  decided=9 state=(Follower, Accept))`. That is the source-level prediction
  (`send_decide(.., resend=true)` reuses `get_seq_num(follower)`, which the follower compares
  against `self.counter + 1`) observed directly;
* one node stopped ticking after ~6 resend periods (`state=(Follower, Accept) accepted=3
  decided=3`) — the node `sync_test.rs:220-224` stops to block the write quorum, which
  `stop_node` never restarts.

What the trace does **not** settle: mapping the panic's printed "Follower log" (decided 5) onto a
pid — the pids visible in the trace are at accepted 10/decided 9 and stopped-at accepted 3, so
the final link from "follower stranded at 5" to "no message ever nudges it" is implied rather
than observed end-to-end in that harness. The deterministic probe above does not depend on that
mapping; it shows the gap directly.

**Confirmed at the source, and observed in the trace: a re-sent `Decide` can never take
effect.** `send_decide(to, decided_idx, resend)` picks the sequence number with
`resend => self.leader_state.get_seq_num(to)` (the counter already in use) versus
`!resend => next_seq_num(to)` (`sequence_paxos/leader.rs:240-245`), and the follower only
accepts a message whose counter equals `self.counter + 1`
(`util.rs:382-390`: `Expected` if `counter == self.counter + 1`, `Outdated` if
`msg <= *self`, else `DroppedPreceding`), with `Outdated` handled as `=> ()` (silently
dropped, no resync). So when the StopSign path re-sends `Decide` with
`get_seq_num(follower)` — the very counter that follower has already applied — every resend is
`Outdated` by construction and can never advance the follower's decided index. That is exactly
what the instrumented run shows at its end:

```
[diag-leader pid 2] resend: … decided_idx=9 … accepted_indexes=[5, 9, 10] … stopsign_decided=true
[diag pid 3] resend: state=(Follower, Accept) current_seq_num=SequenceNumber { session: 3, counter: 1 } accepted=10 decided=9
[diag pid 3] seq: from=2 msg=SequenceNumber { session: 3, counter: 1 } current=SequenceNumber { session: 3, counter: 1 } -> Outdated
```

This is the defect in its own right (the StopSign decide-resend cannot help a lagging follower,
and `get_accepted_idx(follower)` — tracked by the leader — is only consulted for the *un*decided
stopsign case), independent of which node the harness's printed log came from.

Two caveats on reading that excerpt: the re-sends shown are addressed to a node whose own
`decided_idx` had already caught up (9, equal to the leader's), i.e. the trace proves the
*classification* (`Outdated`, silently ignored) and the leader's blindness to what each follower
actually needs, but it does not by itself show that this particular follower was the one the
test was waiting on. And the counter arithmetic alone does not make every resend useless: when
the fresh (non-resend) `Decide` for a new decision was *lost*, the counter stays where the
follower expects it next, so a resend is `Expected` and does heal it — the permanent
`Outdated` loop needs the follower to have already consumed the counter the leader keeps
re-using (as in the trace above).

*Residual inconsistency, reported rather than papered over:* in the passing runs the
instrumented copy prints `follower_id=3 leader_id=2 nodes_to_stop=[1]`, so the panic's
"Follower log" should be pid 3's — yet pid 3's traced `decided_idx` is 9 while that printed log
reads as `decided ≤ 5` (a single `Snapshotted(trimmed_idx 5)` item). Either the stalled run had a
different role assignment (my role print did not catch a stall in 4 further attempts) or the two
observations are of different nodes. `notes/diag_stall_attempt_2.log` and
`notes/diag_stall2_*.log` hold the raw evidence for whoever picks this up; an instrumented run
that stalls *while printing the role line* would settle it in one attempt.


**Relation to the `sync_full_test` stall (executed symptom).** The captured suite's own
`sync_full_test` also stalls, but only under CPU pressure: with the budget raised to 120 s in a
diagnostic config copy
(`work/diag/sync_harness`, same captured test binary), 2 of 4 runs sat out the full budget
(122.91 s) while the passing runs finish in 2.53 s — i.e. it is a stall, not slowness — and
3/4 runs failed at the captured 8 s budget under 8 CPU hogs on 4 cores (0/4 alone). The state
captured at those failures (`notes/workspace_tests.log`, `notes/stall_attempt_2.log`) is the
same one:

```
Follower log: [Snapshotted(trimmed_idx: 5, snapshot {1,2,3,6,7,4,5})]      <- decided 5, accepted 5
 Leader log: [Snapshotted(2, {1,2}), Decided(3), Decided(4), Decided(5), Decided(10),
              Decided(11), Decided(12), StopSign(config 2, …)]              <- decided 9
```

**Attribution of that stall is two-way, and I did not manage to settle it.** Either

* *the protocol gap above*: under load the "later message with a higher counter" that normally
  rescues a lagging follower never arrived, leaving it stale for the remaining 120 s; or
* *a harness expectation*: the scenario stops one node to block the write quorum
  (`sync_test.rs:220-224`) and `stop_node` never restarts it, so if the node the test then waits
  on is (or becomes) that stopped node, the wait cannot succeed no matter what the protocol
  does. The instrumented trace is consistent with this reading — one node stops ticking after
  ~6 resend periods (`accepted=3 decided=3`), and the only pid whose counter/decide loop the
  trace captures in detail (pid 3, `accepted=10 decided=9`) was *not* behind: its `decided_idx`
  equalled the leader's. The node the panic actually printed as "Follower log" (a log that reads
  as `decided ≤ 5`) could not be matched to a pid in the trace, so I cannot say which reading
  holds.

What is *not* in doubt, and does not depend on that question: the protocol gap reproduced
deterministically above, and the two mechanisms behind it (no accept re-send / no
follower-behind detection; a `Decide` re-send that reuses an already-consumed counter and is
dropped as `Outdated`, which the trace does show happening).

**Role attribution, confirmed in a stalled run.** With the test's role line printed by the
instrumented copy (`notes/diag_stall3_4.log`, 122.93 s, 1 stall in 6 loaded runs), the stalled
run is `follower_id=3 leader_id=2 nodes_to_stop=[1]`: the node the test waits on is the
reconnected follower (pid 3), the leader is pid 2, and the node *stopped* to block the write
quorum is pid 1 — which is therefore the node whose decided log the test keeps printing as
`decided ≤ 5` in some runs. That rules out my earlier "the test may be waiting on the node it
stopped" reading for this run, and leaves the leader-side picture: `decided_idx=9`,
`accepted_indexes=[5, 9, 10]` (i.e. it believed pid 1 was at 5 and pid 3 at 10), and its only
outgoing traffic the StopSign `Decide` re-sent with `get_seq_num(follower)`.
*One inconsistency remains and I report it rather than hide it*: in this same run the
instrumented pid 3 prints `accepted=10 decided=9`, while the test's own `read_decided_log()` on
pid 3 returns a single `Snapshotted(trimmed_idx 5)` item, which by construction means
`decided ≤ 5`. I could not reconcile the two readings of the same node's decided index within
this audit's budget; both raw logs are named here so the next auditor can instrument the
*print site* rather than the resend clocks.
The two readings *can* be reconciled in principle — a resync that carries a lower
`decided_idx` than the node already had would put the node back below its own earlier state
(`sync_log` assigns `state_cache.decided_idx` unconditionally), or the trace's last per-pid
print may simply precede the node's final transition — but neither is demonstrated here, and I
did not want to assert either without evidence.

**Resolved, with a correction to the framing.** Instrumenting the *print site* itself (the
panic handler of the copied test now also prints both nodes' `decided`/`accepted`/`compacted`
indices, `notes/diag_stall4_3.log` and `diag_stall4_4.log`, both stalling at 122.9 s) gives:

```
[diag-test] panic state: follower(pid 3) decided=9 accepted=10 compacted=5 |
                         leader(pid 2) decided=9 accepted=9 compacted=2
```

So at the end of the failed run the reconnected follower was **fully caught up** — `decided_idx`
equal to the leader's — while the test's own `read_decided_log()`, executed a few statements
earlier in the same handler, had returned a single `Snapshotted(trimmed_idx 5)` item
(`decided ≤ 5`). The two cannot both describe the same instant: the node was making progress
between the log read and the diagnostic print, i.e. it recovered *just after* the 120 s window
closed. That changes the reading of this scenario from "permanently stranded" to **"recovered
too late"** — a slow-recovery symptom under CPU starvation, not a permanent strand.

Consequences for the finding, stated separately:

* the **deterministic** probe (accept *and* decide lost, no CPU pressure) is still a permanent
  strand — 5000 rounds, no progress, fixed by one `reconnected(1)`. That remains the defect;
* the captured `sync_full_test` failures are **not** shown to be that same permanent strand:
  what is observed there is a recovery that completes after the budget expires, which is a
  liveness/latency concern of its own but a weaker claim;
* the source-level facts underpinning both (no accept re-send, no follower-behind detection,
  `Outdated` silently dropped, `resend=true` reusing an already-consumed counter) are unchanged.

**Checked alternative explanations.** (i) *Not a safety violation*: the leader's decided log is
intact and the follower is a strict prefix of it (decided 5 of 9) — availability, not
divergence. (ii) *Not slowness*: paired runs give 2.53 s when the nudge happens and ≥122.9 s
when it does not, with ~500 ms re-send periods available throughout. (iii) *Not the whole
resend machinery*: the `DroppedPreceding` path demonstrably works (trace above), so the gap is
specifically "no follower-behind detection and no accept re-send", not "no recovery at all".
(iv) *`reconnected` is a real remedy*: the second test shows it converges immediately, and the
captured `reconnect_test` passes for the same reason.

**Suggested fixes (not applied).** Have the leader re-send the missing suffix to a follower
whose `accepted_idx` is behind (the data is already tracked), or give the follower a phase
`Accept` timeout that re-requests the log, or make `Outdated` messages trigger a resync instead
of being dropped silently.
For the confirmed resend arithmetic specifically: increment the counter when re-sending
`Decide`/`AcceptStopSign` (`next_seq_num` rather than `get_seq_num`), or classify an
`Outdated` *decide* as a resync trigger on the follower side.


## Core probes run without finding a defect (negative results, executed)

Recorded so the negative results are as checkable as the findings, and so the next auditor
does not repeat them.

**Crash recovery (the `#[ignore]`d tests).** `omnipaxos/tests/recovery_test.rs` holds the
only tests that kill a node and restart it over `PersistentStorage` (RocksDB) — and all four
are `#[ignore]`d, so the captured runs never exercise crash recovery at all. Run explicitly
through the isolated executor (kompact + TCP):

```
$ cargo test -p omnipaxos --features "logging,toml_config" --test recovery_test \
      -- --ignored --nocapture --test-threads=1
test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
```

(log `notes/core_recovery_ignored.log`, execution
`executions/dbec5558a2bf4599b695f7606c12f037/stdout.txt`). Leader and follower crash/restart,
with proposals before and after the restart, all pass. So the recovery path itself works;
what the captured suite lacks is *any* automatic coverage of it.

**Stale new leader adopts a more up-to-date log.**
`work/omnipaxos/tests/audit_leader_change_adoption_test.rs` drives three nodes purely through
the public core API (no kompact, no sockets, deterministic). Node 3 is cut off while nodes 1
and 2 accept and decide entries 1-3, then node 3 is forced to become leader with a higher
ballot so it must adopt the followers' suffix from their `Promise`/`LogSync` — a shape the
captured `sync_test`/`reconnect_test` never drive (there the leader always has the longest
log). Both variants pass (log `notes/repro_adopt.log`):

* node 3 knows nothing at all (hard partition), i.e. `na > prep.n_accepted`;
* node 3 is in the *same* accepted round with an empty log (every `AcceptDecide` to it was
  dropped), i.e. the `na == prep.n_accepted && accepted_idx > prep.accepted_idx` branch.

In both cases all three nodes end with `decided_idx = 3` and the identical decided log
`[1, 2, 3]`: nothing lost, nothing duplicated, values preserved under the new ballot.

**Randomised partition + leader-churn safety soak.** Same harness, 4 seeds × 1000 rounds:
partitions redrawn every round, proposals issued on whichever node reports itself leader
(followers therefore take the `ProposalForward` path), and a random node forced to bump its
ballot every 29 rounds. Asserted after every round: agreement between all three nodes on
every decided entry of their common prefix; no entry value decided twice on any node;
`decided_idx <= accepted_idx` everywhere. All four seeds pass (log
`notes/repro_core_soak.log`); the final states show real divergence in progress
(e.g. seed 1: p1 decided 143 of 162 accepted, p2/p3 decided 158), so the soak did keep the
nodes apart and force re-synchronisation.

Scope of these negative results: everything runs inside one process (no process kill, no
disk, no partial writes), and the runtime layer is not exercised together with persistent
storage — see the unresolved list.

**Reconfiguration (StopSign) boundary.**
`work/omnipaxos_runtime/tests/audit_reconfiguration_boundary_test.rs` decides three entries,
reconfigures the two-node cluster, waits until both nodes observe the reconfiguration, and
then starts an actor on the *already stopped* cluster and subscribes from 0
(`notes/repro_stopsign.log`):

```
[audit-stopsign] core: decided_idx 4, suffix items 4, last StopSign(next_config {id 2}, …, true)
[audit-stopsign] runtime: subscriber got 4 items ["Decided(200)", "Decided(201)",
                "Decided(202)", "StopSign(decided=true)"]; Reconfigured event Some(4)
```

Core log, subscriber stream and event agree: `decided_idx` = the StopSign's index (4), the
decided suffix has exactly one item per decided position, the StopSign is delivered exactly
once and last with `decided = true`, no item is marked `Undecided`, the `Reconfigured` event
reports the StopSign's index, and the peer's log matches the subscriber's stream verbatim.

## Evidence-base caveats (not implementation defects)

* Two of the captured runtime tests assert essentially nothing:
  `append_notify_shutdown_error_when_actor_gone`
  (`omnipaxos_runtime/tests/async_runtime_test.rs:861`) accepts `Ok(_)` or *any* error
  variant, so it can only catch a panic, and
  `dropping_all_handles_shuts_actor_down` (`:793`) drops handles, sleeps, then calls
  `decided_idx()` on a *survivor* without asserting the shutdown it is named for. So
  "24/24 runtime tests pass" is a slightly weaker signal than it looks.
* The four crash-recovery tests are `#[ignore]`d (see above), and `recovery_test` is the
  only place recovery is exercised.
* Numbers in the baseline table are summed from the `test result:` lines of the saved logs;
  the counts I first quoted for the core suite were an eyeball estimate and have been
  replaced by the summed values (34 captured / 37 with the audit probes).

## Unresolved / next targets (not yet executed)

0. **Finding 3, remaining questions** (top priority): (a) confirm which message was missing in
   the *stalled* `sync_full_test` run by instrumenting a diagnostic copy of the core to log
   `(Role, Phase)`, `current_seq_num`, `accepted_idx`/`decided_idx` per node —
   `diag/omnipaxos_liveness/` was prepared for this and currently does not build (a copied core
   crate still pulls in the captured `omnipaxos_storage`, so two `omnipaxos` package instances
   collide; copying `omnipaxos_storage` too, with its `omnipaxos` path pointing at the copy, is
   the fix); (b) check whether a follower can be rescued by a `Decide` carrying a *higher*
   counter in general, i.e. which counter values the follower classifies as `Outdated` versus
   `DroppedPreceding` in steady state.
1. **Durability consequence of finding 1 (not demonstrated).** If the leader fails or is
   partitioned away between telling a caller `Ok(idx)` and flushing the batch that holds
   the caller's entry, the entry was never accepted by anyone while the caller was told it
   was decided. Demonstrating this needs a restart/partition harness the runtime's public
   API does not expose (storage ownership moves into the actor), so it is recorded as a
   source-based consequence, not an executed observation.
2. Stale placeholders in `unconfirmed_local` in the leadership-change / truncation cases
   (`AcceptSync` resync, buffered proposals being accepted on election): the ballot guard
   in `reconcile_unconfirmed` is supposed to cover these, and no counterexample was found
   by reading, but they were not exercised.
3. Core compaction paths (`try_trim`/`try_snapshot`/`create_diff_snapshot`) and the
   `unicache` encode/decode path: read, and the captured suites for them pass, but no
   adversarial cases were constructed.
4. Interaction of finding 2 with finding 1 (a compacted actor *and* a tracker victim in the
   same run) — not exercised.
5. *(closed this turn: the StopSign boundary probe passes — see the negative-results
   section. Only the hand-off to the *next* configuration's `OmniPaxos` instance, i.e.
   building config 2 from the StopSign metadata, remains unexercised.)*
6. Runtime layer over persistent storage / a real restart: the actor's `unconfirmed_local`
   and `last_seen_accepted_idx` are initialised from the recovered log, and no test covers
   restarting an *actor* (the runtime crate's dev-dependencies do not enable
   `omnipaxos_storage/persistent_storage`, so adding such a test would mean editing the
   captured `Cargo.toml`; a hand-written in-test `Storage` impl would avoid that).
7. Fault injection at the storage layer while the runtime tracker has entries in flight
   (the core's `atomic_storage_test` covers "Broken" storage at the core level only).
8. **Source-based suspicion, not executed: `MemoryStorage::append_on_prefix` underflow.**
   `omnipaxos_storage/src/memory_storage.rs` implements
   `append_on_prefix(from_idx, entries)` as `self.log.truncate(from_idx - self.trimmed_idx)`
   then append. If `from_idx < trimmed_idx` that subtraction underflows, `Vec::truncate`
   with a huge length is a no-op, and the suffix is appended at the *end* of the vector
   instead of replacing it from `from_idx` — silently mis-positioning every later entry
   (and `InternalStorage::sync_log` would set `accepted_idx = sync_idx + suffix.len()`, so
   the node's own bookkeeping would disagree with its storage). I could not construct a
   path that reaches it: for every `send_accsync` branch the leader's `sync_idx` is
   `followers_accepted_idx`, `min(prev_round_max_accepted_idx, followers_accepted_idx)`
   (which, when the target shares the max accepted round, equals the target's own accepted
   index) or `followers_decided_idx`, and for the follower→leader direction the snapshot
   branch's `sync_idx` is the *sender's* decided index; all of these are ≥ the receiving
   node's `compacted_idx` because `compacted ≤ decided ≤ accepted` holds. So this looks like
   defensive hardening rather than a live defect; a targeted test would need a
   `sync_idx < compacted_idx` construction I did not find.

## Files created by this audit

* `work/report.md` (this report)
* `work/omnipaxos_runtime/tests/audit_batch_alignment_test.rs` — reproduction + control
  (8 tests: 6 failing repros, 1 inserted-tick control, 1 `batch_size = 1` soak control)
* `work/omnipaxos_runtime/tests/audit_subscription_compaction_test.rs` — finding 2
  (2 failing repros: fully and partially compacted log; includes the hand-driven two-node
  core harness)
* `work/omnipaxos/tests/audit_leader_change_adoption_test.rs` — core probes: two
  stale-new-leader adoption tests and a 4-seed partition/leader-churn safety soak
  (all passing, i.e. negative results)
* `work/omnipaxos_runtime/tests/audit_reconfiguration_boundary_test.rs` — StopSign boundary
  probe (passing, i.e. negative result)
* `work/diag/omnipaxos_runtime/` — **diagnostic-only copy** of the runtime crate: `eprintln!`
  tracing of the batching bookkeeping, plus the candidate fix kept in a clearly marked
  block. It has its own `[workspace]` and absolute path deps so the captured workspace is
  untouched; `diff -u omnipaxos_runtime/src/actor.rs diag/omnipaxos_runtime/src/actor.rs`
  shows every difference made for diagnosis.
* `work/diag/sync_harness/tests/config/test.toml` — copy of the captured test config with
  `sync_test.wait_timeout_ms` raised to 120000, used (with the captured test binary, run
  from that directory) to tell "slow" from "stuck" for finding 3. Nothing else differs.
* `work/diag/omnipaxos_liveness/` — **diagnostic-only copy** of the core crate prepared for
  instrumenting finding 3, now building and instrumented (rename of package only; lib name
  kept as `omnipaxos`), with `work/diag/omnipaxos_storage_liveness/` as its storage copy.
* `work/notes/repro_run1.log`, `repro_run2.log`, `repro_run3.log`,
  `repro_run4.log`, `repro_run5.log`, `repro_run6.log`, `repro_cascade.log`,
  `repro_soak.log`, `repro_soak2.log`, `repro_soak_runs.log`, `repro_determinism.log`,
  `repro_remote_determinism.log`, `repro_stability.log`, `repro_run7.log`,
  `repro_subs.log`, `repro_subs_determinism.log`, `repro_adopt.log`, `repro_core_soak.log`,
  `repro_stopsign.log`, `core_recovery_ignored.log`, `diag_run1.log`, `diag_fix_run.log`,
  `diag_captured_suite.log`, `workspace_tests.log`, `stall_attempt_1..4.log`,
  `diag_core_build.log`, `diag_stall_attempt_1..3.log`,
  `diag_stall2_1..4.log` (instrumented copy with the test's role line printed),
  `diag_stall3_1..6.log` (role line caught together with a stall in run 4),
  `diag_stall4_1..6.log` (print-site instrumentation; two stalls, role line and both nodes'
  indices in the panic path),
  `repro_lost_accept.log`, `repro_lost_accept_trace.log`, `repro_lost_accept_trace2.log`,
  `repro_lost_accept_final.log`,
  `diag_fix_run2.log`, `rt_baseline.log`, `rt_allfeatures_build.log`,
  `rt_allfeatures_run.log`, `core_baseline.log`, `core_unicache_tests.log`,
  `build_tests.log`, `build_rt.log`
* `work/notes/diff_0.2.2_vs_work.txt` — diff of the captured `omnipaxos/src` against the
  published `omnipaxos` 0.2.2 crate (used only to tell genuine version drift apart from
  local edits; not a reference for the newer dev code)
* `work/ref/omnipaxos-0.2.2/` — extracted copy of the published 0.2.2 crate
