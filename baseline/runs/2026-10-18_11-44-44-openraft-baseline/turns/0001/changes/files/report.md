# Openraft 0.9.25 audit

Scope: `openraft` 0.9.25 in this working copy. Source/logs are read-only; all
reproduction code and diagnostic changes are under `audit/` or clearly marked
test-only additions. The captured implementation under `../source` was not
changed.

## Confirmed finding

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

## Checks performed that did not reveal a defect

All of these were executed against this working copy:

- `cargo test -p openraft --lib`: 188 passed.
- `cargo test -p tests`: all integration/cluster tests passed (0 failed;
  one ignored test in `append_entries`).
- Feature suites: `cargo test -p openraft --lib --features single-term-leader`
  (187 passed), `--features generic-snapshot-data` (197 passed),
  `--features serde` (190 passed).
- `OPENRAFT_STORE_DEFENSIVE=on cargo test -p tests` and
  `OPENRAFT_NETWORK_SEND_DELAY=30 cargo test -p tests`: all passed.
- Every v0.9.25 changelog fix was located in code and its regression test was
  found to pass: sorted-above-granted progress, bounded core-stop wait, empty
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

## Unresolved / further work

- The same ordering pattern exists for the state-machine install's
  `truncate_logs()` (uncommitted logs only, which is safe) and for the
  in-memory membership update; those were not separately reproduced.
- The changelog explicitly notes that a panic during `apply()` leaves a
  client responder held rather than dropped (a different failure mode from
  the bounded core-stop fix). Not reproduced or classified here.
- Example crates and non-workspace stores were not built; only the `openraft`,
  `tests`, and `memstore` packages were exercised.
