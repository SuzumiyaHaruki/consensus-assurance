# Openraft 0.9.25 audit

Scope: `openraft` 0.9.25 in this working copy. Source/logs are read-only; all
reproduction code and diagnostic changes are under `audit/` or clearly marked
test-only additions. The captured implementation under `../source` was not
changed.

| ID | Severity | Defect | Executed reproduction |
|----|----------|--------|-----------------------|
| F1 | High | Snapshot install purges logs before the state-machine install is durable; a crash leaves an unrecoverable state | `tests/tests/audit/t50_snapshot_install_purge_order.rs` |
| F2 | Medium | Documented-valid `PartialSuccess(None)` panics the leader at `replication_handler/mod.rs:194` | `tests/tests/audit/t10_partial_success_none.rs` |
| F3 | Low/Medium | `purge_batch_size = 0` underflows at `calc_purge_upto()`'s `purge_end - 1` | `engine/tests/audit_purge_batch_zero_test.rs` |
| F4 | Medium | `snapshot_max_chunk_size = 0` makes `Chunked::send_snapshot()` send zero-byte chunks forever | `network/snapshot_transport.rs::tests::audit_chunk_size_zero_loops_forever` |
| F5 | Low/Medium | Blocking `add_learner()` returns `Ok` on a leadership change while the learner is still not caught up | `tests/tests/audit/t11_add_learner_blocking_leader_change.rs` |
| F6 | Low/Medium | `heartbeat_interval = 0` is accepted and makes the tick loop emit without a delay (77 ticks/100 ms) | `core/tick.rs::tests::audit_zero_interval_busy_loops` |

## Confirmed findings

### F1 (High): A snapshot install persists the log purge before the state-machine install is durable

#### Expected behavior and basis

Snapshot installation is documented as three ordered steps: truncate
conflicting non-committed logs, install the snapshot into the state machine,
then purge the logs covered by the snapshot
(`openraft/src/docs/protocol/snapshot_replication.md`, "After truncating
conflicting logs, the snapshot is installed. The final step is to purge logs
the snapshot contains.").

The log-store contract reinforces the ordering: `RaftLogStorage::purge` /
`RaftStorage::purge_logs_upto` deletes *applied* log entries
(`openraft/src/storage/v2.rs`, `openraft/src/storage/mod.rs`). A node that
crashes after the purge is durable but before
`RaftStateMachine::install_snapshot()` returns has neither the purged logs nor
the snapshot state. Its persisted `last_purged_log_id` is ahead of both the
state machine's `last_applied` and the current snapshot, so startup cannot
reconstruct a consistent state.

#### Affected code

- `openraft/src/engine/handler/following_handler/mod.rs:278-330`
  (`install_full_snapshot`)
- `openraft/src/engine/engine_impl.rs:484-513`
  (`handle_install_full_snapshot`)
- `openraft/src/core/raft_core.rs:894-911` (`run_engine_commands` stops at a
  condition only for the command carrying it) and the `Command::StateMachine`
  / `Command::PurgeLog` arms in `run_command`.

`install_full_snapshot()` queues the state-machine install at lines 321-322,
then immediately sets `state.purge_upto` and calls `log_handler().purge_log()`
at lines 324-325, which queues `Command::PurgeLog`. The condition returned at
lines 327-329 is attached only to the client `Respond` command in
`handle_install_full_snapshot`. `RaftCore::run_command` sends
`Command::StateMachine` to the worker with a non-blocking channel send, then
awaits `log_store.purge()` for the purge command. The purge therefore becomes
durable while the worker may still be inside
`RaftStateMachine::install_snapshot()`.

The existing unit test
`engine::tests::install_full_snapshot_test::test_handle_install_full_snapshot_no_conflict`
already asserts this ordering: `StateMachine(InstallFullSnapshot)`,
`PurgeLog`, then `Respond { when: StateMachineCommand(seq) }`.

#### Necessary conditions

1. A follower/learner receives a snapshot whose `last_log_id` is greater than
   its committed log id, so `install_full_snapshot()` does not return early.
2. The application's `install_snapshot()` has not yet made the new snapshot
   durable/current when `PurgeLog` completes. The trait only guarantees the
   snapshot is installed *before `install_snapshot()` returns*, so this is
   permitted and is the normal window for a slow or blocked install.
3. The process crashes (or the task is killed) in that window, after the log
   store's purge is persisted and before the install completes.

The window is not specific to the in-memory test store. The bundled
`rocksstore` and `sledstore` implementations update the state machine and the
snapshot metadata in separate durable steps (`rocksstore/src/lib.rs:558-584`,
`sledstore/src/lib.rs:628-652`), and the `RaftStateMachine` trait only
promises that both are updated *before `install_snapshot()` returns*. A crash
between the log purge and that return can therefore leave the real store with
`last_applied` and/or `snapshot_meta` behind `last_purged_log_id`. This was
checked by source inspection, not executed (those stores were not built in
this run).

#### Observed behavior

The reproduction is
`tests/tests/audit/t50_snapshot_install_purge_order.rs` with the test-only
hook `BlockOperation::InstallSnapshot` in `memstore` (see
`audit/diagnostics/memstore-install-block.patch`). The hook only delays the
memstore `install_snapshot()` call; the openraft code is unmodified.

Command:

```
cargo test -p tests --test audit -- --nocapture
```

Result: the test passes, i.e. it confirms the defect:

- While the state-machine install is still pending (its adapter lock is held,
  and `applied_state()` times out), the follower's log store already reports
  `last_purged_log_id == snapshot.meta.last_log_id`.
- Recreating the persisted state left by a crash at that point (log store
  purged to the snapshot, state machine still at its pre-install state, no
  snapshot at the snapshot index) and starting `Raft::new()` produces:

```
invalid state: expect: self.purge_upto()(Some(LogId { leader_id: LeaderId { term: 1, node_id: 0 }, index: 6 })) <= self.committed()(None) at openraft/src/raft_state/mod.rs:192
```

The panic is raised by `RaftState::validate()` when the restarted node's
`RaftCore` dereferences the reconstructed state. `Raft::with_raft_state()`
returns a fatal error; the node cannot serve or recover from this state.
Even if the state machine had managed to save the new snapshot data but had
not persisted its applied state, the other validation branch
(`snapshot_last_log_id <= committed`) would fail instead.

Captured output: `audit/logs/repro-stderr.txt`,
`audit/logs/repro-stdout.txt`.

#### Alternative explanations checked

- The observation is not caused by the test's logging thread: the purge is
  reported by the follower's own `RaftCore` command path
  (`run command: PurgeLog ... index 6`) before the memstore install hook
  completes.
- The first version of the reproduction shared one `Adaptor` lock between the
  log store and state machine, which made the inspection block behind the
  install. The final reproduction uses separate adaptors/locks, so the log
  store is readable while the state-machine install is blocked.
- The snapshot install does not return early: the target node starts with no
  committed log, and the snapshot's `last_log_id` is greater, so
  `install_full_snapshot()` proceeds.
- This is not the documented "crash after installing snapshot and before
  purging logs" case; that order is safe. The failing order is the reverse,
  which the code permits because the purge command has no install-completion
  condition.

#### Remediation direction

The purge must be ordered after the state-machine install has completed, e.g.
by making `PurgeLog` wait for the install command's sequence number (the same
condition already used for the response), or by emitting the purge only from
the install-completion callback. A store-side atomic "snapshot + applied
state + purge" transaction would also close the window, but the trait does
not currently require stores to provide one.

### F2 (Medium): `PartialSuccess(None)` is an allowed network response but panics the leader in debug builds

#### Expected behavior and basis

`AppendEntriesResponse::PartialSuccess(Option<LogId>)` is public API. Its
contract says the returned matching log id must be greater than or equal to
the request's `prev_log_id`
(`openraft/src/raft/message/append_entries.rs:66-82`). When a leader sends
from the beginning of the log, `prev_log_id` is `None`; the response
`PartialSuccess(None)` is therefore valid (the implementation's own
`debug_assert_partial_success()` accepts `None >= None`). It means "the
target accepted none of the entries yet", not a conflict.

#### Affected code

- `openraft/src/replication/mod.rs:485-490` handles
  `AppendEntriesResponse::PartialSuccess(matching)` and forwards it as
  `Ok(matching)` through `finish_success_append()` (lines 856-875).
- `openraft/src/engine/handler/replication_handler/mod.rs:187-194`
  (`update_matching`) unconditionally asserts
  `debug_assert!(log_id.is_some(), "a valid update can never set matching to None")`.

#### Necessary conditions

1. The leader is sending an AppendEntries request with `prev_log_id = None`,
   e.g. the first replication to a new learner whose progress is empty.
2. The network layer returns `PartialSuccess(None)`. This is permitted by the
   public contract when it forwards zero entries (for example, a transport
   that applies a zero entry quota or a zero-sized payload budget) while the
   follower did not report a conflict.

#### Observed behavior

The reproduction is `tests/tests/audit/t10_partial_success_none.rs`. It sets
the test router's AppendEntries quota to 0 before creating a learner, so the
router truncates the first request's entries to zero and maps the follower's
`Success` to `PartialSuccess(prev_log_id=None)`.

Command:

```
cargo test -p tests --test audit partial_success_none -- --nocapture
```

The test passes by observing the resulting fatal stop, and the captured
stderr contains:

```
panicked at openraft/src/engine/handler/replication_handler/mod.rs:194:9:
a valid update can never set matching to None
```

Because the panic occurs in RaftCore, the leader task dies and the node can
no longer serve state. In a release build the `debug_assert!` is compiled
out; `ProgressEntry::update_matching()` then accepts `None` and retries, so
the release behavior is a retry rather than a crash. Debug builds, the
crate's test suite, and any deployment retaining debug assertions are
affected.

Captured output: `audit/logs/repro2-stderr.txt`,
`audit/logs/repro2-stdout.txt`.

#### Alternative explanations checked

- This is not a `Conflict` response: the follower returned `Success`; the
  router only converted it to a partial success because its quota truncated
  all entries. A `Conflict` takes the separate `AppendEntriesResponse::Conflict`
  path and is handled without this assertion.
- The `PartialSuccess(Some(..))` case is covered by the existing
  `t10_append_entries_partial_success` test and works; only the documented
  `None` case trips the assertion.
- The response is not malformed per the public contract: `None >= None` and
  the request's `prev_log_id` is `None`.

#### Remediation direction

Treat `Ok(None)` from a partial success as "no matching progress yet": update
the leader clock but leave `matching` unchanged and retry. Either remove the
assertion or make `finish_success_append` not report a matching update when
the matching id is `None`.

### F3 (Low/Medium): `purge_batch_size = 0` underflows in `calc_purge_upto()`

#### Expected behavior and basis

`purge_batch_size` is a public `u64` config option ("The minimal number of
applied logs to purge in a batch", `openraft/src/config/config.rs:183-185`).
`Config::validate()` does not reject 0, and the clap parser accepts
`--purge-batch-size 0`. A zero minimum reasonably means "purge without a
minimum batch"; the policy code must still handle the case where there is
nothing to purge.

The acceptance was executed: `audit_config_accepts_zero_limits` in
`openraft/src/engine/tests/audit_purge_batch_zero_test.rs` builds a `Config`
with `--purge-batch-size=0` and `--snapshot-max-chunk-size=0` and both fields
come back as 0 (`audit/logs/repro-config-zero-stdout.txt`).

After a snapshot, `LogHandler::calc_purge_upto()` computes
`purge_end = snapshot_last_log_id.next_index().saturating_sub(max_keep)`. With
the default `max_in_snapshot_log_to_keep = 1000` and a snapshot at index 0,
`purge_end` is 0. The guard
`last_purged_log_id.next_index() + batch_size > purge_end` is false for
`batch_size = 0` and `purge_end = 0`, so the code falls through to
`self.state.log_ids.get(purge_end - 1)`.

#### Affected code

- `openraft/src/engine/handler/log_handler/mod.rs:78-110`, especially the
  subtraction at line 104.
- `openraft/src/config/config.rs:183-185` and `Config::validate()` (no
  zero check).

#### Necessary conditions

1. `purge_batch_size = 0`.
2. `snapshot_meta.last_log_id.next_index() <= max_in_snapshot_log_to_keep`.
   A snapshot at index 0 with the default `max_keep = 1000` satisfies this.
3. `calc_purge_upto()` runs, e.g. from `schedule_policy_based_purge()` after a
   snapshot build (a fresh single-node cluster plus `trigger().snapshot()` is
   enough).

#### Observed behavior

Reproduction: `openraft/src/engine/tests/audit_purge_batch_zero_test.rs`.

Command:

```
cargo test -p openraft --lib audit_calc_purge_upto_zero_batch -- --nocapture
```

The test passes by catching the panic; the captured stderr contains:

```
panicked at openraft/src/engine/handler/log_handler/mod.rs:104:45:
attempt to subtract with overflow
```

In a release build the subtraction wraps to `u64::MAX`; `LogIdList::get()`
returns `None`, the debug assertion is compiled out, and the function returns
`None`. The zero-batch configuration therefore silently skips the purge in
release and panics in debug, instead of either purging or reporting an
invalid configuration.

Captured output: `audit/logs/repro3-stderr.txt`,
`audit/logs/repro3-stdout.txt`.

#### Alternative explanations checked

- With `purge_batch_size = 1` and the same snapshot, the guard
  `0 + 1 > 0` returns `None` before the subtraction; the existing
  `test_calc_purge_upto` covers that path.
- `max_keep = 0` with a snapshot at index 0 makes `purge_end = 1`, so the
  subtraction is `get(0)` and is valid. The underflow needs the larger
  `max_keep` boundary (the default) combined with a zero batch.

#### Remediation direction

Return `None` when `purge_end == 0` before subtracting, and/or reject
`purge_batch_size == 0` in `Config::validate()`. If zero is intended to mean
"no batching", handle it explicitly rather than relying on the
`+ batch_size` guard.

### F4 (Medium): `snapshot_max_chunk_size = 0` makes snapshot sending loop forever

#### Expected behavior and basis

`snapshot_max_chunk_size` is a public config option, documented as "The
maximum snapshot chunk size allowed when transmitting snapshots (in bytes)"
(`openraft/src/config/config.rs:173-175`). The parser accepts `0` and
`Config::validate()` does not reject it. The chunked snapshot transport should
either reject an unusable chunk size or make progress; it must not send
zero-byte chunks indefinitely.

This was executed: `audit_config_accepts_zero_limits` verifies that
`Config::build(&["foo", "--purge-batch-size=0", "--snapshot-max-chunk-size=0"])`
succeeds and preserves both zeros.

#### Affected code

- `openraft/src/network/snapshot_transport.rs:151-235`
  (`Chunked::send_snapshot`), especially the read loop and
  `let done = (offset + n_read as u64) == end;`.
- `openraft/src/config/config.rs:173-175`, `Config::validate()`.

`send_snapshot` allocates `Vec::with_capacity(chunk_size)`, reads until the
buffer is full or EOF, and computes `done` from `offset + n_read`. With
`chunk_size = 0`, `n_read` is always 0, `done` stays false for a non-empty
snapshot, the receiver writes zero bytes, and `offset` never advances.

#### Necessary conditions

1. `snapshot_max_chunk_size = 0` (accepted by the config parser).
2. A non-empty snapshot is transmitted through `Chunked::send_snapshot`, the
   default implementation of `RaftNetwork::full_snapshot` for
   `SnapshotData: AsyncRead + AsyncWrite + AsyncSeek`.

#### Observed behavior

The audit test is
`openraft/src/network/snapshot_transport.rs::tests::audit_chunk_size_zero_loops_forever`
(behind `generic-snapshot-data`, like the other transport tests).

Command:

```
cargo test -p openraft --lib --features generic-snapshot-data \
  audit_chunk_size_zero -- --nocapture
```

The test wraps `send_snapshot()` in a 100 ms timeout; it times out, and the
captured stderr reports:

```
audit_chunk_size_zero: 42 zero-byte chunks in 100ms, offsets[..8]=[0, 0, 0, 0, 0, 0, 0, 0]
```

The snapshot replication task is stuck in this loop: it never reaches the
next chunk and never completes the install. If the target is needed for a
quorum or a membership change, the cluster cannot make progress with that
target.

Captured output: `audit/logs/repro4-stderr.txt`,
`audit/logs/repro4-stdout.txt`.

#### Alternative explanations checked

- With a positive chunk size, the existing `test_chunked_reset_offset_if_snapshot_id_mismatch`
  and the other transport tests pass; the loop is specific to a zero chunk
  size.
- The receiver's `Streaming::receive()` accepts a zero-byte write and returns
  `Ok(false)`; it does not reject the empty chunk. The sender, not the
  follower, is the one that fails to advance.

#### Remediation direction

Reject `snapshot_max_chunk_size == 0` in `Config::validate()`, or guard
`chunk_size == 0` in `Chunked::send_snapshot` (e.g. treat it as the whole
snapshot or return a clear network error). Do not enter the chunk loop with a
zero-sized buffer.

### F5 (Low/Medium): Blocking `add_learner()` can return `Ok` before the learner catches up

#### Expected behavior and basis

`Raft::add_learner(id, node, blocking = true)` is documented to block until
"the leader believes the logs on the new node is up to date, i.e., ready to
join the cluster, as a voter, by calling `change_membership`"
(`openraft/src/raft/impl_raft_blocking_write.rs:125-140`). Returning `Ok`
while the learner's matching log id is still `None` violates that contract.

#### Affected code

- `openraft/src/raft/mod.rs:735-780` (`check_replication_upto_date`).
- `openraft/src/raft/impl_raft_blocking_write.rs:125-180` (`add_learner`).

`check_replication_upto_date()` returns `Ok(None)` when it should stop
waiting because the node is no longer the leader, the learner was removed, or
there is no replication metrics (its own comment lists these as reasons to
quit waiting). `add_learner()` uses the predicate "predicate returns Ok" as
"success" and returns the original membership-add response. It does not
distinguish `Ok(None)` (not caught up / no longer leader) from
`Ok(Some(matching))` (up-to-date).

#### Necessary conditions

1. `add_learner(..., blocking = true)` is called; the initial membership-add
   log commits, so the function enters its blocking wait.
2. The learner is not up to date (for example, its network is blocked or the
   node is unreachable).
3. Leadership changes while the wait is active (or the learner is removed, or
   replication metrics disappear). The old leader's `metrics.replication`
   becomes `None`, `check_replication_upto_date` returns `Ok(None)`, and the
   wait completes.

#### Observed behavior

The reproduction is
`tests/tests/audit/t11_add_learner_blocking_leader_change.rs`. A two-voter
cluster has a blocked learner 2; `add_learner(2, (), true)` waits; node 1 is
then forced to campaign, node 0 grants the vote and loses leadership. The
blocking call returns `Ok` while the learner has no matching log:

```
add_learner returned Ok after leadership change; learner-2 matching=Some(None), cluster log_index=4
```

The test passes by asserting the false success (and that the learner's
matching is below the cluster log index). Command:

```
cargo test -p tests --test audit add_learner_blocking_leader_change -- --nocapture
```

Captured output: `audit/logs/repro5-stderr.txt`,
`audit/logs/repro5-stdout.txt`.

#### Alternative explanations checked

- This is not a failure of the initial membership add: the add's
  `ChangeMembership` step committed and the learner is present in node 1's
  membership. The failure is specifically the blocking-readiness guarantee.
- The learner is not slow-but-eventually-up-to-date at the instant of return:
  its network RPC is blocked (`set_rpc_blocked(2, true)`), and node 1's
  replication metrics for learner 2 are `Some(None)` (no matched log) while
  the cluster log index is 4.

#### Remediation direction

Propagate the `Ok(Some(matching))`/`Ok(None)` distinction: return
`ForwardToLeader` (or another explicit error) when the wait ends because the
leader changed or the learner was removed, and return `Ok` only when the
learner actually reached the replication target. At minimum, document that
`Ok` from the blocking form means only "membership add committed", not
"learner is ready".

### F6 (Low/Medium): `heartbeat_interval = 0` creates an unthrottled tick loop

#### Expected behavior and basis

`heartbeat_interval` is a public config option. `Config::validate()` rejects
an election timeout that is not greater than the heartbeat interval, but it
accepts a heartbeat interval of 0. A zero interval means the leader's tick
loop has no delay, and every AppendEntries RPC uses a zero timeout
(`ReplicationCore::send_log_entries()` constructs `RPCOption` from
`heartbeat_interval`). The config parser should reject this unusable value or
the runtime should clamp it; the documented way to disable heartbeats is
`enable_heartbeat = false`.

#### Affected code

- `openraft/src/config/config.rs:255-280` (`Config::validate`).
- `openraft/src/core/tick.rs:70-125` (`Tick::spawn`/`tick_loop`).
- `openraft/src/replication/mod.rs:405-430` (the per-RPC timeout uses
  `heartbeat_interval`).

#### Necessary conditions

1. `heartbeat_interval = 0`, accepted by `Config::build`/`validate`.
2. The tick loop is enabled (`enable_tick = true`, the default).

#### Observed behavior

`audit_config_accepts_zero_limits` confirms that
`Config::build(&["foo", "--heartbeat-interval=0"])` returns a valid config
with `heartbeat_interval == 0`. The audit test
`core::tick::tests::audit_zero_interval_busy_loops` starts the tick emitter
with a zero interval and observes:

```
zero-interval ticks in 100ms: 77
```

A normal 50 ms heartbeat interval would produce about 2 ticks in the same
window; the zero interval is limited only by the runtime scheduler. Each tick
also drives the leader's heartbeat path, whose RPC timeout is zero, so this is
an unthrottled liveness/load failure rather than a useful configuration.

Command:

```
cargo test -p openraft --lib audit_zero_interval_busy_loops -- --nocapture
```

Captured output: `audit/logs/repro6-stdout.txt`,
`audit/logs/repro6-stderr.txt`.

#### Alternative explanations checked

- A positive interval is throttled normally; the existing `test_shutdown`
  uses 100 ms and only receives a few ticks.
- The high rate is not a test-harness artifact: the tick emitter itself is
  driven directly with `Duration::ZERO`, and the count is taken from its
  output channel.

#### Remediation direction

Reject `heartbeat_interval == 0` in `Config::validate()` (with a clear
error), or clamp it to a sensible minimum. `enable_heartbeat = false` already
exists for applications that want to disable heartbeats explicitly.

## Checks performed that did not reveal a defect

All of these were executed against this working copy:

- `cargo test -p openraft --lib`: 194 passed (the captured baseline had 188;
  the audit-only tests add six test functions).
- `cargo test -p tests`: all integration/cluster tests passed (0 failed;
  one ignored test in `append_entries`), including the three audit
  integration tests.
- `cargo test -p tests --features loosen-follower-log-revert`: all passed,
  including `t60_feature_loosen_follower_log_revert` and
  `t60_follower_clear_restart_recover`.
- Feature suites: `--features single-term-leader` (187 passed) and
  `--features serde` (190 passed) were run before the audit-only tests were
  added; `--features generic-snapshot-data` (204 passed after the F4/F6 audit
  test; the captured baseline had 197).
- `OPENRAFT_STORE_DEFENSIVE=on cargo test -p tests` and
  `OPENRAFT_NETWORK_SEND_DELAY=30 cargo test -p tests`: all passed.
- The consensus-relevant v0.9.25 changelog fixes were located in code and
  their regression tests were found to pass: sorted-above-granted progress,
  bounded core-stop wait, empty
  `limited_get_log_entries`, `current_leader` without an `is_voter` filter,
  election trigger on a leader, snapshot for a fully purged log, background
  join of removed replication, and purged-membership reset on snapshot
  install.
- Randomized model tests, added under `audit/repro/`:
  - `VecProgress` update/granted against a brute-force quorum computation for
    uniform majorities (n=1..9, 20 seeds x 300 steps) and a joint majority
    (50 seeds x 500 steps). No mismatch.
  - `LogIdList` append/extend/truncate/purge against a `Vec<LogId>` model
    (60 seeds x 400 operations). No mismatch.
- `cargo test -p tests --test audit partial_success_none -- --nocapture`
  reproduces F2 (the test is designed to pass while observing the fatal
  stop); see the logs above.

## Artifacts and commands

- Main report: `report.md`.
- Reproduction sources: `audit/repro/` (`t50_snapshot_install_purge_order.rs`,
  `t10_partial_success_none.rs`, `t11_add_learner_blocking_leader_change.rs`,
  `audit_vec_progress_test.rs`, `audit_log_id_list_test.rs`,
  `audit_purge_batch_zero_test.rs`, `audit-main.rs`). The F4 test lives in
  the `snapshot_transport.rs` test module and is included in the patch.
- Captured outputs: `audit/logs/repro-f1-current-{stdout,stderr}.txt`,
  `repro2-*` (F2), `repro3-*` (F3), `repro4-*` (F4), and
  `repro5-*` (F5), `repro6-*` (F6), and `repro-config-zero-*` (the
  config-acceptance test).
- Patches: `audit/diagnostics/memstore-install-block.patch` (test-only
  install delay hook), `openraft-audit-tests.patch` (all openraft test-only
  additions, including F3/F4), and `tests-audit.patch` (the two `tests`
  package integration tests).
- Commands:

```
cargo test -p tests --test audit
cargo test -p tests --test audit partial_success_none -- --nocapture
cargo test -p tests --test audit add_learner_blocking_leader_change -- --nocapture
cargo test -p openraft --lib audit_calc_purge_upto_zero_batch -- --nocapture
cargo test -p openraft --lib audit_config_accepts_zero_limits -- --nocapture
cargo test -p openraft --lib audit_zero_interval_busy_loops -- --nocapture
cargo test -p openraft --lib --features generic-snapshot-data audit_chunk_size_zero -- --nocapture
```

The full-suite tracing logs under `tests/_log` grew to ~11 GB and were
removed after the targeted logs above were copied; they are reproducible with
the commands.

## Unresolved / further work

- The same ordering pattern exists for the state-machine install's
  `truncate_logs()` (uncommitted logs only, which is safe) and for the
  in-memory membership update; those were not separately reproduced.
- The changelog explicitly notes that a panic during `apply()` leaves a
  client responder held rather than dropped (a different failure mode from
  the bounded core-stop fix). Not reproduced or classified here.
- Source-based suspicion, not reproduced: `Command::QuitLeader` only sets
  `leader_data = None`; it does not remove the entries in `self.replications`.
  A leader that steps down can therefore retain idle or blocked replication
  tasks until a later `RebuildReplicationStreams` removes them.
- `install_snapshot_timeout = 0` is also accepted by the parser/`validate`;
  its replication/timeout consequences were not separately reproduced.
- Example crates and non-workspace stores were not built; only the `openraft`,
  `tests`, and `memstore` packages were exercised.
