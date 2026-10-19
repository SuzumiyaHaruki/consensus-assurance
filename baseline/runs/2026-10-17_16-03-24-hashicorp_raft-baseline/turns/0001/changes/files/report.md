# Audit report: hashicorp/raft baseline

Source snapshot: `cc91171013bec7a55e35d8e3043a7611ecd9795e`

Working copy: this directory. The captured source under `../source` was not
modified. Audit tests are in `audit_restore_committed_config_test.go`; captured
test output is under `audit_results/`.

Artifacts: `audit_results/finding1_*.txt` (membership loss cases),
`audit_results/finding2_*.txt` (deadlock and control),
`audit_results/all_audit_tests.txt` (combined run), and
`audit_results/baseline_*.txt` (upstream/network/fuzzy baseline runs).

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
   snapshot exists) membership and cannot campaign because it no longer holds a
   vote in its own view of the configuration.
2. **`NewRaft()` deadlocks for a sufficiently large committed log.** The restore
   path calls `processLogs()` before the FSM goroutine is started. `processLogs`
   sends fixed-size batches to `fsmMutateCh` (capacity 128), so restoring more
   than `128 * MaxAppendEntries` committed entries blocks forever in `NewRaft()`.
   With the default `MaxAppendEntries = 64`, the threshold is 8192 entries,
   below the default `TrailingLogs`/`SnapshotThreshold` range.

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
- `go test -run 'TestNetworkTransport|TestTCPTransport' .` passes in
  `isolated_exec` (4.2 s).
- `go test -run TestRaft_NoIssueSanity .` in `fuzzy/` passes (5-node,
  10000 applies, FSM hashes agree).
- The existing `RestoreCommittedLogs` tests pass. The main one takes a snapshot
  first and only asserts `lastApplied`, which is why it does not detect
  Finding 1.
- The audit tests are intentionally failing regression tests against the
  unmodified source. All five can be run together with:

  ```
  go test -run TestAuditRestoreCommittedLogs -v .
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
`raft.go:1807`).

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

### Necessary conditions

- `RestoreCommittedLogs` enabled and the log store implements
  `CommitTrackingLogStore`.
- The persisted commit index is at least the index of a configuration entry.
  Any cluster that has committed at least one command after bootstrap meets this.
- No newer uncommitted configuration entry happens to follow the committed one.
  If one exists, it becomes `latest`, but `committed` is still wrong because the
  skipped entry was never processed.

### Consequences

- `GetConfiguration()` reports empty/stale membership.
- `hasVote(r.configurations.latest, r.localID)` is false, so the follower logs
  "no known peers, aborting election" and never transitions to candidate.
- A single-voter cluster cannot re-elect after restart. If every voter restarts
  with this feature enabled and no snapshot, no node can campaign. This is a
  cluster-wide availability failure (executed with three voters above).
- With a snapshot, the node can come back with an outdated voter set (executed
  above). Because Raft uses the latest configuration to compute quorums, a
  membership history that has advanced several changes past the snapshot can
  leave a restarted node with a stale quorum view; this is safety-relevant, not
  only an availability issue.

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
  `r.goFunc(r.run)` / `r.goFunc(r.runFSM)` (`api.go:630-637`).
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

The test creates a valid store with the bootstrap configuration plus 9000
committed command entries (`commitIndex = 9001`), then calls `NewRaft` in a
goroutine. Observed output (`audit_results/finding2_deadlock.txt`):

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

### Necessary conditions

- `RestoreCommittedLogs` enabled with a commit-tracking store.
- More than `128 * MaxAppendEntries` entries between the last applied/snapshot
  index and the persisted commit index. With defaults: more than 8192. A smaller
  configured `MaxAppendEntries` lowers the threshold proportionally.

### Consequences

`NewRaft` never returns; the node never starts its main loop or FSM goroutine.
An application performing a rolling restart can hang on startup indefinitely.

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

## Unresolved / further work

- The interaction with `LogCache`: a commit-tracking store wrapped in
  `LogCache` no longer satisfies `CommitTrackingLogStore`, so
  `RestoreCommittedLogs` returns `ErrIncompatibleLogStore`. This is an API
  compatibility limitation, not yet classified as a correctness defect.
- Source-based suspicion, not executed: when the persisted commit index is
  below the snapshot index, `restoreFromCommittedLogs` sets the in-memory commit
  index to the lower value (after clamping to `logs.LastIndex()`). This makes
  `CommitIndex()` report a value below `AppliedIndex()`/the snapshot index. It
  appears conservative (not a safety violation), but it may surprise users of
  the read-index API; it was not counted as a finding.
- The repeated full-suite failure of
  `TestRaft_ProtocolVersion_Upgrade_1_2` was not reduced to a deterministic
  cause; it passes in isolation and the failing source is unchanged from
  v1.7.3. It is recorded as an unresolved flake, not a finding.
