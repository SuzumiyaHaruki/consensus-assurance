# HashiCorp Raft correctness audit

Source identity: `0f543c056e7e577a54b819a62116335c9661a13a`

The implementation's new `RestoreCommittedLogs` startup and persistence paths
have six independently reproducible correctness defects, plus one independent
defect in the exposed cluster test helper. All occur with supported
configuration values; the configuration-loss defect can prevent a cluster from
electing a leader after a coordinated restart.

Comparison with the cached `hashicorp/raft v1.7.3` source showed that the
relevant semantic additions are the `RestoreCommittedLogs` recovery path and
commit-index staging. The remaining differences reviewed were dependency
compatibility, API-header promotion, and lint-driven changes.

## Finding 1: committed-log recovery discards the persisted cluster configuration

Severity: high

Affected code:

- `api.go:607-625`: `NewRaft` invokes `restoreFromCommittedLogs`, then starts its
  configuration scan at `max(snapshotIndex, lastApplied)+1`.
- `api.go:720-755`: `restoreFromCommittedLogs` sets `lastApplied` to the persisted
  commit index via `processLogs`.
- `raft.go:1296-1363`: `processLogs` applies entries to the FSM, but never calls
  `processConfigurationLogEntry` or updates `r.configurations`.

Expected behavior: enabling `RestoreCommittedLogs` should replay the committed
log suffix to the FSM without losing Raft's own persistent state. In particular,
after restart, the latest committed configuration must be reconstructed from
configuration entries in that suffix. This is the behavior of the same startup
path with `RestoreCommittedLogs` disabled, and is required before the node can
evaluate elections or membership safely.

Actual behavior: on startup, `processLogs` advances `lastApplied` through the
persisted commit index. The subsequent configuration scan deliberately starts
after `lastApplied`, so it skips every configuration entry in the replayed
range. No other recovery step populates `r.configurations`. A restarted node can
therefore have an empty or stale `latest` configuration even though its log
contains the committed current configuration.

This occurs without a snapshot. With one bootstrapped voter and one committed
client command, the persisted tracker reaches the committed no-op and command.
After restart, the log still contains the bootstrap configuration at index 1,
but `restarted.GetConfiguration()` returns an empty configuration and the node
logs `initial configuration: index=0 servers=[]`.

Reproduction: `TestAuditRestoreCommittedLogsRestoresConfiguration` in
`audit_repro_test.go`.

Command:

```text
go test -run '^TestAuditRestoreCommittedLogsRestoresConfiguration$' -count=1 -v .
```

Observed result:

```text
server-...: initial configuration: index=1 servers="[{Suffrage:Voter ID:server-... Address:...}]"
server-...: initial configuration: index=0 servers=[]
audit_repro_test.go:170: configuration after recovery = [], want local server "server-..."
--- FAIL: TestAuditRestoreCommittedLogsRestoresConfiguration (0.33s)
```

The first `initial configuration` line is the original startup. The second is
the recovery-enabled restart immediately after `NewRaft` returns.
Running this test ten times produced ten failures, so the observation is not a
startup race.

The same defect occurs with a snapshot containing an older configuration. A
separate reproducer installs a valid snapshot at index 1 with the old
configuration, stores a committed configuration change at index 2, and restarts.
Recovery keeps the old configuration from the snapshot instead of installing
the newer committed configuration. This is
`TestAuditRestoreCommittedLogsAppliesConfigurationAfterSnapshot` in
`audit_repro_test.go`.

Command:

```text
go test -run '^TestAuditRestoreCommittedLogsAppliesConfigurationAfterSnapshot$' -count=1 -v .
```

Observed result:

```text
initial configuration: index=1 servers="[{...}]"
audit_repro_test.go:343: configuration after recovery = {Servers:[one server]}, want {Servers:[two servers]}
--- FAIL: TestAuditRestoreCommittedLogsAppliesConfigurationAfterSnapshot (0.00s)
```

The defect also resurrects a removed voter in a real three-node cluster:
`TestAuditRestartDoesNotResurrectRemovedVoter` snapshots the original
three-voter configuration, commits removal of one voter, commits another write,
and restarts the two survivors. Both survivors recover the removed voter from
the snapshot and skip the committed removal log entry.

```text
go test -run '^TestAuditRestartDoesNotResurrectRemovedVoter$' -count=1 -v .
```

Observed result:

```text
initial configuration: index=1 servers="[three voters]"
audit_repro_test.go:875: node 0 resurrected removed voter "server-...": [three voters]
--- FAIL: TestAuditRestartDoesNotResurrectRemovedVoter (0.35s)
```

The configuration loss also prevents a whole three-voter cluster from recovering
when all members restart together. Every node returns an empty configuration
and logs `no known peers, aborting election`. This is
`TestAuditRestartAllNodesRecoversMembership` in `audit_repro_test.go`:

```text
go test -run '^TestAuditRestartAllNodesRecoversMembership$' -count=1 -v .
```

Observed result after waiting through several randomized election intervals:

```text
... no known peers, aborting election
audit_repro_test.go:426: restarted three-voter cluster has no leader; recovered server counts: [0 0 0]
--- FAIL: TestAuditRestartAllNodesRecoversMembership (0.64s)
```

Alternative considered: perhaps the FSM-side configuration application is
intended to replace the Raft configuration scan. It cannot: `processLogs` only
queues `commitTuple`s for `runFSM`; `runFSM` may call an application
`ConfigurationStore`, but never mutates `Raft.configurations`, which is used by
elections, quorum calculation, and `GetConfiguration`.

The package-level `GetConfiguration` helper (`api.go:450-466`) inherits this
defect because it obtains its value by constructing the same `NewRaft` path
with `skipStartup=true`.

`TestAuditGetConfigurationRecoversCommittedConfiguration` confirms the public
consequence directly. It bootstraps a one-voter configuration, commits index 1
atomically with a following persisted no-op, then calls the package-level
`GetConfiguration`; the helper returns an empty server list.

```text
go test -run '^TestAuditGetConfigurationRecoversCommittedConfiguration$' -count=1 -v .
```

```text
audit_repro_test.go:1027: GetConfiguration recovered {Servers:[]}, want local server "server-..."
--- FAIL: TestAuditGetConfigurationRecoversCommittedConfiguration (0.00s)
```

The package-level reproduction failed in 10 of 10 consecutive runs.

## Finding 2: startup deadlocks while replaying enough committed batches

Severity: medium; deterministic availability failure during startup

Affected code:

- `api.go:607-628`: committed-log recovery completes before `runFSM` is started.
- `api.go:560`: `fsmMutateCh` has a fixed buffer of 128 items.
- `raft.go:1302-1317`: `processLogs` sends one batch per `MaxAppendEntries`
  entries and blocks when the channel is full.

Expected behavior: `NewRaft` should return after replaying any number of
persisted committed entries that fit the supported configuration. Writes to the
FSM mutation channel must have a live consumer or must not outnumber its buffer
before startup completes.

Actual behavior: `restoreFromCommittedLogs` calls `processLogs`, which must put
every batch on `fsmMutateCh`; however, `runFSM` is only started after recovery
returns. Consequently, more than 128 batches block `NewRaft` forever while it
waits for a consumer it has not yet launched.

With the default `MaxAppendEntries = 64`, 8,193 committed entries that produce
FSM batches require 129 batches and trigger the deadlock. The reproducer uses
those stock settings, commits 8,193 such entries including the bootstrap
configuration, and leaves one later entry in storage. A smaller legal batch
size reaches the same failure with fewer entries.

Reproduction: `TestAuditRestoreCommittedLogsDoesNotDeadlockBeforeRunFSM` in
`audit_repro_test.go`.

Commands:

```text
go test -run '^TestAuditRestoreCommittedLogsDoesNotDeadlockBeforeRunFSM$' -count=1 -v .
```

Observed result:

```text
audit_repro_test.go:232: NewRaft deadlocked while restoring 8193 committed entries
--- FAIL: TestAuditRestoreCommittedLogsDoesNotDeadlockBeforeRunFSM (2.00s)
```

Alternative considered: `BatchApplyCh` could relieve the problem if it allowed
`runFSM` to consume during recovery, but it does not. It buffers `applyCh`, not
`fsmMutateCh`, and the FSM goroutine is not started until after
`restoreFromCommittedLogs` returns.

The package-level `GetConfiguration` helper always uses `skipStartup=true`, so
it has no FSM consumer at all and encounters the same replay deadlock for a
sufficiently large committed suffix.

This is reproduced directly by
`TestAuditGetConfigurationDoesNotDeadlockOnCommittedReplay`:

```text
go test -run '^TestAuditGetConfigurationDoesNotDeadlockOnCommittedReplay$' -count=1 -v .
```

Observed result:

```text
audit_repro_test.go:991: GetConfiguration deadlocked while restoring 8193 committed entries
--- FAIL: TestAuditGetConfigurationDoesNotDeadlockOnCommittedReplay (2.01s)
```

Even when replay is small enough not to fill the channel, `NewRaft` does not
wait for the FSM to consume its work. `processLogs` queues the batch and returns;
`runFSM` is started later, and `NewRaft` does not synchronize with FSM
completion. This contradicts the `Config.RestoreCommittedLogs` documentation
that committed logs are replayed "before completing `NewRaft`". With an FSM
whose `Apply` blocks, `NewRaft` returned while zero of the two committed
commands had been applied.

Reproduction: `TestAuditNewRaftWaitsForCommittedReplay` in
`audit_repro_test.go`.

Command:

```text
go test -run '^TestAuditNewRaftWaitsForCommittedReplay$' -count=1 -v .
```

Observed result:

```text
audit_repro_test.go:579: NewRaft returned after applying 0 committed commands, want 2
--- FAIL: TestAuditNewRaftWaitsForCommittedReplay (0.00s)
```

Alternative considered: normal Raft deliberately applies commands
asynchronously, and `AppliedIndex` is documented as queue progress rather than
FSM completion. That does not override this option's explicit startup contract.
Applications enabling it to make relaxed follower reads less stale need a
point at which the promised replay is complete.

## Finding 3: recovery moves the public commit index behind restored FSM state

Severity: low to medium; persistent state inconsistency visible through the
public API

Affected code:

- `api.go:598-607`: `restoreSnapshot` restores the FSM and sets `lastApplied` to
  the snapshot index.
- `api.go:746-753`: `restoreFromCommittedLogs` unconditionally replaces the
  commit index with the tracker's value.

Expected behavior: `commitIndex` is the highest log entry known to be committed,
while `lastApplied` is the highest entry applied to the FSM. The restored
snapshot necessarily represents committed state, so
`CommitIndex() >= AppliedIndex()` must hold.

Actual behavior: taking a snapshot does not append a log entry, so the last
durably staged commit can be one or more indices behind the snapshot. On a
restart, snapshot restore sets `lastApplied` to the snapshot index 3, then
committed-log recovery sets `commitIndex` to the stale tracker value 2.
`Raft.CommitIndex()` consequently reports 2 while `Raft.AppliedIndex()` reports
3. The code does not raise the recovered value to `lastApplied`.

The same bound is also wrong when all logs have been compacted: the clamp at
`api.go:743-750` uses `logs.LastIndex()` rather than the effective last index
including the snapshot, so it can reduce an otherwise valid tracker value to 0.

Related source review: `restoreUserSnapshot` (`raft.go:1105-1195`) and
`RecoverCluster` (`api.go:281-429`) can both install snapshot state without
advancing the commit tracker. They use the same missing
`max(trackerIndex, snapshotIndex/appliedIndex)` recovery rule, so they share
Finding 3 rather than demonstrating a distinct defect.

This is a local state-invariant/API defect. A later leader heartbeat can repair
the in-memory value, but until then commit status is false and monitoring or
logic based on the public index sees impossible state.

Reproduction:
`TestAuditRestoreCommittedLogsDoesNotRegressCommitBehindSnapshot` in
`audit_repro_test.go`.

Command:

```text
go test -run '^TestAuditRestoreCommittedLogsDoesNotRegressCommitBehindSnapshot$' -count=1 -v .
```

Observed result:

```text
restored from snapshot: id=2-3-... last-index=3 ...
skipping application of old log: index=2
audit_repro_test.go:276: commit index regressed behind restored state: commit=2 applied=3
--- FAIL: TestAuditRestoreCommittedLogsDoesNotRegressCommitBehindSnapshot (0.38s)
```

The snapshot regression reproduced in ten consecutive runs.

Alternative considered: a low recovered commit index might merely reduce the
optimization benefit if it were only internal. That does not explain the public
contradiction with `AppliedIndex`, and `CommitIndex` is documented as the highest
known committed entry. Recovery should use at least `max(trackerIndex,
lastApplied)`.

## Finding 4: accepting AppendEntries can overwrite a higher persisted commit index

Severity: medium for the committed-log recovery feature

Affected code:

- `raft.go:1555-1559`: when new entries are stored, Raft stages
  `min(a.LeaderCommitIndex, lastNewIndex)` without considering the follower's
  already persisted commit index.

Expected behavior: commit indexes are monotonic. A follower that durably knows
index 3 is committed must not overwrite that knowledge with 0 merely because a
newly elected/restarted leader advertises its own earlier commit index. A
persisted tracker should advance to at least `max(currentPersisted,
leaderCommit bounded by new entries)`.

Actual behavior: `InmemCommitTrackingStore` had commit index 3. A valid
`AppendEntries` with an entry at index 6 and `LeaderCommitIndex=0` caused the
tracker to stage 0 atomically with storing entry 6. The in-memory Raft commit
index remained 3 because the normal commit rule rejects 0, but the recovery
tracker regressed. If the follower crashes before another append, startup
restores only the now-lower persisted value.

This condition is normal while mixing enabled followers with a restarted leader
that does not enable `RestoreCommittedLogs`, or before a new leader commits its
first no-op. `RestoreCommittedLogs` is an independently configured node option,
so the feature must not corrupt stronger commit information already present on
a follower.

Reproduction:
`TestAuditAppendEntriesDoesNotRegressPersistedCommitIndex` in
`audit_repro_test.go`.

Command:

```text
go test -run '^TestAuditAppendEntriesDoesNotRegressPersistedCommitIndex$' -count=1 -v .
```

Observed result:

```text
audit_repro_test.go:518: persisted commit regressed from 3 to 0
--- FAIL: TestAuditAppendEntriesDoesNotRegressPersistedCommitIndex (0.00s)
```

The manual-store reproducers use `auditAtomicTrackingStore`, which keeps a
staged index invisible until the following successful `StoreLog`/`StoreLogs`
call. They therefore do not depend on the permissive behavior of
`InmemCommitTrackingStore`.

The end-to-end recovery consequence is reproduced separately by
`TestAuditRegressedCommitIndexSkipsCommittedReplay`. After the regressed append,
the node is shut down and restarted with a fresh FSM. Its committed commands at
indices 2 and 3 are not replayed:

```text
go test -run '^TestAuditRegressedCommitIndexSkipsCommittedReplay$' -count=1 -v .
```

```text
audit_repro_test.go:680: recovered FSM applied 0 committed commands, want 2
--- FAIL: TestAuditRegressedCommitIndexSkipsCommittedReplay (1.00s)
```

Alternative considered: the in-memory Raft commit index remaining at 3 might
make the durable regression harmless. It is not harmless for this feature:
recovery reads the store rather than reconstructing the follower's previous
in-memory value, so a crash before the next tracked write loses the recovery
progress. With relaxed follower reads, this can also leave the FSM observably
behind committed data after restart.

## Finding 5: the shipped in-memory tracker violates its staged-index bound

Severity: low; test/backend API contract violation

Affected code:

- `log.go:207-220`: `GetCommitIndex` MUST never return an index higher than the
  last stored log entry, even when a higher index has been staged.
- `inmem_store.go:152-159`: `InmemCommitTrackingStore` stores staged values
  immediately and returns that atomic value without comparing it to `LastIndex`.

Expected behavior: after storing log index 1 and staging commit index 2,
`GetCommitIndex` must return at most 1 until a log entry at index 2 is stored.

Actual behavior: `GetCommitIndex` immediately returns 2. This also means the
backend does not model the atomic staging behavior promised by the interface.
Raft clamps the value during startup, so the core recovery path masks this
specific failure, but direct users and tests of the exported backend receive a
value the interface explicitly forbids.

Reproduction:
`TestAuditInmemCommitTrackingStoreBoundsStagedIndex` in `audit_repro_test.go`.

Command:

```text
go test -run '^TestAuditInmemCommitTrackingStoreBoundsStagedIndex$' -count=1 -v .
```

Observed result:

```text
audit_repro_test.go:704: GetCommitIndex returned staged index 2 above last log index 1
--- FAIL: TestAuditInmemCommitTrackingStoreBoundsStagedIndex (0.00s)
```

Alternative considered: the type is documented as test-only, not for
production. That limits severity but does not make it conform to the interface
it asserts, and its permissive behavior can hide violations in tests written
against it. The primary persistence reproducers therefore use the stricter
`auditAtomicTrackingStore`.

## Finding 6: cluster test helper never refreshes its expected configuration

Severity: low; test-harness correctness

Affected code:

- `testing.go:692-716`: `cluster.EnsureSamePeers` reads
  `peerSet := c.getConfiguration(c.rafts[0])` once, before its retry loop.

Expected behavior: while waiting for configurations to converge, the helper
must use the current baseline. A node can legitimately be one configuration
behind when polling starts, then catch up.

Actual behavior: if raft 0 initially reports the old two-peer configuration and
the cluster subsequently converges on the new three-peer configuration, the
function keeps comparing every node against the permanently captured old value.
It reports a peer mismatch even though all nodes now agree.

This was exposed by the existing
`TestRaft_ProtocolVersion_Upgrade_2_3` test: 6 of 20 isolated repetitions failed
with raft 0 showing two peers and the other nodes showing the correct three.
A direct two-node fixture, where both nodes are updated to the same new
configuration during the retry window, also fails deterministically.

The same harness bug independently affected
`TestRaft_ProtocolVersion_Upgrade_1_2`: 3 of 20 isolated repetitions failed with
the same stale-baseline peer mismatch. That run is execution
`39882c37425e4f2cbcee788b6971c9c2`. This confirms it is a general membership
test-helper problem rather than one test's timing artifact.

The original flaky test is reproducible with:

```text
go test -run '^TestRaft_ProtocolVersion_Upgrade_2_3$' -count=20 .
```

That run is execution `6e5786a2795f48f38d0b2c39d7dd4860`. A direct catch-up
diagnostic, `TestAuditProtocol2To3VoterCatchesUp`, confirmed that all three
nodes did reach the new configuration.

Reproduction: `TestAuditEnsureSamePeersRefreshesBaseline` in
`audit_repro_test.go`.

Command:

```text
go test -run '^TestAuditEnsureSamePeersRefreshesBaseline$' -count=1 -v .
```

Observed result:

```text
testing.go:705: peer mismatch: {Servers:[{... ID:one ...}]} {Servers:[{... ID:one ...} {... ID:two ...}]}
--- FAIL: TestAuditEnsureSamePeersRefreshesBaseline (0.11s)
```

Alternative considered: this could indicate replication never completing. It
does not: the direct catch-up probe observes all three nodes reaching the
three-server configuration, while the helper still fails against its stale
captured baseline. This does not affect the production consensus path, but it
creates false ordering/timing failures in tests and downstream users of the
exposed `MakeCluster` helpers.

## Finding 7: exported live-recovery flag races its commit-staging reader

Severity: low to medium; public data race and unpredictable persistence mode

Affected code:

- `api.go:226-232`: `Raft.RestoreCommittedLogs` is exported, unlike the rest of
  the runtime state, and is copied once from `Config`.
- `raft.go:1392-1403`: every append reads the bool without synchronization.

Expected behavior: either the flag should be immutable/private after
construction, or changing it at runtime should use synchronized configuration
state. Concurrent public-field mutation must not race Raft's main loop.

Actual behavior: a concurrent write to `leader.RestoreCommittedLogs` races the
unsynchronized read in `tryStageCommitIndex`. The race detector reports the
write against reads from both `dispatchLogs` paths. Such mutation can also
silently toggle whether commit indexes are persisted.

Reproduction: `TestAuditRestoreCommittedLogsFieldMutationRace` in
`audit_repro_test.go`.

Command:

```text
go test -race -run '^TestAuditRestoreCommittedLogsFieldMutationRace$' -count=1 -v .
```

Observed result:

```text
WARNING: DATA RACE
Write ... TestAuditRestoreCommittedLogsFieldMutationRace.func1 ...
Previous read ... Raft.tryStageCommitIndex ... raft.go:1394
```

That run is execution `19eef98a229e479494d40b3e503595aa`.

Alternative considered: callers are intended to set this option only through
`Config` before `NewRaft`. That is likely the intent, but exposing a mutable
field on the live `Raft` object gives it public runtime semantics and bypasses
`ReloadConfig`; making the internal field private would close the race and
clarify support.

## Combined reproduction

Command:

```text
go test -run '^TestAudit' -count=1 -v .
```

Observed result:

```text
--- FAIL: TestAuditRestoreCommittedLogsRestoresConfiguration (0.33s)
--- FAIL: TestAuditRestoreCommittedLogsDoesNotDeadlockBeforeRunFSM (2.00s)
--- FAIL: TestAuditRestoreCommittedLogsDoesNotRegressCommitBehindSnapshot (0.38s)
--- FAIL: TestAuditRestoreCommittedLogsAppliesConfigurationAfterSnapshot (0.00s)
--- FAIL: TestAuditRestartAllNodesRecoversMembership (0.65s)
--- FAIL: TestAuditAppendEntriesDoesNotRegressPersistedCommitIndex (0.00s)
--- FAIL: TestAuditNewRaftWaitsForCommittedReplay (0.00s)
--- FAIL: TestAuditRegressedCommitIndexSkipsCommittedReplay (1.00s)
--- FAIL: TestAuditInmemCommitTrackingStoreBoundsStagedIndex (0.00s)
--- PASS: TestAuditProtocol2To3VoterCatchesUp (0.23s)
--- FAIL: TestAuditEnsureSamePeersRefreshesBaseline (0.10s)
--- FAIL: TestAuditRestartDoesNotResurrectRemovedVoter (0.38s)
--- PASS: TestAuditRestoreCommittedLogsFieldMutationRace (0.21s)
--- PASS: TestAuditRestoreCommittedLogsPropagatesCommitReadError (0.00s)
--- FAIL: TestAuditGetConfigurationDoesNotDeadlockOnCommittedReplay (2.01s)
--- FAIL: TestAuditGetConfigurationRecoversCommittedConfiguration (0.00s)
FAIL
FAIL	github.com/hashicorp/raft	7.386s
```

No captured source or dependency files were modified. The regression tests are
isolated in `work/audit_repro_test.go`.

The full suite was also run in the isolated local-network runner with
`go test ./...` after all audit tests were added. All pre-existing tests
passed; the only failures were thirteen audit test functions, covering seven
findings. `TestAuditProtocol2To3VoterCatchesUp` is a passing diagnostic that
separates the test-helper defect from replication behavior,
`TestAuditRestoreCommittedLogsPropagatesCommitReadError` validates the startup
error path, and the field-race test passes in ordinary mode but fails under
`-race` as documented above. The complete runner log is execution
`6e4103c970124b29b5f30c5528b2e5bf`.

The pre-existing suite also passed under the race detector with
`go test -race -v -skip '^TestAudit' .` (200 passes, 3 skips, no data-race
reports). That run is execution `23d2b30b74cb40959f92e18dc4f1c397`.

The three long integration tests normally excluded from the suite also passed
with `INTEG_TESTS=1`: `TestRaft_Integ`,
`TestRaft_RestartFollower_LongInitialHeartbeat`, and
`TestRaft_PreVote_LeaderSpam`. That run is execution
`c07029b6658a430b98871155453b4f1e`.

The feature's existing nominal tests
`TestRaft_RestoreCommittedLogs` and
`TestRaft_RestoreSnapshotOnStartup_CommitTrackingLogs` also passed for 50
consecutive isolated repetitions, execution
`7694b9d3975a468aa5efd1b0593b8b0d`. This supports the analysis that the new
failures require specific uncovered states rather than flaky execution.
The same two tests passed 10 repetitions on `GOARCH=386`, providing additional
coverage for atomic/index alignment on 32-bit targets (execution
`554545880dc442ca9191526dced646c9`).
The full suite was also run under `GOARCH=386`; all pre-existing tests passed,
and the only failures were the documented audit tests (execution
`823e529534ce4429b3e44c818126282b`).
The broader set matching `^TestRaft_(Restore|SnapshotRestore|RestoreSnapshot)`
passed 20 consecutive repetitions, with no further interaction failures
(execution `67c6b6d4400f4d2198634ee8aeef114e`).
The two nominal committed-log tests also passed 20 repetitions under the race
detector with no race reports (execution
`d2b96d2363664ec6ae9a014f0d1257eb`).

Coverage was also generated with the known-flaky protocol-upgrade tests and
audit tests excluded. The package reached 80.4% statement coverage; the new
recovery path was 73.7%, commit staging 71.4%, and `processLogs` 90.0%. The
remaining new-code gaps were error-return branches and the defensive
over-limit clamp, with no additional suspicious control flow. That run is
execution `f2fff0f147304d7e83ed6ba5479fa1bc`. The generated profiles are
retained as `work/audit_cover.out` and `work/audit_cover.html`.

The uncovered `GetCommitIndex` error-return branch was exercised separately:
`TestAuditRestoreCommittedLogsPropagatesCommitReadError` confirms that
`NewRaft` aborts with the store's error rather than partially starting. It
passes.

A randomized-order run with the explained
`TestRaft_ProtocolVersion_Upgrade_2_3` helper flake and audit tests excluded
passed. That run is execution `16eb89e18987468ea56e38ed3f45544b`.
Two additional randomized repetitions also passed; that run is execution
`598f9071c6254159a7aad5900dd16aab`.

At this point the semantic deltas from the prior release have been reviewed,
the new persistent-recovery branches have been tested under success, failure,
snapshot, membership, batching, and concurrency scenarios, and the remaining
uncovered branches in this code are error returns or the explicitly documented
clamp for a store that violates `CommitTrackingLogStore`'s bounds. No additional
implementation finding is currently supported by the available offline
evidence.

## Unresolved work

- Determine whether production implementations reject a decreasing
  `StageCommitIndex`; such a rejection would turn Finding 4 into a logged
  persistence failure rather than a silent rollback.
- The nested `fuzzy` module could not be run offline because its pinned
  `raft-boltdb` and `go-msgpack v0.5.5` archives are absent from the local
  module cache.
