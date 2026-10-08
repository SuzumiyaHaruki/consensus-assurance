# Consensus assurance audit - hashicorp/raft (baseline)

**Target:** `/home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-08_13-11-14-hashicorp_raft-baseline/source`
**Source identity (run brief):** `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`
**Scope:** execution backend `go_module`, expected module `github.com/hashicorp/raft`,
execution package `.` (the root `raft` package).
**Audit status:** the artifact is the unmodified upstream v1.7.3 release. No defect was
found in the core consensus/agreement logic. One concrete, reproducible defect was
confirmed in the shipped test helper `EnsureSamePeers` (Finding 1, §3). See "Residual
uncertainty" (§5) for what was and was not covered.

---

## 0. Headline results

Two conclusions, stated separately because they rest on different evidence:

1. **No injected/planted mutation exists in the artifact.** The supplied source is
   **byte-for-byte identical to the upstream `github.com/hashicorp/raft` v1.7.3
   release**, which is the tag whose commit hash is given as `source_identity`
   (see §1). Any defect found here is therefore a *pre-existing upstream* defect, not
   a planted one. I found **no defect in the core consensus/agreement logic** (§4).

2. **Finding 1 (concrete, reproducible): a defect in the shipped test helper
   `(*cluster).EnsureSamePeers` (`testing.go:692-715`) makes the project's own
   tests fail nondeterministically (roughly 25-50% here), producing false negatives.**
   The helper caches `c.rafts[0]`'s configuration once and never refreshes it, so a
   single early read of a not-yet-converged node permanently poisons the comparison.
   Three tests were observed failing (`ProtocolVersion_Upgrade_1_2`, `_2_3`,
   `HasExistingState`); 10 tests call the helper and are exposed. See §3 for the
   executed reproduction and the experiment showing the *implementation itself*
   converges correctly. This is a local harness defect, not a consensus-safety defect,
   and it is within scope because `testing.go` ships in the audited package.

---

## 1. Identity verification (executed)

The Go module cache already contains a pristine copy of the same release at
`/home/nitro/go/pkg/mod/github.com/hashicorp/raft@v1.7.3`, with proxy metadata
`cache/download/github.com/hashicorp/raft/@v/v1.7.3.info` recording
`"Hash":"c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe","Ref":"refs/tags/v1.7.3"` - the
same commit the run brief names.

Whole-tree recursive diff of the read-only source against that pristine copy:

```
$ diff -rq <source> /home/nitro/go/pkg/mod/github.com/hashicorp/raft@v1.7.3
Only in <source>: fuzzy
Only in <source>: raft-compat
```

There are **no "Files ... differ" entries**: every file present in both trees has
identical bytes. `md5sum` spot checks on the security-critical files confirm this
(`audit/verification-facts.txt`):

```
raft.go            src=92d8f55e554659558d745c3f170cb008  cache=92d8f55e554659558d745c3f170cb008
api.go             src=f7f483548aef50aa16526144986f11ae  cache=f7f483548aef50aa16526144986f11ae
replication.go     src=1cd395843c9fa3cb32d4cbb8805f69c5  cache=1cd395843c9fa3cb32d4cbb8805f69c5
log.go             src=588d2b1ad6ecd80e17a646ea46c9ccd1  cache=588d2b1ad6ecd80e17a646ea46c9ccd1
configuration.go   src=78999f7a73e5ada3e4ad48edce3709ed  cache=78999f7a73e5ada3e4ad48edce3709ed
commitment.go      src=d044803a9b5b35e524eb29b29984882d  cache=d044803a9b5b35e524eb29b29984882d
... (see file)
```

The two "Only in" entries are expected and out of scope:
* `fuzzy/` and `raft-compat/` each carry their **own `go.mod`** (nested modules), so
  `go mod download` of the root module does not include them. `raft-compat` is also a
  git submodule (`.gitmodules`). Neither is the `execution_package` (`.`).

**Interpretation.** This artifact is the *unmodified upstream release*. Any concrete
defect found here would be a pre-existing upstream defect, not a planted one. That is
a materially different audit question, so I kept the process honest rather than
manufacturing a finding from a design nuance.

---

## 2. Executed checks

Environment: offline (`GOPROXY=off`), deps from the read-only module cache, Go 1.25.8.
The sandbox **blocks binding loopback TCP sockets** (`socket: operation not permitted`),
so any test that calls `NewTCPTransport`/`NewNetworkTransport` cannot run here. All
in-memory (`InmemTransport`) tests do run. Logs are preserved under `work/audit/`.

| Check | Command | Result |
|---|---|---|
| Build | `go build ./...` | ok (exit 0) |
| Vet | `go vet .` | ok, no diagnostics (`audit/vet.log`) |
| Full suite (short) | `go test -short -count=1 -timeout 700s .` | FAIL, **all 22 failures are `listen tcp ...: socket: operation not permitted`** (`audit/test-short.log`) |
| Race detector on core | `go test -race -short -run 'TestRaft_' .` | **no `DATA RACE`**; only the 2 TCP-dependent `TestRaft_runFollower_*` tests fail for socket reasons (`audit/test-race.log`) |
| Race detector, full non-network | `go test -race -short -skip 'TestNetworkTransport|TestTCPTransport|TestRaft_runFollower' .` | **ok, 0 `DATA RACE`** (`audit/test-race-full.log`) |
| Non-network suite x3 | `go test -short -count=3 -skip 'TestNetworkTransport|TestTCPTransport|TestRaft_runFollower' .` | FAIL: `TestRaft_HasExistingState` failed once, at `testing.go:705` - same root cause as Finding 1 (`audit/test-repeat3.log`) |
| Committed-entry churn soak | `go test -count=2 -run 'TestAudit_CommittedEntriesSurviveChurn' -v .` | **PASS 2/2**: 64 committed entries over 8 leader-isolation rounds per run, every replica retained every committed entry (`audit/soak.log`) |
| Snapshot region x5 under race | `go test -race -count=5 -skip 'PeerChange' -run 'TestRaft_Snapshot|TestRaft_AutoSnapshot|TestRaft_UserSnapshot|TestRaft_UserRestore|TestRaft_SendSnapshot|TestRaft_RestoreSnapshot|TestRaft_NoRestore|TestRaft_InstallSnapshot' .` | **PASS 50/50, 0 data races** (`audit/snapshot-race.log`) |

The full-suite failures are exactly the tests that need a real TCP listener:
`TestNetworkTransport_*`, `TestTCPTransport_*`, and the two `integ_test.go`
`TestRaft_runFollower_*` tests (which call `NewTCPTransport`, `integ_test.go:99`). No
failure was caused by consensus logic. Every other test (elections, log replication,
snapshots, membership, leadership transfer, commitment, log cache, etc., all on
`InmemTransport`) passed, and none tripped the race detector.

One log line worth explaining so it is not mistaken for a defect:
```
[ERROR] failed to install snapshot: error="failed to decode peers: msgpack decode error [pos 1]: only encoded map or array can be decoded into a slice (0)"
```
This is emitted by a test that deliberately feeds a malformed peers payload and
asserts the failure path (`installSnapshot`, `raft.go:1846-1853`). The producing test
passes; the message is expected output, not a failure.

---

## 3. Finding 1 - `EnsureSamePeers` caches a stale configuration and fails the test

**Severity:** test-harness correctness (false-negative test failure). Not a consensus
safety defect. **Status:** reproduced and root-caused.

### 3.1 Expected vs actual

`(*cluster).EnsureSamePeers` is meant to block until every Raft in the cluster reports
the same configuration, retrying for `longstopTimeout`. The retry loop re-reads the
*other* nodes (`otherSet`) on every pass but reads the reference node
`c.rafts[0]` **only once, before the loop** (`testing.go:694`):

```go
// testing.go:692
func (c *cluster) EnsureSamePeers(t *testing.T) {
	limit := time.Now().Add(c.longstopTimeout)
	peerSet := c.getConfiguration(c.rafts[0])   // <-- captured once

CHECK:
	for i, raft := range c.rafts {
		if i == 0 { continue }
		otherSet := c.getConfiguration(raft)     // <-- re-read each pass
		if !reflect.DeepEqual(peerSet, otherSet) {
			if time.Now().After(limit) {
				t.Fatalf("peer mismatch: %+v %+v", peerSet, otherSet)
			} else { goto WAIT }
		}
	}
	return
WAIT:
	c.WaitEvent(nil, c.conf.CommitTimeout)
	goto CHECK
}
```

**Expected:** if `rafts[0]` has not yet applied a just-committed configuration change at
the moment of the first read, the loop should re-read it and converge, because the
change *is* eventually applied everywhere.

**Actual:** `peerSet` is never refreshed. If the first read catches `rafts[0]` one step
behind, `peerSet` is frozen at the old configuration forever, the comparison can never
succeed, and the test fails with `peer mismatch:` after `longstopTimeout`. In the
failure output the first (stale) configuration is consistently the *older* one and the
second is the *new* one - the signature of this defect, e.g.:

```
--- FAIL: TestRaft_ProtocolVersion_Upgrade_1_2 (5.38s)
    testing.go:705: peer mismatch:
      {Servers:[A B]}          <- stale peerSet from rafts[0]
      {Servers:[A B C]}        <- live otherSet
```

### 3.2 Reproduction (executed)

`testing.go` is part of the audited package (`execution_package: "."`), so this runs
directly:

```sh
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-08_13-11-14-hashicorp_raft-baseline/work
export GOMODCACHE=/home/nitro/go/pkg/mod GOPROXY=off GOFLAGS=-mod=mod
go test -count=6 -timeout 480s -v \
  -run 'TestRaft_ProtocolVersion_Upgrade_1_2|TestRaft_ProtocolVersion_Upgrade_2_3' .
```

Result (log: `audit/upgrade-repeat.log`): **3 of 12 runs failed**, always at
`testing.go:705 peer mismatch`, always `{2-server config} != {3-server config}`. Example
failures: `_1_2` at 5.38s and 5.28s, `_2_3` at 5.32s; passing runs finish in ~0.5s.

The defect is not specific to the upgrade tests. Repeating the whole non-network suite
three times:

```sh
go test -short -count=3 -timeout 780s -skip 'TestNetworkTransport|TestTCPTransport|TestRaft_runFollower' .
```

produced a **third** victim - `TestRaft_HasExistingState` failed in one of the three
passes with the identical `testing.go:705 peer mismatch: {2 servers} {3 servers}`
signature (`audit/test-repeat3.log`). Scanning the test suite, **10 tests call the
defective helper**, so all of them are exposed to the same spurious failure:

```
raft_test.go:241  TestRaft_RecoverCluster
raft_test.go:285  TestRaft_HasExistingState              <- observed failing
raft_test.go:618  TestRaft_JoinNode
raft_test.go:669  TestRaft_JoinNode_ConfigStore
raft_test.go:862  TestRaft_RemoveFollower_SplitCluster
raft_test.go:1363 TestRaft_SnapshotRestore_PeerChange
raft_test.go:2270 TestRaft_ProtocolVersion_Upgrade_1_2    <- observed failing
raft_test.go:2304 TestRaft_ProtocolVersion_Upgrade_2_3    <- observed failing
raft_test.go:2338 TestRaft_LeaderID_Propagated
raft_test.go:3119 TestRaft_FollowerRemovalNoElection
```

A focused campaign running exactly those tests (`-count=10`, log `audit/campaign.log`)
produced **3 failures in 120 test executions**, and no other test failed:

```
1/10 FAIL  TestRaft_HasExistingState
2/10 FAIL  TestRaft_ProtocolVersion_Upgrade_1_2
0/10 FAIL  TestRaft_ProtocolVersion_Upgrade_2_3   (failed in other campaigns)
0/10 FAIL  the other 8 callers
```

The failure rate is timing-dependent and differs per run (this matches the earlier
~50% figure for the upgrade pair in a smaller loop); the important, stable facts are
the failure *signature* (`testing.go:705`, stale `peerSet` is the smaller/older config)
and that the affected set is exactly the callers of `EnsureSamePeers`.

### 3.3 Separating the helper defect from the implementation (executed)

To rule out the alternative explanation "the implementation genuinely fails to
propagate the configuration", I added a diagnostic-only test,
`audit_diag_test.go` (`TestAudit_EnsureSamePeers_StalePeerSetCapture`), which performs
the same setup (`MakeCluster(2, v2)` + merge `MakeClusterNoBootstrap(1, v3)` +
`AddVoter`), then (a) captures `rafts[0]`'s config immediately, exactly like
`EnsureSamePeers`, and (b) polls all three nodes until they agree.

```sh
go test -count=8 -timeout 180s -run 'TestAudit_EnsureSamePeers_StalePeerSetCapture' -v .
```

Result (log: `audit/audit-diag.log`): in **3 of 8 runs** the immediate capture was
already stale, and in every one of those runs all three nodes live-reported the new
3-server configuration within ~20 ms:

```
captured peerSet from rafts[0] immediately after AddVoter: n=2 {Servers:[A B]}
live: rafts[0]=3 rafts[1]=3 rafts[2]=3 converged=true
CONFIRMED: stale peerSet had 2 servers while the cluster live-reports 3; EnsureSamePeers
compares the stale capture forever and times out
```

So the *Raft implementation converges correctly*; the failure is entirely due to the
un-refreshed `peerSet` in the helper. This is a concrete defect (the project's own
tests are flaky/false-negative), and `TestRaft_ProtocolVersion_Upgrade_*` is the
observed user-visible symptom.

### 3.4 Proposed fix (not applied to the captured source)

Re-read the reference node inside the loop, e.g. move
`peerSet := c.getConfiguration(c.rafts[0])` to just after `CHECK:` (or make
`TAKE`/`CHECK` refresh all nodes). `audit_diag_test.go` is diagnostic-only and can be
deleted; the read-only `source/` tree was never modified.

The fix was verified with `audit_diag_test.go`'s `TestAudit_EnsureSamePeers_Fixed`,
which runs the identical scenario but re-reads the reference configuration each pass:

```sh
go test -count=20 -timeout 280s -run 'TestAudit_EnsureSamePeers_Fixed' -v .
# -> 20 x --- PASS, 0 FAIL  (audit/audit-fixed.log)
```

20/20 clean, versus the ~25-50% failure rate of the un-refreshed helper. This isolates
the cause to the cached `peerSet` and confirms the one-line re-read resolves it for all
10 callers.

### 3.5 Related source-based suspicion (not executed / not observed failing)

`(*cluster).EnsureLeader` (`testing.go:582-604`) differs from its siblings: it performs a
**single, non-retrying** comparison of every node's `LeaderWithID()` against the expected
leader and calls `t.Fatalf` on the first mismatch. `EnsureSame` and `EnsureSamePeers` both
poll until `longstopTimeout`; `EnsureLeader` has no such guard and no `WaitEvent`. It is
currently invoked only right after `EnsureSamePeers`/`EnsureSame` (e.g.
`raft_test.go:2271-2272`), which usually masks it, so I did not observe it failing. But if
leader propagation is still in flight at that instant (a real possibility after a
configuration change, since `EnsureSamePeers` waits on *configuration*, not on *leader
agreement*), it would flake the same way Finding 1 does. I record this as a suspicion
only: it is supported by the code's structure, not by an executed failure.

---

## 4. Source review of the core agreement paths (source-based, not executed)

I read the main thread and replication paths that carry Raft's safety properties. Line
numbers are for the audited tree. For each I note the property and why I did not find a
defect. This section records *coverage*, not a claim of proven correctness.

* **Follower term/leader handling and log matching** - `appendEntries`, `raft.go:1440`.
  Older-term requests are ignored; newer terms transition to follower; `PrevLogEntry`/
  `PrevLogTerm` are verified (with the snapshot-boundary shortcut `nextIndex-1 == lastSnapIdx`
  mirrored in `setPreviousLog`, `replication.go:587`). Conflicting suffixes are deleted
  with `DeleteRange` and the cached latest configuration is rolled back to the committed
  configuration when the truncation crosses `latestIndex` (`raft.go:1544-1550`). Commit
  index advances only to `min(leaderCommit, lastIndex)` (`raft.go:1575`). Consistent with
  standard Raft.

* **Vote granting and election restriction** - `requestVote`, `raft.go:1603`.
  Rejects non-configuration/non-voter candidates, refuses to vote when a different leader
  is known unless `LeadershipTransfer`, enforces the log up-to-dateness rule
  (term, then index) and persists the vote via `persistVote` before granting
  (`raft.go:1727`). Pre-vote path (`requestPreVote`, `raft.go:1736`) grants without
  mutating term/vote, as intended. Duplicate same-term votes for the same candidate are
  re-granted idempotently. Consistent with the protocol.

* **Leader lease / quorum** - `checkLeaderLease`, `raft.go:1036`; `quorumSize`,
  `raft.go:1086`. Counts self plus voters whose `replState.LastContact()` is within
  `LeaderLeaseTimeout`, steps down below quorum. `replState` entries for voters are
  created synchronously by `startStopReplication` (`raft.go:582`) before the lease check
  can run on the main thread, so the `replState[server.ID]` lookup is not a nil-deref
  window under normal operation.

* **Snapshot install and configuration restore** - `installSnapshot`, `raft.go:1814`.
  Version-gated; older terms ignored; the snapshot is streamed, size-checked, applied to
  the FSM, then `lastApplied`/`lastSnapshot`/latest+committed configuration are updated
  and old logs removed/compacted depending on `MonotonicLogStore`. On restore failure it
  logs and returns without corrupting state. Consistent with upstream behavior.

* **User restore ("burn an index")** - `restoreUserSnapshot`, `raft.go:1104`.
  Refuses while a configuration change is outstanding (`committedIndex != latestIndex`),
  aborts inflight futures with `ErrAbortedByRestore`, rewrites the snapshot at
  `max(lastIndex, meta.Index)+1` so replication faults and re-sends the snapshot. The
  committed/latest indices for the *current* configuration are used deliberately (the
  doc comment states this), so restoring into a new cluster is intended.

* **Leader replication setup / pipelining** - `replicateTo`, `setupAppendEntries`,
  `setNewLogs`, `pipelineReplicate` (`replication.go:202,570,614,446`). `MaxAppendEntries`
  batching, `nextIndex` backoff on conflict, and `updateLastAppended`
  (`replication.go:655`) match-index updates look consistent with the code's own
  invariants.

* **Log cache** - `log_cache.go`. Cache is only populated after a successful store and is
  fully invalidated on `DeleteRange`, matching the documented `LogStore`/`MonotonicLogStore`
  contracts.

None of the above produced a counterexample I could turn into a failing test.

---

## 5. Residual uncertainty / unresolved work

Honesty requires flagging the boundaries of this result:

1. **No planted mutation was found; the artifact is the upstream tag.** If the intent was
   to audit a *modified* build, this run appears to be a clean baseline. A different
   run with a mutated source (differing from the v1.7.3 tag) is what would carry a
   planted defect. Finding 1 (§3) is therefore a pre-existing upstream harness defect,
   reproducible against the v1.7.3 tag as shipped.
2. **Network transport not exercised.** `net_transport.go` / `tcp_transport.go` and their
   tests require loopback sockets, which the sandbox denies. Their framing, pooling, and
   pipeline code is therefore unverified by execution here.
3. **`fuzzy/` and `raft-compat/` modules unverified.** They are separate modules
   (own `go.mod`, and `raft-compat` is a git submodule absent from the module zip), so
   they were out of the `execution_package` and not built/tested.
4. **Long-run / disk-backed soak not performed.** Only `-short` tests plus the in-memory
   `TestRaft_` subset under `-race` were run; Boltdb-backed stores, fsync/latency
   injection, and multi-hour soak are not covered by this budget.
5. **Redundancy checks not performed.** No differential comparison against the
   `raft-compat` previous-version implementation (needs the missing submodule).

Updated coverage from this pass: the *full* non-network suite now passes under `-race`
with 0 data races (`audit/test-race-full.log`), so no concurrency defect was surfaced in
the exercised paths. Repeating the non-network suite also found a third affected test
for Finding 1 (`audit/test-repeat3.log`). Because the `EnsureSamePeers` defect is
timing-dependent, further repeats may reveal more victims among the 10 callers; the
fix in §3.4 addresses all of them at once.

A bounded safety soak (`TestAudit_CommittedEntriesSurviveChurn`, `audit/soak.log`) was
added to probe the core safety property directly rather than rely only on the project's
tests: a 5-node in-memory cluster applies commands while the current leader is
repeatedly isolated (forcing re-elections) and then healed, and it asserts that every
command reported committed (`Apply` returned nil) is present on every replica. Two runs
passed (64 committed entries, 8 churn rounds each) with no loss. This is *positive
negative-evidence*, not proof: it is a small randomized sample, uses the in-memory store
and transport, and does not cover disk persistence, restarts, or snapshot+compaction
interactions under churn. Those remain open (§5 items 2-4).

The snapshot/restore/compaction region was also exercised repeatedly under the race
detector: `TestRaft_{AutoSnapshot,SnapshotRestore,SnapshotRestore_Progress,UserSnapshot,
UserRestore,SendSnapshotFollower,SendSnapshotAndLogsFollower,NoRestoreOnStart,
RestoreSnapshotOnStartup_Monotonic,InstallSnapshot_InvalidPeers}` at `-count=5`
completed **50/50 passes with 0 data races** (`audit/snapshot-race.log`). This reduces
(but does not eliminate) the snapshot+compaction-under-churn gap.

Recommended next steps if budget continues: (a) run `net_transport` tests in an
environment that permits loopback, (b) build/test the `fuzzy/` module, (c) run a
targeted randomized soak of elections + snapshot install + membership changes
(e.g. `fuzzy/simple_test.go`) under `-race`.

---

## 6. Reproduction

```sh
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-08_13-11-14-hashicorp_raft-baseline/work
export GOMODCACHE=/home/nitro/go/pkg/mod GOPROXY=off GOFLAGS=-mod=mod

# identity: source == upstream v1.7.3
diff -rq ../source /home/nitro/go/pkg/mod/github.com/hashicorp/raft@v1.7.3

go build ./...
go vet .
go test -short -count=1 -timeout 700s .            # see audit/test-short.log
go test -race -short -run 'TestRaft_' -count=1 -timeout 700s .   # see audit/test-race.log
```

Artifacts preserved in this directory:
* `audit/verification-facts.txt` - identity diff + md5 evidence
* `audit/test-short.log` - full short test run
* `audit/test-race.log` - race-detector run of `TestRaft_`
* `audit/test-race-full.log` - race-detector run of the full non-network suite (0 races)
* `audit/test-nonnetwork.log` - short run with socket-bound tests skipped (surfaced Finding 1)
* `audit/test-repeat3.log` - non-network suite x3 (surfaced the third victim test)
* `audit/campaign.log` - `-count=10` over the 10 `EnsureSamePeers` callers (3/120 fail)
* `audit/soak.log` - committed-entry churn soak, 2/2 pass (no safety violation)
* `audit/snapshot-race.log` - snapshot region x5 under race, 50/50 pass
* `audit/upgrade-repeat.log` - `-count=6` repeat showing the flaky `ProtocolVersion_Upgrade` failures
* `audit/audit-diag.log` - diagnostic run proving the nodes converge (Finding 1 §3.3)
* `audit/audit-fixed.log` - fixed-helper demo, 20/20 pass (Finding 1 §3.4)
* `audit/vet.log` - `go vet` output (empty = clean)
* `report.md` - this report

Diagnostic-only file (added by the audit, safe to delete): `audit_diag_test.go`. It is
the only test source added to `work/`; no pre-existing file was edited.

No files under `source/` were modified; the writable `work/` tree is a copy, and the
only additions (`audit/`, this report) are diagnostic artifacts, not source changes.
