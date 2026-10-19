# Audit report: hashicorp/raft baseline

Source snapshot: `cc91171013bec7a55e35d8e3043a7611ecd9795e`

Working copy: this directory. The captured source under `../source` was not
modified. Audit tests are in `audit_restore_committed_config_test.go`; captured
test output is under `audit_results/`.

Artifacts: `audit_results/finding1_*.txt` (membership loss cases),
`audit_results/finding2_*.txt` (deadlock and control),
`audit_results/finding3_replay_control.txt` (post-snapshot command replay
control),
`audit_results/finding4_commit_index_lag.txt` (commit-index staging
observation),
`audit_results/finding5_logcache_compat.txt` (LogCache compatibility
observation),
`audit_results/finding6_commit_below_snapshot.txt` (commit-index/snapshot
consistency observation),
`audit_results/finding1_stale_election.txt` (stale-quorum election
consequence),
`audit_results/finding1_stale_conflict.txt` (two leaders committing
conflicting entries),
`audit_results/finding1_real_cluster_conflict.txt` (normal cluster-operation
reproduction),
`audit_results/real_cluster_conflict_run{1,2,3}.txt` (repeat confirmation),
`audit_results/stale_conflict_run{1,2,3}.txt` (repeat confirmation),
`audit_results/all_audit_tests.txt` (combined run), and
`audit_results/audit_race.txt` (race-detector run),
`audit_results/audit_race_controls.txt` (clean race controls),
`audit_results/recovercluster_control.txt` and `audit_results/userrestore_control.txt`
(alternate recovery controls),
`audit_results/baseline_*.txt` (upstream/network/fuzzy baseline runs).
`reproduce_audit.sh` reruns every case and writes the raw outputs.

## Summary

Two concrete crash-recovery defects were reproduced in the
`RestoreCommittedLogs` startup path. Both require the opt-in
`Config.RestoreCommittedLogs = true` and a `LogStore` that implements
`CommitTrackingLogStore`.

1. **Committed membership is lost on restart.** `restoreFromCommittedLogs()`
   advances `lastApplied` to the persisted commit index before `NewRaft()` scans
   the log for configuration entries. The scan therefore starts after every
   committed configuration entry, and those entries are never loaded into the
   in-memory configuration. A restarted node reports an empty (or stale, when a
   snapshot exists) membership. With a snapshot, this can produce a smaller
   stale quorum view: the node can elect and commit without committed voters.
   Two partitions using stale and current configurations were also observed
   committing different entries at the same index and term.
2. **`NewRaft()` deadlocks for a sufficiently large committed log.** The restore
   path calls `processLogs()` before the FSM goroutine is started. `processLogs`
   sends fixed-size batches to `fsmMutateCh` (capacity 128), so restoring more
   than `128 * MaxAppendEntries` committed entries blocks forever in `NewRaft()`.
   With the default `MaxAppendEntries = 64`, the threshold is 8192 entries;
   that is comparable to the default `SnapshotThreshold` (8192) and below the
   default `TrailingLogs` (10240).

For a no-snapshot cluster with a committed configuration entry, the small-log
case loses membership and the large-log case hangs, so the feature is not
reliable for its documented restart use case.

## Method and baseline

- Diffed the captured source against the pristine `hashicorp/raft@v1.7.3` copy
  in the local module cache. Outside the 2026-dated `RestoreCommittedLogs`
  feature and small upstream/lint changes (error wrapping, metrics import,
  `time.Since`, snapshot error handling), no substantive protocol changes were
  found; the other protocol files match v1.7.3.
- Ran the upstream test suite. In the ordinary shell, TCP tests are blocked by
  the sandbox. In `isolated_exec` (private network namespace),
  `go test ./...` ran for ~144 s and failed three load-sensitive tests:
  `TestRaft_ProtocolVersion_Upgrade_1_2`,
  `TestRaft_ProtocolVersion_Upgrade_2_3`, and
  `TestRaft_FollowerRemovalNoElection`. Each passes when run alone
  (`go test -run 'TestRaft_ProtocolVersion_Upgrade_1_2|..._2_3' .` -> ok;
  `TestRaft_HasExistingState` also passed alone), so these are treated as
  pre-existing timing flakes under full-suite load, not findings. A second
  full-suite run failed only `TestRaft_ProtocolVersion_Upgrade_1_2`, consistent
  with timing rather than an order-dependent deterministic defect.
- A clean upstream run with the audit test file temporarily excluded passed in
  133.7 s (`audit_results/baseline_clean_full_suite.txt`: `ok
  github.com/hashicorp/raft 133.739s`). This confirms the earlier failures were
  load-related rather than deterministic source failures.
- `go test -run 'TestNetworkTransport|TestTCPTransport' .` passes in
  `isolated_exec` (4.2 s).
- `go test -run TestRaft_NoIssueSanity .` in `fuzzy/` passes (5-node,
  10000 applies, FSM hashes agree).
- `go test -run TestRaft_LeaderPartitions .` in `fuzzy/` passes (98 s, 5-node
  cluster with repeated leader partitions and final log/FSM verification);
  `audit_results/baseline_fuzzy_partition.txt`.
- The randomized membership suite (`TestRaft_AddMembership`,
  `TestRaft_AddRemoveNodesNotLeader`, `TestRaft_RemoveLeader`,
  `TestRaft_RemovePartitionedNode`) passes in `fuzzy/`
  (`audit_results/baseline_fuzzy_membership.txt`).
- The slow-voter and leadership-transfer fuzzy tests pass
  (`audit_results/baseline_fuzzy_election.txt`).
- The existing `RestoreCommittedLogs` tests pass. The main one takes a snapshot
  first and only asserts `lastApplied`, which is why it does not detect
  Finding 1.
- A fresh-FSM restart with a snapshot plus 50 post-snapshot committed commands
  applies all 150 commands (control in
  `audit_results/finding3_replay_control.txt`), so the underlying command
  replay itself works; the defect is specifically the configuration scan.
- A `RecoverCluster` recovery followed by a `RestoreCommittedLogs` restart also
  elects successfully and retains its configuration
  (`audit_results/recovercluster_control.txt`).
- A user-triggered `Restore` followed by a `RestoreCommittedLogs` restart also
  elects successfully and retains its configuration
  (`audit_results/userrestore_control.txt`).
- The audit tests include intentionally failing regression tests against the
  unmodified source plus passing controls. They can be run together with:

  ```
  go test -run TestAudit -v .
  ```

  Captured output: `audit_results/all_audit_tests.txt`.

## Finding 1: Restart with RestoreCommittedLogs loses committed membership

### Expected behavior

On startup, `NewRaft()` must reconstruct the current configuration from the
snapshot and from configuration log entries before the node serves. The
existing startup loop does this by calling `processConfigurationLogEntry()` for
each log entry after the snapshot (`api.go:610-625`). Committed configuration
entries are part of that range and must be loaded. Raft's own membership is
separate from any `ConfigurationStore` FSM and is required for
`hasVote()`/`inConfiguration()` checks and for campaigning
(`raft.go:230-245`, `raft.go:1667`, `raft.go:1703`, `raft.go:1780`,
`raft.go:1807`). Loading the latest committed configuration is also what makes
quorum calculations safe after restart; an obsolete membership can form a
smaller, non-intersecting quorum.

### Affected code

- `api.go:606-613`:

  ```go
  if err := r.restoreFromCommittedLogs(); err != nil { ... }

  // Scan through the log for any configuration change entries.
  snapshotIndex, _ := r.getLastSnapshot()
  lastappliedIndex := r.getLastApplied()
  for index := max(snapshotIndex, lastappliedIndex) + 1; index <= lastLog.Index; index++ {
  ```

- `api.go:723-754`: `restoreFromCommittedLogs()` reads the persisted commit
  index and calls `r.setCommitIndex(commitIndex); r.processLogs(commitIndex, nil)`.
- `raft.go:1296-1362`: `processLogs()` only queues entries to the FSM
  (`r.fsmMutateCh`) and sets `lastApplied`; it does **not** call
  `processConfigurationLogEntry()`. Therefore the startup loop is the only
  place that reconstructs `r.configurations` from log entries.

### What happens

`processLogs(commitIndex, nil)` sets `lastApplied = commitIndex`. The scan then
starts at `max(snapshotIndex, commitIndex) + 1`, so every configuration entry at
or below the persisted commit index is skipped. With no snapshot, the result is
an empty configuration; with a snapshot, the configuration is frozen at the
snapshot's (older) membership.

### Reproduction (executed)

Test file: `audit_restore_committed_config_test.go`.

```
go test -run TestAuditRestoreCommittedLogsKeepsConfiguration -v .
```

The test bootstraps one voter (configuration entry index 1), stores
`StageCommitIndex(1)`, and constructs the node with `RestoreCommittedLogs=true`.
Observed output (`audit_results/finding1_unit.txt`):

```
initial configuration: index=0 servers=[]
recovered configuration: {Servers:[]}
hasVote(after restart) = false
--- FAIL: TestAuditRestoreCommittedLogsKeepsConfiguration
```

Control with the feature disabled: the same store and index produce
`initial configuration: index=1 servers="[{...node1...}]"` and the test passes
(`audit_results/finding1_control_disabled.txt`). The failure is specific to the
`RestoreCommittedLogs` startup path.

Conforming-store check: `atomicCommitStore` in the audit test only makes a
staged index visible after the following `StoreLogs` succeeds, matching the
interface contract. Staging commit index 1 and atomically storing a no-op at
index 2 still reproduces the empty configuration after restart
(`audit_results/finding1_conforming_store.txt`:
`{Servers:[]} (lastApplied=1, commitIndex=1)`). The finding is not an artifact of
the in-memory helper's immediate persistence.

Package-level API check:
`TestAuditGetConfigurationRestoreCommittedLogs` calls
`GetConfiguration(conf, ...)` against the same committed state and receives
`{Servers:[]}` (`audit_results/finding1_getconfiguration_helper.txt`).

End-to-end single-node restart:

```
go test -run TestAuditRestoreCommittedLogsSingleNodeRestart -v .
```

Observed output (`audit_results/finding1_cluster.txt`):

```
config before restart: {Servers:[{Suffrage:Voter ID:server-... Address:...}]};
after restart: {Servers:[]} (lastApplied=6, commitIndex=6)
WARN ...: no known peers, aborting election
--- FAIL: TestAuditRestoreCommittedLogsSingleNodeRestart
```

The restarted node had the complete log and commit index 6, but its state stayed
`Follower`; it never became leader.

Snapshot case (membership change committed after the snapshot):

```
go test -run TestAuditRestoreCommittedLogsSnapshotStaleMembership -v .
```

Observed output (`audit_results/finding1_snapshot_stale.txt`):

```
configuration after restart: {Servers:[{Suffrage:Voter ID:node1 Address:node1}]}
(lastApplied=3, commitIndex=3)
expected: {Servers:[node1 node2]}
actual:   {Servers:[node1]}
```

The snapshot carries the old one-node configuration. The committed
`LogConfiguration` at index 3 adds `node2`, but the restart scan begins at index
4, so the node keeps the snapshot's stale membership.

Three-voter full restart:

```
go test -run TestAuditRestoreCommittedLogsAllVotersRestart -v .
```

All three nodes had logs and commit tracking. After shutting all of them down
and recreating the Raft instances over their persisted stores, every node
logged `initial configuration: index=0 servers=[]` and then
`no known peers, aborting election`:

```
node 0: state=Follower config={Servers:[]}
node 1: state=Follower config={Servers:[]}
node 2: state=Follower config={Servers:[]}
--- FAIL: TestAuditRestoreCommittedLogsAllVotersRestart
```

No leader was elected (`nLeaders == 0`). This is the cluster-wide availability
consequence of the local defect.

Quorum-safety consequence:

```
go test -run TestAuditStaleSnapshotConfigElectsWithoutCommittedVoter -v .
```

The node starts from a snapshot containing only `{nodeA}`, while its log and
persisted commit index contain a committed configuration `{nodeA,nodeB}`. After
restart it reports:

```
state=Leader config={Servers:[{Suffrage:Voter ID:nodeA Address:nodeA}]}
commitIndex=3 lastApplied=3
```

It elected itself with one vote and committed a no-op even though the committed
configuration requires both `nodeA` and `nodeB` for a quorum. This is a direct
quorum-safety consequence of the skipped committed configuration entry, not
only an availability/reporting issue.

Conflicting-commit demonstration:

```
go test -run TestAuditStaleConfigAllowsConflictingCommits -v .
```

The test starts a stale `{A}` view on one side and a current `{A,B,C}` view on
the other. The stale side elects alone; the current side elects with `B,C`.
Both sides then commit commands and produce:

```
A:  term=2 data="from-stale-partition"    commit=4
BC: term=2 data="from-current-partition" commit=4
```

Both entries are at the same index and term but have different data, so the
Raft Log Matching Property and election safety are violated. This is a direct
consequence of restoring a stale configuration; it is the strongest finding in
this audit. The same result was reproduced in three consecutive runs
(`audit_results/stale_conflict_run{1,2,3}.txt`).

The same violation was then reproduced through ordinary cluster operations,
without hand-built log stores:

```
go test -run TestAuditRealClusterStaleConfigConflict -v .
```

A starts as a one-voter cluster, takes a snapshot, adds B and C (committed),
applies commands, is shut down, and is restarted without transport connectivity
to B/C. B/C elect under the current configuration, A elects from its old
snapshot configuration, and both apply commands:

```
index=16 A(term=3,data="real-stale",commit=16)
         BC(term=3,data="real-current",commit=16)
```

This confirms the conflict is reachable through normal snapshot, membership
change, shutdown, and restart operations, not only through synthetic stores.
It reproduced in three consecutive runs
(`audit_results/real_cluster_conflict_run{1,2,3}.txt`).

### Necessary conditions

- `RestoreCommittedLogs` enabled and the log store implements
  `CommitTrackingLogStore`.
- The persisted commit index is at least the index of a configuration entry.
  Any cluster that has committed at least one command after bootstrap meets this.
- For the stale-quorum and conflicting-commit consequences, the node must also
  have a snapshot whose configuration predates a committed configuration entry
  in its log.
- No newer uncommitted configuration entry happens to follow the committed one.
  If one exists, it becomes `latest`, but `committed` is still wrong because the
  skipped entry was never processed.

### Consequences

- `GetConfiguration()` reports empty/stale membership.
- The package-level `GetConfiguration` helper (`api.go:453-465`) calls the same
  `NewRaft` startup path, so it returns the empty/stale configuration too.
- `hasVote(r.configurations.latest, r.localID)` is false, so the follower logs
  "no known peers, aborting election" and never transitions to candidate.
- A single-voter cluster cannot re-elect after restart. If every voter restarts
  with this feature enabled and no snapshot, no node can campaign. This is a
  cluster-wide availability failure (executed with three voters above).
- With a snapshot, the node can come back with an outdated voter set (executed
  above). The executed `{nodeA}`/`{nodeA,nodeB}` case shows the stale node
  electing and committing with one vote while the committed configuration
  requires two. The `{A}`/`{A,B,C}` partition test further shows two leaders in
  the same term committing different entries at the same index/term. Because
  Raft uses the latest configuration to compute quorums, a membership history
  that has advanced past the snapshot can leave a restarted node with a stale
  quorum view; this is a safety issue, not only an availability issue.

### Alternatives checked

- The membership is not recovered elsewhere: `processConfigurationLogEntry()` is
  called only from `NewRaft()`'s scan, `AppendEntries` for newly appended
  entries, and live bootstrap (`grep processConfigurationLogEntry`).
- The `ConfigurationStore` FSM interface does not substitute for Raft's own
  configuration; the failing test uses the ordinary `MockFSM`.
- The existing `TestRaft_RestoreCommittedLogs` avoids the bug by restoring a
  snapshot (which sets the configuration) and asserting only `lastApplied`.

## Finding 2: NewRaft deadlocks while restoring a large committed log

### Expected behavior

`NewRaft()` should complete startup after replaying committed entries.
`RestoreCommittedLogs` is documented as replaying all known-committed logs
before `NewRaft` completes (`config.go:239-256`).

### Affected code

- `api.go:606` calls `restoreFromCommittedLogs()` before
  `r.goFunc(r.run)` / `r.goFunc(r.runFSM)` (`api.go:636-638`).
- `api.go:753` calls `r.processLogs(commitIndex, nil)`.
- `raft.go:1304-1306` sends each batch to `r.fsmMutateCh`; `api.go:560` creates
  that channel with capacity 128.
- Batches hold up to `MaxAppendEntries` entries (`raft.go:1344-1347`); the
  default is 64 (`config.go:335`).

### What happens

There is no consumer of `fsmMutateCh` until `runFSM` starts, and `runFSM` starts
only after `NewRaft` returns. Once 128 batches are queued, the next send blocks
in `processLogs`; `NewRaft` can never reach `goFunc(runFSM)`. With defaults, the
threshold is 8192 committed entries (128 x 64). `TrailingLogs` defaults to 10240
and `SnapshotThreshold` to 8192, so this is a realistic post-snapshot replay
size.

### Reproduction (executed)

```
go test -run TestAuditRestoreCommittedLogsLargeLogStartup -v .
```

The test uses the conforming `atomicCommitStore` with the bootstrap
configuration plus 9000 committed command entries (`commitIndex = 9001`), then
calls `NewRaft` in a goroutine. Observed output
(`audit_results/finding2_deadlock.txt`):

```
processLogs.func1(...)          raft.go:1305
processLogs(...)                raft.go:1346
restoreFromCommittedLogs(...)   api.go:753
NewRaft(...)                    api.go:606
NewRaft did not return within 3s while restoring 9001 committed entries
(fsmMutateCh capacity=128, MaxAppendEntries=64)
--- FAIL: TestAuditRestoreCommittedLogsLargeLogStartup
```

The stack is a channel send, not slow disk I/O. The same `NewRaft` path returns
normally for the small logs used by the other audit tests.

Control: `TestAuditRestoreCommittedLogsBelowChannelCapacity` uses 8000 committed
entries (125 batches) and `NewRaft` returns in 0.01 s
(`audit_results/finding2_control_below.txt`). The cutoff is the channel
capacity, not replay cost.

End-to-end cluster check: `TestAuditRealClusterLargeLogRestartHangs` commits
9000 commands through a real one-node cluster, shuts it down, and restarts it
with the same stores. `NewRaft` remained blocked after 3 seconds
(`audit_results/finding2_real_cluster_deadlock.txt`), confirming the deadlock is
reachable through normal cluster operation.

### Necessary conditions

- `RestoreCommittedLogs` enabled with a commit-tracking store.
- More than `128 * MaxAppendEntries` entries between the last applied/snapshot
  index and the persisted commit index. With defaults: more than 8192. A smaller
  configured `MaxAppendEntries` lowers the threshold proportionally.

### Consequences

`NewRaft` never returns; the node never starts its main loop or FSM goroutine.
An application performing a rolling restart can hang on startup indefinitely.
The package-level `GetConfiguration` helper (`api.go:453-465`) calls NewRaft
with `skipStartup`, but the restore call happens before that check, so it
inherits the same hang for a large committed log.

## Fix directions (for the report's affected code)

- For Finding 1, the startup configuration scan must process every
  configuration entry after the restored snapshot, independently of how far
  `processLogs` advanced `lastApplied`. Alternatively,
  `restoreFromCommittedLogs` must call `processConfigurationLogEntry` for the
  committed entries it replays (without double-applying uncommitted entries).
- For Finding 2, replay must have a consumer before `NewRaft` blocks on
  `fsmMutateCh`: start the FSM goroutine first, apply synchronously during
  startup, or use an unbounded/direct replay path rather than the bounded
  runtime channel.

## Scope and limitations

- The results apply to the `RestoreCommittedLogs` opt-in path. With the default
  `RestoreCommittedLogs = false`, the startup scan still starts at the snapshot
  index and the reproduced failures do not occur.
- The test store (`InmemCommitTrackingStore`) is test-only. Findings 1 and 2 are
  in the library's startup code and do not depend on a specific durable store.
- The tests use `MockFSM` / a no-op FSM, so FSM-specific application behavior is
  not part of the evidence.

## Conclusion

- **Critical:** Finding 1 can produce two leaders and conflicting committed
  entries at the same index/term after a supported restart sequence involving a
  snapshot and a committed membership change.
- **High:** Finding 2 can prevent a node, or a restarted cluster, from
  completing `NewRaft` when the committed-log replay is large enough to fill
  `fsmMutateCh`.
- The additional commit-index and `LogCache` observations are API/feature-
  completeness issues and were not demonstrated to cause consensus-safety
  violations.

## Reproduction quick reference

```text
# all audit cases (intentionally failing assertions + passing controls)
go test -run TestAudit -v .

# primary safety violation through normal cluster operations
go test -run TestAuditRealClusterStaleConfigConflict -v .

# primary startup deadlock through normal cluster operations
go test -run TestAuditRealClusterLargeLogRestartHangs -v .

# alternate recovery controls
go test -run TestAuditRecoverClusterWithRestoreCommittedLogs -v .
go test -run TestAuditUserRestoreWithRestoreCommittedLogs -v .
```

The implementation under `../source` remains read-only and unchanged; all
diagnostic code is in `audit_restore_committed_config_test.go`.

## Additional observations and unresolved work

- The interaction with `LogCache`: a commit-tracking store wrapped in
  `LogCache` no longer satisfies `CommitTrackingLogStore`, so
  `RestoreCommittedLogs` returns `ErrIncompatibleLogStore`. This was executed in
  `TestAuditLogCacheDoesNotPreserveCommitTracking`
  (`audit_results/finding5_logcache_compat.txt`). It is an API compatibility
  limitation, not a consensus-safety defect, and is not counted in the two main
  findings.
- Executed low-severity observation: when the persisted commit index is below
  the snapshot index, `restoreFromCommittedLogs` sets the in-memory commit
  index to the lower value. `TestAuditCommitIndexBelowSnapshotAfterRestart`
  observed `commitIndex=1` with `lastApplied=2` (a snapshot at index 2), so
  `CommitIndex()` can be below `AppliedIndex()`
  (`audit_results/finding6_commit_below_snapshot.txt`). This is conservative
  for read-index users, but it is an API inconsistency; it was not counted as a
  safety finding.
- Executed low-severity observation: `tryStageCommitIndex` runs on the append
  paths (and leader dispatch) but not when a commit index advances without a
  following append. In `TestAuditCommitIndexPersistenceOnHeartbeatOnlyCommit`,
  a live leader had `commitIndex=12` while the store returned `11`
  (`audit_results/finding4_commit_index_lag.txt`). The persisted value can
  therefore lag the true commit index, so restart replay may omit recently
  committed entries even when `RestoreCommittedLogs` is enabled. This looks
  conservative rather than a safety violation (the entries remain in the log
  and a live leader will re-establish the commit index), so it is recorded as a
  feature-completeness issue, not one of the two main findings.
- The earlier `TestRaft_ProtocolVersion_Upgrade_1_2` failures occurred only
  under the loaded full-suite/audit-test runs; the clean upstream suite passes.
  They are treated as load-related flakes, not findings.
- `go test -race -run TestAudit .` primarily reported test logger/output races
  because intentionally failing tests leave Raft goroutines logging during test
  teardown; the stacks are in `testing.go`/`testLoggerAdapter`, not in Raft
  state. The passing controls pass under `-race`
  (`audit_results/audit_race_controls.txt`), so no production data race was
  identified.
