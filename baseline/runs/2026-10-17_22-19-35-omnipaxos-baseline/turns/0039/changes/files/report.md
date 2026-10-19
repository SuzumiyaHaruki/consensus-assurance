# OmniPaxos correctness audit

Audited source identity: `827f304846ab0c5aa40910b6f6cdce1d4ddf8e12`.

## Scope and method

The audit covers the Rust workspace in the supplied source tree, with emphasis on the
`omnipaxos` protocol crate and its public runtime wrapper. I reviewed protocol safety
conditions, log synchronization, batching, recovery, configuration validation, and public
read/subscription behavior. Source observations are distinguished below from executed
reproductions. All reproduction files and logs are retained under `work/`.

The offline Cargo cache contains OmniPaxos 0.2.2. It was unpacked under `reference/` only
as a structural comparison point; the supplied source was not modified.

## Findings

The highest-impact defects are finding 8, where delta snapshot synchronization exposes values
from an obsolete receiver suffix as decided snapshot state; finding 10, where a failed
persistent atomic transaction leaks state into a later transaction; finding 13, where a
cloned LFU UniCache decoder silently reconstructs the wrong original value; and finding 23,
where bincode cannot deserialize LRU cache state. Finding 26 additionally allows synchronization
to move a follower's decided index backward. Other confirmed
issues are sparse-ID compaction failure, cross-epoch ballot ordering, non-increasing
reconfiguration IDs, two runtime liveness/cursor defects, feature/macro composition build
failures, zero-ID configuration panic, a zero flush timeout that never fires, and a
pre-election StopSign that is never forwarded. The focused reproductions are local; the
snapshot defect is also corroborated by intermittent failures of the shipped `sync_full_test`.

### 1. Trim cannot progress with sparse/non-1-based node IDs

**Status:** executed, deterministic.

**Expected behavior.** Node IDs are arbitrary `u64` values; the configuration docs do not
require IDs to be contiguous or start at 1. The implementation itself exercises sparse IDs
in `util::tests::preparable_peers_test` (`[6, 7, 8]` and `[7, 1, 100, 4, 6]`). After every
configured node has accepted and decided a prefix, `trim(Some(idx))` should trim it.

**Affected code.** [`LeaderState::with`](../source/omnipaxos/src/util.rs:96) allocates
`accepted_indexes` with length `max_pid`, including slots for unconfigured IDs.
[`get_min_all_accepted_idx`](../source/omnipaxos/src/util.rs:186) takes the minimum over the
entire vector rather than configured nodes. [`SequencePaxos::trim`](../source/omnipaxos/src/sequence_paxos/mod.rs:141)
uses that value as its safety threshold.

**Necessary condition.** The cluster contains an ID gap below its maximum ID, for example
nodes `[1, 10, 20]`, and the leader asks to trim a prefix accepted by all configured nodes.

**Observed behavior.** The unconfigured slots remain zero forever, so the computed minimum
is 0. In the reproduction, all three nodes had accepted and decided index 3, while
`trim(Some(3))` returned `Err(NotAllDecided(0))`. A contiguous-ID control, `[1, 2, 3]`,
succeeded. `trim(None)` is similarly reduced to a no-op at index 0. This is a compaction
liveness/supported-configuration defect, not a demonstrated log-safety violation.

**Reproduction.** `audit_runner/src/bin/core_checks.rs`, check `sparse-id trim`.
Command and output: `repro_core_checks.log`. The test-only equivalent is
`omnipaxos/tests/audit_sparse_ids_trim.rs`.

### 2. Ballot ordering ignores `config_id`, allowing a stale configuration to supersede the current epoch

**Status:** executed for ordering and protocol effect; protocol impact requires a delayed
cross-configuration message.

**Expected behavior.** `ClusterConfig::configuration_id` identifies the configuration and is
documented to increase across reconfigurations
([source](../source/omnipaxos/src/omni_paxos.rs:93)). A ballot from an older configuration
must not replace a promise in the current configuration merely because its round counter is
larger. Independently, Rust's `Ord` contract requires `cmp(a, b) == Equal` exactly when
`a == b`; `Ballot` derives equality over all fields, including `config_id`.

**Affected code.** [`Ballot::cmp`](../source/omnipaxos/src/ballot_leader_election.rs:53)
compares only `(n, priority, pid)`. [`handle_prepare`](../source/omnipaxos/src/sequence_paxos/follower.rs:13)
uses `old_promise < prep.n` to decide whether to replace its promise.

**Observed behavior.** Ballots `{config_id:1, n:5, pid:1}` and
`{config_id:2, n:5, pid:1}` compare `Equal` but are not equal. More concretely, a node in
configuration 2 that had promised `{config_id:2, n:1, pid:2}` accepted a crafted Prepare
from configuration 1 with `{config_id:1, n:2, pid:1}`; its promise changed to the old
configuration. The first observation is unconditional; the protocol effect requires a
delayed/out-of-scope old-configuration message being delivered to a new instance.

**Reproduction.** `audit_runner/src/bin/core_checks.rs`, checks
`Ballot Ord/Eq consistency` and `cross-epoch Prepare rejection`; see
`repro_core_checks.log`. Test-only equivalent:
`omnipaxos/tests/audit_config_validation.rs`.

### 3. Reconfiguration accepts a non-increasing next configuration ID

**Status:** executed, deterministic.

**Expected behavior.** The public field documentation requires the next configuration ID to
be greater than the previous one, and `OmniPaxos::reconfigure` documents that invalid new
configurations return `ProposeErr::ConfigError` ([source](../source/omnipaxos/src/omni_paxos.rs:375)).

**Affected code.** [`OmniPaxos::reconfigure`](../source/omnipaxos/src/omni_paxos.rs:379)
calls `ClusterConfig::validate`, but [`validate`](../source/omnipaxos/src/omni_paxos.rs:102)
only rejects ID 0; it cannot/does not compare against the instance's current ID.

**Observed behavior.** An instance built for configuration 7 accepted a proposal for another
configuration 7 and returned `Ok(())`, creating the StopSign. No transport/failure condition
is needed beyond the public API call.

**Reproduction.** `audit_runner/src/bin/core_checks.rs`, check
`reconfiguration epoch validation`; see `repro_core_checks.log`.

### 4. Decided-log subscription repeats entries when subscribing before the compacted index

**Status:** executed, deterministic.

**Expected behavior.** `subscribe_decided(from)` promises log-order delivery of the backlog
and later decisions ([source](../source/omnipaxos_runtime/src/handle.rs:261)). With
compaction at 3 and decisions at indices 1 through 6, a subscriber from 0 should receive one
compacted placeholder and entries 4, 5, 6 once each.

**Affected code.** [`push_to_sub`](../source/omnipaxos_runtime/src/actor.rs:279) and
[`push_to_all_subs`](../source/omnipaxos_runtime/src/actor.rs:301) increment `next_idx` once
per returned vector element. The core storage represents all pre-compaction indexes with a
single `Snapshotted`/`Trimmed` placeholder, so the vector length does not map one-to-one to
the cursor's index space.

**Observed behavior.** After snapshotting at index 3, the subscription cursor advanced from
0 to 4 after first returning the snapshot plus entries 4, 5, and 6. The next tick read from
index 4 and delivered entries 5 and 6 again. The observed stream was:
`[Snapshotted(3), Decided(4), Decided(5), Decided(6), Decided(5), Decided(6)]`.

**Reproduction.** `audit_runner/src/bin/runtime_compaction_check.rs`; output in
`repro_runtime_compaction.log`. Test-only equivalent:
`omnipaxos_runtime/tests/audit_compacted_subscription.rs`.

### 5. A full event channel blocks the entire runtime actor, including consensus traffic

**Status:** executed, deterministic differential reproduction.

**Expected behavior.** An optional observer stream should not be required for the actor to
make progress. The runtime explicitly makes slow decided-log subscribers apply deferred
backpressure rather than block the actor
([source](../source/omnipaxos_runtime/src/handle.rs:261)), and its command/outgoing paths are
designed to stay responsive. `RuntimeConfig::event_capacity` is a supported public setting,
not documented as requiring a minimum number of concurrent transitions.

**Affected code.** [`ActorState::detect_and_emit_events`](../source/omnipaxos_runtime/src/actor.rs:169)
performs `event_tx.send(...).await` for leader, decision, and reconfiguration events. This
method is awaited from the tick branch of the single actor `select_biased!` loop. Once the
bounded event channel is full, the actor stops polling commands, incoming protocol messages,
ticks, and outgoing egress.

**Necessary condition.** The configured event channel fills while nobody is draining
`subscribe_events()`. With `event_capacity = 1`, a normal three-node election already emits
the prepare-phase and accepted-phase `LeaderElected` events.

**Observed behavior.** In the same three-node in-process setup, `event_capacity = 1024`
reached a stable accepted leader and remained command-responsive. With only
`event_capacity` changed to 1, the cluster did not reach an accepted leader within two
seconds. No explicit subscription was created; the default handle still holds the event
receiver. This is a local actor-liveness defect and can prevent consensus traffic from being
handled, although draining the receiver resumes work.

**Reproduction.** `audit_runner/src/bin/runtime_event_stall_check.rs` runs the
large-capacity control first and the capacity-1 case second; see
`repro_runtime_event_stall.log`.

### 6. Feature unification with `omnipaxos/unicache` breaks `omnipaxos_runtime`

**Status:** executed compile failure.

**Expected behavior.** `omnipaxos_runtime` exposes a `unicache` feature that forwards to
`omnipaxos/unicache` ([Cargo.toml](../source/omnipaxos_runtime/Cargo.toml:31)). A downstream
program should also be able to enable `omnipaxos/unicache` directly for its entry type while
using the runtime for transport. Cargo features are unified per package, so the runtime must
compile against the actual associated types exposed by its `omnipaxos` dependency.

**Affected code.** [`ActorEntry`](../source/omnipaxos_runtime/src/traits.rs:8) chooses whether
to require `UniCache: Send` and `EncodeResult: Send` using the runtime crate's own cfg
feature, not the feature state of its `omnipaxos` dependency. Under unification the dependency
has those associated types while the runtime's `not(feature = "unicache")` blanket bound
omits their `Send` requirements.

**Necessary condition.** One dependency edge enables `omnipaxos/unicache`; another uses
`omnipaxos_runtime` without explicitly enabling the runtime's forwarding `unicache` feature.

**Observed behavior.** `cargo check --offline` for the minimal
`feature_unification_check` crate fails twice with “future cannot be sent between threads
safely”, identifying missing `Send` bounds for `<T as Entry>::UniCache` and `EncodeResult`
at `omnipaxos_runtime/src/handle.rs:315`.

**Reproduction.** `feature_unification_check/Cargo.toml` and `src/main.rs`; command/output in
`repro_feature_unification.log`.

### 7. Configuration validation accepts node ID 0, followed by an arithmetic panic

**Status:** executed, deterministic.

**Expected behavior.** Every server in the configuration must have the same nonzero-PID
invariant as `ServerConfig::pid` (“Must not be 0”). `ClusterConfig::validate` claims to check
all fields, so a configuration containing 0 should be rejected before an instance is built.

**Affected code.** [`ClusterConfig::validate`](../source/omnipaxos/src/omni_paxos.rs:104)
checks only the node count and configuration ID. Leader bookkeeping then calls
[`pid_to_idx`](../source/omnipaxos/src/util.rs:110), which computes `pid - 1` without checking
for zero.

**Necessary condition.** `nodes` contains 0, as in `[1, 0, 2]`; the local node later enters
the leader Prepare phase and performs a normal resend tick.

**Observed behavior.** `OmniPaxosConfig::validate()` returned `Ok(())`. A node built from the
configuration successfully called `try_become_leader()`, and the next ordinary `tick()`
panicked with `attempt to subtract with overflow` at `util.rs:111`. This is a local crash
from a configuration the public validator accepted.

**Reproduction.** `audit_runner/src/bin/core_checks.rs`, checks `zero node ID validation` and
`zero node ID runtime safety`; see `repro_core_checks.log`. Test-only equivalents are in
`omnipaxos/tests/audit_config_validation.rs`.

### 8. Delta snapshot synchronization incorporates obsolete receiver-suffix entries (high severity)

**Status:** executed, deterministic focused reproduction; matching failures also observed in
the shipped `sync_full_test` under feature-enabled full-suite runs.

**Expected behavior.** A snapshot represents an application-visible prefix of decided log
entries. During delta snapshot synchronization, the receiver must merge the leader's delta
onto a snapshot of the *common decided prefix*. Accepted entries after that prefix may
conflict with the new leader's history and must be discarded, not folded into the snapshot.

**Affected code.** In [`InternalStorage::sync_log`](../source/omnipaxos/src/storage/internal_storage.rs:318),
the receiver first overwrites `state_cache.decided_idx` with the leader's decided index at
line 320. In `SnapshotType::Delta` handling at line 333, it then calls
`create_decided_snapshot()`. That helper snapshots entries through the newly assigned decided
index from the receiver's **old, not-yet-synchronized** log. Only afterward does
`AppendOnPrefix` replace the log suffix. Complete snapshots do not have this problem because
the leader's complete snapshot replaces the receiver snapshot directly.

**Necessary condition.** The receiver has snapshot-based compaction, a stale accepted suffix
that conflicts with the new leader after both peers' previous common decided prefix, and the
new leader sends a `SnapshotType::Delta` while catching it up. This naturally occurs when a
disconnected old leader accepted entries that were never decided before a new leader took
over.

**Observed behavior (focused test).** The receiver had decided/snapshotted `[1,2]`, decided
entry 3, and stale accepted entries `[6,7]`. The new leader supplied a delta for `[4,5]` with
the correct common prefix ending at 3. After synchronization the receiver's snapshot was
`[1,2,3,6,7,4,5]`, not `[1,2,3,4,5]`. Thus an application reading the snapshot can apply
values 6 and 7 that were never decided by the new leader.

**Corroborating clustered observation.** Two of three full feature-enabled runs failed the
shipped `sync_full_test` with the same signature: follower snapshot
`[1,2,3,6,7,4,5]`, no subsequent decided entries, and timeout. Standalone repetitions usually
avoided the corrupting path because whether the disconnected node locally accepted `[6,7]`
depends on the elected-leader/timing path. Logs: `isolated_feature_tests.log`,
`isolated_feature_tests_repeat.log`, and `isolated_feature_tests_third.log`.

A snapshot-aware randomized crash harness also failed at step 50: history had recorded value
1 at decided index 0, while pid 1's snapshot contained value 5 at the same index. This run
included 5-node partitions, process crashes and restarts, delayed/duplicated messages, and
leader churn (`repro_core_crash_fuzz_snapshot.log`).

**Reproduction.** `omnipaxos/tests/audit_sync_delta_snapshot.rs` is protocol-message-level and
deterministic. Command/output: `repro_sync_delta_snapshot.log`. It fails on the original
source without any diagnostic modification, both with default features and with
`logging,toml_config,unicache` (`repro_sync_delta_snapshot_features.log`).

### 9. `flush_batch_tick_timeout = 0` silently disables timeout flushing

**Status:** executed, deterministic.

**Expected behavior.** `flush_batch_tick_timeout` is documented as the number of ticks before
batched entries are flushed. Other zero-valued timeout fields are rejected by
`ServerConfig::validate`; the flush timeout should likewise be rejected if zero is not
meaningful, or defined/handled as an immediate flush.

**Affected code.** [`ServerConfig::validate`](../source/omnipaxos/src/omni_paxos.rs:187)
does not check this timeout. [`LogicalClock::tick_and_check_timeout`](../source/omnipaxos/src/util.rs:403)
fires only when its counter becomes exactly equal to the timeout, so a timeout of 0 never
fires.

**Necessary condition.** `batch_size > 1`, `flush_batch_tick_timeout = 0`, and fewer than
`batch_size` entries are appended.

**Observed behavior.** The configuration passed validation. After reaching the accepted
leader phase, one append left `get_batched_len() == 1` and `get_accepted_idx() == 0`.
Twenty ordinary `tick()` calls did not flush it. Without a later write filling the batch (or
a leader change), that entry remains neither stored as accepted nor decided.

**Reproduction.** `omnipaxos/tests/audit_zero_flush_timeout.rs`; output in
`repro_zero_flush_timeout.log`.

### 10. A failed persistent atomic write leaks state into later transactions

**Status:** executed, deterministic.

**Expected behavior.** `Storage::write_atomically` explicitly requires all-or-none semantics:
if it returns `Err`, every operation in the call must be rolled back, and a later transaction
must not commit any part of the failed one
([trait contract](../source/omnipaxos/src/storage/mod.rs:130)).

**Affected code.** [`PersistentStorage::write_atomically`](../source/omnipaxos_storage/src/persistent_storage.rs:278)
applies operations incrementally to the reusable `write_batch`, and the append helpers also
increment `next_log_key` before the final `db.write`. The `?` on any serialization/operation
error returns early without clearing the batch or restoring `next_log_key`. A later
`write_atomically` call writes the retained batch at line 295.

**Necessary condition.** A transaction contains at least one serializable operation followed
by an operation whose serialization or storage preparation fails. A database write error has
a similar next-key consistency issue.

**Observed behavior.** The reproduction submitted a valid `AppendEntry` followed by an entry
whose `Serialize` implementation intentionally returned an error. The transaction correctly
returned `Err`, but immediately afterward `get_log_len()` reported 1 while reads failed with
`ErrHelper` because the claimed log key did not exist in RocksDB. A subsequent unrelated
`SetPromise` transaction then returned `Ok` and committed the leaked append; `get_entries(0,
1)` returned one entry. Captured diagnostic:
`len_after_failure=1, entries_after_failure=Err(ErrHelper),
entries_after_unrelated_write=Ok(1)`. Closing and reopening RocksDB still returned one
entry, showing the leaked operation is durable rather than only stale cache state
(`entries_after_reopen=Ok(1)`).

The same corruption occurs through the directly used
[`PersistentStorage::append_entries`](../source/omnipaxos_storage/src/persistent_storage.rs:309)
path: one valid entry followed by a serialization failure left `get_log_len() == 1`; after a
later single-entry append, `get_entries(0, 2)` returned `Err(ErrHelper)` because key 0 had
never been committed. Core batching calls this method directly, so the issue is not limited to
callers of `write_atomically`. Captured diagnostic:
`len_after_failure=1, read_after_failure=Ok(0), read_after_retry=Err(ErrHelper)`.

**Reproduction.** `persistent_check/src/main.rs`; command/output in
`repro_persistent_atomicity.log`. The direct-append case is
`persistent_check/src/bin/append_error_state.rs`, with output in
`repro_persistent_append_error.log`. The custom serializer is a valid `Entry` permitted by
the public trait bounds and is used only to deterministically exercise the error path.

### 11. A StopSign requested before leader election is never forwarded afterward

**Status:** executed, deterministic.

**Expected behavior.** `reconfigure()` returns `Ok(())` when it accepts a StopSign proposal.
Ordinary entries proposed while no leader is known are buffered and forwarded when the node
joins a leader. A buffered StopSign should receive equivalent handling so the accepted
reconfiguration request eventually reaches the leader.

**Affected code.** [`forward_stopsign`](../source/omnipaxos/src/sequence_paxos/mod.rs:386)
stores the StopSign in `buffered_stopsign` when no leader is known.
[`handle_acceptsync`](../source/omnipaxos/src/sequence_paxos/follower.rs:53) later calls
`forward_buffered_proposals()` but never forwards `buffered_stopsign`. The StopSign is only
consumed if this same node becomes leader.

**Necessary condition.** A follower calls `reconfigure` before any leader is known, then
another node is elected and sends that follower its `AcceptSync`.

**Observed behavior.** The initial reconfigure returned success. After agreeing to leader 1
and entering the accepted phase, the node emitted `Accepted`/other sequence traffic but no
`ForwardStopSign` to leader 1. The request remains silently buffered unless the caller issues
another reconfigure after a leader becomes known, or this node itself later becomes leader.

**Reproduction.** `omnipaxos/tests/audit_buffered_stopsign.rs`; output in
`repro_buffered_stopsign.log`.

### 12. `UniCacheEntry` generated code depends on undocumented caller imports and caller feature names

**Status:** executed, two independent downstream compile failures.

**Expected behavior.** The documented UniCache example imports only
`omnipaxos::macros::UniCacheEntry` and derives it on a user struct
([documentation](../source/docs/omnipaxos/unicache.md:27)). Additionally, enabling
`omnipaxos/serde` should make the generated cache type satisfy `Entry::UniCache`'s serde
bounds; a downstream crate should not need to invent a matching feature with the same name.

**Affected code.** The macro expansion in
[`unicache_entry_derive`](../source/omnipaxos_macros/src/lib.rs:153) emits unqualified
`impl Entry`, `MaybeEncoded`, and `impl UniCache` at the caller's scope. It also emits
`#[cfg_attr(feature = "serde", ...)]` at line 166, but that condition is evaluated against the
*downstream crate's* features, not the `omnipaxos` dependency's features.

**Observed behavior.**

- With the documented imports, compilation fails because `Entry`, `MaybeEncoded`, and
  `UniCache` are not in scope from the derive expansion. The documentation also omits
  `PartialEq` beside `Eq`; after adding `PartialEq` to isolate the macro issue, the three
  macro-resolution errors remain (`repro_unicache_macro_imports.log`).
- With those implementation traits imported and `omnipaxos` enabled with `serde,unicache`,
  the generated `CustomerCache` lacks `Serialize`/`Deserialize`, because the downstream crate
  has no feature named `serde`. Compilation fails at the required
  [`Entry::UniCache` bounds](../source/omnipaxos/src/storage/mod.rs:45)
  (`repro_unicache_macro.log`, `repro_unicache_macro_serde.log`).

**Necessary condition.** A downstream crate uses `UniCacheEntry` without importing internal
implementation traits, or enables `omnipaxos/serde` without defining its own downstream
`serde` feature.

**Reproduction.** The first case is `unicache_macro_imports_check`; the serde case is
`unicache_macro_check`.

### 13. Cloned LFU UniCache decoders can silently decode a cache hit to the wrong value (high severity)

**Status:** executed, deterministic.

**Expected behavior.** Encoding a value as `MaybeEncoded::Encoded(code)` and decoding it with
the cache snapshot supplied by the leader must reconstruct that exact value. UniCache’s
documented guarantee is that encoded values are decoded back to their originals before being
stored.

**Affected code.** [`LFUniCache::clone`](../source/omnipaxos/src/unicache/lfu_cache.rs:18)
copies encoder key/value pairs into the follower’s decoder, but starts every copied entry at
the same fresh LFU frequency. It does not copy the leader encoder’s frequency counts or
recency state. Both sides then evict using their own different LFU state in
[`decode`](../source/omnipaxos/src/unicache/lfu_cache.rs:74), so they can discard different
encoding-to-value pairs and reuse the same code for different values.

**Necessary condition.** An LFU field cache has unequal access frequencies when its decoder is
cloned, followed by enough new cache misses to evict entries and then a cache hit.

**Observed behavior.** With cache size 2, the leader encoded `A`, `B`, then accessed `A` twice
before cloning. After two new misses and another `A` hit, the follower decoded the leader’s
encoding for `A` as `C`. The reproduction failed with
`left: "C", right: "A"` rather than reporting an unknown code. In a replicated log this can
store a different entry on the follower than the leader decided.

**Reproduction.** `unicache_check/src/bin/lfu_clone_check.rs` and the package-level
`omnipaxos/tests/audit_lfu_clone.rs`; outputs in `repro_lfu_clone.log` and
`repro_lfu_clone_test.log`. The same sequence with the LRU cache passes
(`lru_clone_control.rs`, `repro_lru_clone_control.log`), isolating the defect to LFU state
transfer rather than the test sequence.

### 14. Duplicate node IDs are accepted and inflate the configured cluster size

**Status:** executed for validation; consequence is source-traced.

**Expected behavior.** `NodeId` is the unique identifier for a server, and cluster liveness
calculations require distinct nodes. A node list with only `[1, 1]` is not a two-node cluster
and should be rejected by `OmniPaxosConfig::validate`.

**Affected code.** [`ClusterConfig::validate`](../source/omnipaxos/src/omni_paxos.rs:104)
uses `nodes.len()` as the cluster size without checking uniqueness. The duplicate is retained
in BLE peers and contributes to the quorum count, while
[`LeaderState`](../source/omnipaxos/src/util.rs:131) stores a Promise by PID, so duplicate
PIDs cannot contribute distinct promises.

**Observed behavior.** Validation returned success for `nodes = [1, 1]` with local PID 1. In
this configuration the reported cluster size is two and both majority thresholds are two, but
there is only one distinct process. Even if the node's self-directed heartbeat is counted by
BLE, there is no second distinct Sequence Paxos Promise, so accepted leadership cannot be
reached.

**Reproduction.** `omnipaxos/tests/audit_duplicate_nodes.rs`; output in
`repro_duplicate_nodes.log`.

### 15. `read(usize::MAX)` panics despite the out-of-bounds contract

**Status:** executed, deterministic in debug builds.

**Expected behavior.** [`OmniPaxos::read`](../source/omnipaxos/src/omni_paxos.rs:322) documents
that an out-of-bounds `idx` returns `None`.

**Affected code.** The method constructs `idx..idx + 1` without checking before adding one.
For `idx == usize::MAX`, that addition overflows before the storage range check. Similar
inclusive-end arithmetic exists in `InternalStorage::read`.

**Observed behavior.** `read(usize::MAX)` on a valid empty instance panicked with
`attempt to add with overflow` at `omni_paxos.rs:325`. Debug builds panic; release builds wrap
the endpoint rather than returning the documented `None` directly.

**Reproduction.** `omnipaxos/tests/audit_read_bounds.rs`; output in
`repro_read_bounds.log`.

### 16. `ConfigError::source()` creates an infinite self-referential chain

**Status:** executed, deterministic.

**Expected behavior.** `std::error::Error::source()` must eventually return `None` for a
non-wrapping leaf error. `ConfigError::InvalidConfig` contains only an owned message and has no
underlying error.

**Affected code.** [`ConfigError::source`](../source/omnipaxos/src/errors.rs:39) returns
`Some(self)` for `InvalidConfig`, which points back to the same error forever.

**Observed behavior.** Repeatedly following `source()` produced
`"Invalid config: invalid value"` at least 16 times without reaching `None`. Consumers that
walk error sources can loop indefinitely.

**Reproduction.** `omnipaxos/tests/audit_error_source.rs`; output in
`repro_error_source.log`.

### 17. MemoryStorage panics when reading a range below the compacted index

**Status:** executed, deterministic in debug builds.

**Expected behavior.** `Storage::get_entries` and `get_suffix` document an empty vector when
the requested entries do not exist as a complete interval. After trimming, indexes below the
compacted index no longer exist and should produce an empty result.

**Affected code.** [`MemoryStorage::get_entries`](../source/omnipaxos_storage/src/memory_storage.rs:90)
and [`get_suffix`](../source/omnipaxos_storage/src/memory_storage.rs:98) compute
`from - self.trimmed_idx` without first checking whether `from` is below the trim point.

**Observed behavior.** After trimming a three-entry log at index 2, both `get_entries(0, 2)`
and `get_suffix(0)` panicked with `attempt to subtract with overflow` at
`memory_storage.rs:93`. The same invalid interval behavior exists in the persistent backend,
which returns an error rather than the documented empty vector.

**Reproduction.** `audit_runner/src/bin/core_checks.rs`, check
`memory storage compacted-range reads`; output in `repro_core_checks.log`.

### 18. `AppendError::Timeout` is documented as retry-safe although the proposal may already be decided

**Status:** executed, deterministic.

**Expected behavior.** [`AppendError::Timeout`](../source/omnipaxos_runtime/src/event.rs:59)
states “Retry safe.” A caller following that contract must not duplicate a successfully
committed non-idempotent operation merely because the assignment/decision response was lost.

**Affected code.** On timeout, [`drain_notifiers`](../source/omnipaxos_runtime/src/actor.rs:201)
removes the origin's local `Pending` entry but sends no cancellation to the leader.
`TaggedProposal` may already have been accepted and decided; there is no durable idempotency
key exposed to the caller for a retry.

**Necessary condition.** The proposal reaches the leader, but the `Assigned` reply is lost or
delayed long enough for the caller's timeout to fire.

**Observed behavior.** With `Assigned` messages dropped, two sequential
`append_notify_with_timeout(TestEntry(7), 300ms)` calls—the second made according to the
documented retry-safe contract—each returned `Timeout`, while the leader's decided log
contained two identical `TestEntry(7)` values. Repeating a non-idempotent application
operation can therefore apply it twice.

**Reproduction.** `omnipaxos_runtime/tests/audit_timeout_retry.rs`; output in
`repro_timeout_retry.log`.

### 19. Dropped decided subscribers retain their capacity slot on an idle log

**Status:** executed, deterministic.

**Expected behavior.** `subscribe_decided` documents that dropping the returned receiver ends
the subscription ([source](../source/omnipaxos_runtime/src/handle.rs:268)). A dropped
subscriber should therefore stop consuming one of the `max_decided_subscribers` slots,
including when no new entry is decided.

**Affected code.** [`push_to_all_subs`](../source/omnipaxos_runtime/src/actor.rs:305) performs
closed-receiver cleanup with `retain_mut`, but returns early at line 312 when the trailing
subscriber is already caught up. Thus an idle log never visits the cleanup path. The
subscription command at [`actor.rs:628`](../source/omnipaxos_runtime/src/actor.rs:628) then
counts the stale closed subscriber and rejects a replacement.

**Observed behavior.** With `max_decided_subscribers = 1`, empty-log decided index 0, and no
traffic, the sequence “subscribe, drop receiver, wait 50 ms, subscribe again” closed the
second receiver immediately. The first dropped subscription continued consuming the only
capacity slot because no decision had advanced to trigger reaping.

**Reproduction.** `omnipaxos_runtime/tests/audit_subscriber_reuse.rs`; output in
`repro_subscriber_reuse.log`.

### 20. Empty logger path panics during configuration build

**Status:** executed, deterministic with the `logging` feature.

**Expected behavior.** `OmniPaxosConfig::build` is fallible and validates configuration
fields. An unusable logger destination should be rejected or reported as an error rather than
panic through an internal unwrap.

**Affected code.** [`create_logger`](../source/omnipaxos/src/utils/logger.rs:5) calls
`path.parent().unwrap()` and later unwraps directory/file creation. An empty
`logger_file_path` makes `parent()` return `None`.

**Observed behavior.** `ServerConfig::logger_file_path = Some(String::new())` passed
`OmniPaxosConfig::validate()`, then `build()` panicked at `logger.rs:7` with
`called Option::unwrap() on a None value`.

**Reproduction.** `omnipaxos/tests/audit_logger_path.rs`; output in `repro_logger_path.log`.

### 21. A second reconfiguration returns success while an earlier request is buffered

**Status:** executed, deterministic.

**Expected behavior.** `reconfigure` documents that it returns
`ProposeErr::PendingReconfigConfig` if a reconfiguration is already pending. A request
buffered because no leader is known is pending and cannot simply be discarded.

**Affected code.** [`SequencePaxos::reconfigure`](../source/omnipaxos/src/sequence_paxos/mod.rs:310)
checks `accepted_reconfiguration()`, which only tests the stored/accepted StopSign. It does not
include `buffered_stopsign`. [`forward_stopsign`](../source/omnipaxos/src/sequence_paxos/mod.rs:386)
keeps an existing buffer and silently ignores later requests when no leader is known.

**Observed behavior.** On a node with no leader, a first valid reconfiguration returned
`Ok(())` and was buffered. A second valid reconfiguration with a different next configuration
also returned `Ok(())`, but its StopSign was discarded; the first remains the buffered
request.

**Reproduction.** `omnipaxos/tests/audit_pending_reconfigure.rs`; output in
`repro_pending_reconfigure.log`.

### 22. Trim is gated on acceptance rather than the documented all-node decision

**Status:** executed, deterministic.

**Expected behavior.** `trim` and `CompactionErr::NotAllDecided` document that the requested
index may be removed only after all nodes have **decided** it. If any node has merely accepted
the entry, the call should return `NotAllDecided`.

**Affected code.** [`SequencePaxos::trim`](../source/omnipaxos/src/sequence_paxos/mod.rs:141)
uses [`LeaderState::get_min_all_accepted_idx`](../source/omnipaxos/src/util.rs:186), whose
name and implementation operate on acknowledgement indexes from acceptance, not each node's
decided index.

**Necessary condition.** All followers accept an entry and report `Accepted`, but one follower
does not receive the leader's subsequent `Decide`.

**Observed behavior.** The leader had decided index 1, all three nodes had accepted index 1,
and pid 3 still had decided index 0. `trim(Some(1))` nevertheless returned `Ok(())` and
locally removed the entry. This violates the public all-decided precondition and the safety
rationale in the compaction documentation.

**Reproduction.** `omnipaxos/tests/audit_trim_decidedness.rs`; output in
`repro_trim_decidedness.log`.

### 23. Bincode deserialization of LRU UniCache state panics

**Status:** executed with bincode; JSON transport passes as a control.

**Expected behavior.** A cache sent to a follower through the supported serde path should
preserve its configured capacity and remain usable for subsequent encoded entries, just like
the direct `Clone` path.

**Affected code.** [`LruWrapperVisitor::visit_seq`](../source/omnipaxos/src/unicache/lru_cache.rs:205)
constructs the inner `LruCache` with capacity
`seq.size_hint().unwrap_or(u8::MAX as usize)`. Bincode supplies a zero size hint, causing
`NonZeroUsize::new(0).unwrap()` at line 210 to panic before any entries are deserialized.

**Necessary condition.** An `LRUniCache` is transmitted through serde using bincode. This can
be the cache inside an `AcceptSync` message when the application serializes messages with
bincode.

**Observed behavior.** With capacity 4, entries `A, B`, and the actual decoder-only clone that
`get_unicache()` places in `AcceptSync`, bincode serialization succeeded but deserialization
panicked inside the LRU visitor at line 210. The equivalent JSON round-trip remained usable
for later cache hits, and direct `Clone` is also unaffected.

**Reproduction.** `unicache_check/src/bin/lru_serde_sync_check.rs`, output in
`repro_lru_serde_sync.log`. Passing controls: `repro_lru_serde_test.log` (LRU JSON package
test) and `repro_lfu_serde_control.log` (LFU JSON and bincode transport).

### 24. Workspace all-features build fails in the supplied async example

**Status:** executed compile failure.

**Expected behavior.** Running `cargo check --workspace --all-targets --all-features` should
compile every workspace member, including the shipped examples, under the enabled feature
set.

**Affected code.** [`kv_store_async/src/kv.rs`](../source/examples/kv_store_async/src/kv.rs:5)
derives the ordinary `Entry` macro. Workspace feature unification enables
`omnipaxos/unicache`, which adds `Encoded`, `Encodable`, `NotEncodable`, `EncodeResult`, and
`UniCache` associated types to `Entry`; the example does not define them or switch to
`UniCacheEntry`.

**Observed behavior.** The all-features workspace check failed with `E0046: not all trait
items implemented` at `kv.rs:5`, and therefore never completed verification of the other
workspace targets.

**Reproduction.** `cargo check --workspace --all-targets --all-features`; output in
`isolated_all_features_check.log`.

### 25. A failed `append_on_prefix` permanently deletes the existing suffix

**Status:** executed, deterministic.

**Expected behavior.** If a storage mutation returns an error, the existing durable log should
remain readable and must not be partially discarded. This is the minimum rollback behavior
needed by recovery and synchronization paths.

**Affected code.** [`PersistentStorage::append_on_prefix`](../source/omnipaxos_storage/src/persistent_storage.rs:323)
first executes `delete_range_cf` against the live database for the old suffix, then sets
`next_log_key`, and only afterward calls the fallible `append_entries`. A serialization or
write failure therefore occurs after the old data has already been deleted.

**Necessary condition.** `append_on_prefix` replaces a suffix whose end is below
`next_log_key`, and serialization of one replacement entry fails.

**Observed behavior.** With entries `[1,2,3,4]`, a call replacing the suffix at index 1 with
`[valid, serialization-failing]` returned `Err`, but after closing and reopening RocksDB the
log length was 3 and entries were `[1,2,3]`. Original entry 4 had been permanently deleted;
the failed replacement also lost the valid first element.

**Reproduction.** `persistent_check/src/bin/append_on_prefix_error.rs`; output in
`repro_persistent_append_on_prefix.log`.

### 26. `AcceptSync` can decrease a follower’s already-decided index

**Status:** executed, deterministic.

**Expected behavior.** A decided index is monotonic: `LogEntry::Decided` values are promised
not to be reverted, so synchronization must never make an application-visible decided prefix
shrink. If the receiver has already decided further than the new leader’s current decided
index, synchronization must retain the higher local decided index.

**Affected code.** [`InternalStorage::sync_log`](../source/omnipaxos/src/storage/internal_storage.rs:318)
assigns both `state_cache.decided_idx` and `StorageOp::SetDecidedIndex` directly to the
leader-provided value without taking the maximum with the existing decided index.

**Necessary condition.** A follower previously decided through index 10, while a new leader
knows the same accepted prefix through 10 but has itself decided only through 5. This can
occur when the leader is part of the old accept quorum but missed a prior decision message;
the late follower then receives `AcceptSync { decided_idx: 5, sync_idx: 10 }`.

**Observed behavior.** The receiver started with decided index 10. After the valid
`AcceptSync`, its public `get_decided_idx()` returned 5. Entries 6–10 were still present and
accepted, but they temporarily disappeared from the decided API, violating monotonic decided
visibility.

**Reproduction.** `omnipaxos/tests/audit_sync_decided_regression.rs`; output in
`repro_sync_decided_regression.log`.

## Unresolved / further work

- The package-level exhaustive feature matrix passes; only the cross-package workspace
  all-features composition fails (finding 24).

## Baseline test status

`cargo check --workspace --all-targets` passes under default features
(`isolated_workspace_check.log`).

Kompact's network thread was blocked by the ordinary sandbox, so the complete test suite was
rerun with `isolated_exec`:

```text
cargo test -p omnipaxos --tests --no-fail-fast
```

Every shipped test passed; the only failures in that run were the then-present audit targets
`audit_config_validation` and `audit_sparse_ids_trim`, as expected. Full log:
`isolated_network_tests.log`. The snapshot, zero-flush, and buffered-StopSign reproductions
were added and run separately through `repro_all_core_audit_tests.log`.

The four normally ignored crash-recovery tests were also run explicitly:

```text
cargo test -p omnipaxos --test recovery_test -- --ignored --test-threads=1
```

All four passed (`isolated_recovery_ignored.log`).

The runtime suite was run with:

```text
cargo test -p omnipaxos_runtime --features tokio_runtime --tests --no-fail-fast
```

All 24 shipped runtime tests and 4 runtime unit tests passed; the only failure was
`audit_compacted_subscription` (`isolated_runtime_tests.log`).
The later `audit_timeout_retry` and `audit_subscriber_reuse` reproductions were run separately
and fail as described in findings 18 and 19 (`repro_timeout_retry.log`,
`repro_subscriber_reuse.log`).

With `--all-features`, all 24 shipped runtime tests and 4 runtime unit tests also passed
(`isolated_runtime_all_features.log`).

The project's exhaustive `omnipaxos/test_all_features.sh -c` feature-combination check also
completed successfully (`isolated_feature_matrix_check.log`).

With `logging,toml_config,unicache` enabled, all shipped targets passed in one complete run
(`isolated_feature_tests_third.log`) but two other full runs hit the intermittent
`sync_full_test` failure described in finding 8
(`isolated_feature_tests.log`, `isolated_feature_tests_repeat.log`). Running `sync_test`
alone passed repeatedly, consistent with the timing-dependent preconditions of the focused
delta-snapshot reproduction.

## Checks that did not reproduce a defect

- `audit_runner/src/bin/core_fuzz_check.rs` ran 4,000 randomized steps with 2,654 unique
  proposals, asymmetric link loss, delayed/lost messages, duplicates, reordering, and leader
  churn. It found no decided-index conflict; after healing, every node reported decided index
  2,573. Log: `repro_core_fuzz.log`.
- JSON serialization/deserialization remains usable after later cache hits
  (`repro_lru_serde_test.log`, `repro_lfu_serde_control.log`). The failure in finding 23 is
  specific to bincode.
- 160 randomized LRU clone/decode runs (cache sizes 1–8, 2,000 operations each) remained
  synchronized, supporting the conclusion that finding 13 is LFU-specific:
  `lru_clone_fuzz.rs`, `repro_lru_clone_fuzz.log`.
- An earlier crash harness without snapshot state transfer ran 5,000 steps with 18 process
  crashes and no decided-index conflict. After snapshot support was added, the harness
  immediately exposed the snapshot defect above, so it is retained as corroboration rather
  than a clean negative result.

## Reproduction commands

Run from `work/` unless a `cd` is shown. The core audit binaries intentionally exit nonzero
when a check fails; each command below produced the corresponding retained log.

```bash
cargo test -p omnipaxos \
  --test audit_config_validation \
  --test audit_sparse_ids_trim \
  --test audit_sync_delta_snapshot \
  --test audit_zero_flush_timeout \
  --test audit_buffered_stopsign \
  --test audit_duplicate_nodes \
  --test audit_read_bounds \
  --test audit_error_source \
  --test audit_pending_reconfigure \
  --test audit_sync_decided_regression \
  --test audit_trim_decidedness \
  --no-fail-fast -- --nocapture

cargo test -p omnipaxos --features "logging,toml_config,unicache" \
  --test audit_sync_delta_snapshot -- --nocapture

cargo test -p omnipaxos --features unicache \
  --test audit_lfu_clone -- --nocapture

cargo test -p omnipaxos --features "serde,unicache" \
  --test audit_lru_serde -- --nocapture

cargo test -p omnipaxos_runtime --features tokio_runtime \
  --test audit_timeout_retry -- --nocapture

cargo test -p omnipaxos_runtime --features tokio_runtime \
  --test audit_subscriber_reuse -- --nocapture

cargo test -p omnipaxos --features logging \
  --test audit_logger_path -- --nocapture

cd audit_runner
CARGO_TARGET_DIR=../repro-target cargo run --offline --bin core_checks
CARGO_TARGET_DIR=../repro-target cargo run --offline --bin runtime_compaction_check
CARGO_TARGET_DIR=../repro-target cargo run --offline --bin runtime_event_stall_check
CARGO_TARGET_DIR=../repro-target cargo run --offline --bin core_fuzz_check
CARGO_TARGET_DIR=../repro-target cargo run --offline --bin core_crash_fuzz

cd ../feature_unification_check
CARGO_TARGET_DIR=../repro-feature-target cargo check --offline

cd ../unicache_check
CARGO_TARGET_DIR=../repro-unicache-target cargo run --offline
CARGO_TARGET_DIR=../repro-unicache-target cargo run --offline --bin lfu_clone_check
CARGO_TARGET_DIR=../repro-unicache-target cargo run --offline --bin lru_clone_control
CARGO_TARGET_DIR=../repro-unicache-target cargo run --offline --bin lru_clone_fuzz
CARGO_TARGET_DIR=../repro-unicache-target cargo run --offline --bin lru_serde_sync_check

cd ../persistent_check
CARGO_TARGET_DIR=../.runtime/cargo-target cargo run --offline
CARGO_TARGET_DIR=../.runtime/cargo-target cargo run --offline --bin append_error_state
CARGO_TARGET_DIR=../.runtime/cargo-target cargo run --offline --bin append_on_prefix_error

cd ../unicache_macro_check
CARGO_TARGET_DIR=../repro-unicache-target cargo check --offline

cd ../unicache_macro_imports_check
CARGO_TARGET_DIR=../repro-unicache-target cargo check --offline

cd ..
cargo check --workspace --all-targets --all-features
```

The ordinary-shell baseline attempt cannot open Kompact's TCP socket. The successful and
feature-enabled baseline commands were run through `isolated_exec`; their exact commands and
logs are listed under **Baseline test status** above.
