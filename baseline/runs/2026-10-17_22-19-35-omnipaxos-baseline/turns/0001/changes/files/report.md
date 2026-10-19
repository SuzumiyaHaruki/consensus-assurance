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

## Unresolved / further work

- Run the repository's complete existing test suite once the RocksDB dev-dependency finishes
  building, to identify any independent baseline failures.
- Continue failure-oriented checks around recovery/compaction and batching.

## Baseline test status

`cargo test -p omnipaxos --lib --tests --no-fail-fast` was started for a clean baseline.
Initial compilation was still in progress at the time this report was created. Output is
being retained in the terminal transcript and final test logs will be written under
`work/repro/`.
