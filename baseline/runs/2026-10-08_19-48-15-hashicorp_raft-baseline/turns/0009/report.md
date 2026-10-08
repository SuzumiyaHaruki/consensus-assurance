# Audit report — hashicorp/raft (source identity c0dc6a0b, tag v1.7.3)

Working directory: `/home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-08_19-48-15-hashicorp_raft-baseline/work`
Read-only source: `.../source`  ·  Module: `github.com/hashicorp/raft`

## Verdict (current)

No concrete correctness defect was identified in the captured implementation within the
authorized scope and the checks performed. The captured tree is byte-for-byte identical to the
official `github.com/hashicorp/raft@v1.7.3` module content (verified below), the full in-process
test suite passes, `go vet`/`gofmt` are clean, and a source review of the consensus-critical paths
found no deviation from the specified Raft algorithm.

This is a *negative* result, stated with its limits: two categories of check could not be executed
in my shell (TCP transport tests; the `fuzzy`/`raft-compat` helper modules). Those limits are
listed in "Unresolved / not covered" and are not evidence of a defect.

### Confidence and residual risk

Supporting the negative result: (a) the tracked files are byte-identical to the official v1.7.3
module content; (b) the complete test suite passes except for tests that literally cannot create a
socket here; (c) the full suite under `-race` reports zero data races; (d) three independent checks
I wrote (in-memory crash/restart, randomized acknowledged-entry safety, socketless transport
RPC/pipeline/heartbeat/snapshot) pass, including under `-race`; and (e) the consensus-critical
source paths were read and match the Raft specification.

What would overturn this: a defect that is (i) not exercised by the shipped test suite (all of
which passes here), (ii) not observable through the in-memory transport, and (iii) outside the
code I read. The plausible residual surface is therefore narrow: the TCP `StreamLayer` syscall
paths in `tcp_transport.go`/`net_transport.go` under real network faults, and the `fuzzy`
linearizability harness — both unreachable in this sandbox. No evidence suggests a defect there
(the transport logic was reviewed and exercised via a socketless fake stream layer).

## Provenance — was the implementation modified?

Goal: decide whether a defect was injected relative to upstream before spending the budget on
line-by-line algorithm review. Method: compare the captured source against the pristine module
copy in the Go module cache, and check module integrity metadata.

Commands and raw output are preserved in `logs/provenance.txt`.

1. `diff -rq /home/nitro/go/pkg/mod/github.com/hashicorp/raft@v1.7.3 <source>` →
   **no differences in any tracked file.** The only reported entries are two directories present in
   the source but excluded from the module zip because they are separate modules:
   `fuzzy/` and `raft-compat/`.
2. The module metadata ties the cache copy to the exact requested identity:
   `v1.7.3.info` → `"Hash":"c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe","Ref":"refs/tags/v1.7.3"`,
   i.e. the same value as the run brief's `source_identity`.
3. Module integrity: `v1.7.3.ziphash` = `h1:DxpEqZJysHN0wK+fviai5mFcSYsCkNpFUl1xpAW8Rbo=` and the
   cached `sum.golang.org` lookup record contains the same
   `github.com/hashicorp/raft v1.7.3 h1:DxpEqZ...` line, with a `sum.golang.org` signed tree-head
   note.

Conclusion (executed observation): the tracked implementation is the unmodified upstream v1.7.3
release. A defect injected into the tracked Go files would have to have been applied identically
to both the captured source and the module cache; the signed transparency-log line for the same
`h1:` hash makes that implausible (though a coordinated offline tamper of cache + tree note cannot
be fully excluded from inside the sandbox). I therefore also reviewed the algorithm source
directly rather than relying on the diff alone.

## Checks executed

Toolchain: `go version go1.25.8 linux/amd64`; `GOFLAGS=-mod=readonly`, `GOPROXY=off`,
`GOSUMDB=off`, `GOMODCACHE=/home/nitro/go/pkg/mod`, local build cache under `work/.runtime`.

1. **Full package test suite** — `go test -count=1 -timeout 600s .` (log `logs/test_full.log`,
   verbose rerun `logs/test_verbose.log`).
   Result: `173` tests/subtests PASS. `17` tests FAIL, and every failure is
   `listen tcp 127.0.0.1:0: socket: operation not permitted` — the ordinary shell sandbox forbids
   creating AF_INET sockets. The failing set is exactly the transport tests:
   `TestNetworkTransport_*`, `TestTCPTransport_*`, and the two `TestRaft_runFollower_*` cases that
   build a TCP transport. No logic assertion failed.
2. **Formatting / vetting** — `gofmt -l *.go` → empty; `go vet .` → clean (exit 0).
3. **Race detector on core scenarios** — `go test -race -count=1 -timeout 900s -run
   'TestRaft_(LeaderFail|TripleNode|SingleNode|JoinNode|ReJoinFollower|RemoveFollower|RemoveLeader|
   SendSnapshotFollower|SendSnapshotAndLogsFollower|SnapshotRestore|LeadershipTransferWithWrites|
   PreVoteMixedCluster|RecoverCluster|UserSnapshot|AddVoter|AppendEntry|BehindFollower|Barrier|
   VoteNotGranted_WhenNodeNotInCluster)' .` (log `logs/test_race.log`).
   Result: **no `DATA RACE` reports.** One test assertion failed (see next item).
4. **Flaky-test characterization** — `TestRaft_SnapshotRestore_PeerChange` failed once during the
   loaded `-race` run (`raft_test.go:1359: bad last: 102`). Re-measured:
   `go test -race -count=40 -run TestRaft_SnapshotRestore_PeerChange .` → 2 failures;
   `go test -count=60 -run TestRaft_SnapshotRestore_PeerChange .` → 0 failures (also 0 in
   `-count=20` earlier). This is a timing-sensitive *test* artifact, not an implementation defect:
   the test waits with `EnsureSame` (which only requires all FSMs to share the same last index),
   then asserts `lastApplied == 103`, i.e. that the leader's post-election no-op has already been
   applied. Under `-race` scheduling the check can run after `EnsureSame` returns but before the
   no-op is applied, yielding `102`. The commit/replication code paths involved are all exercised
   and pass in normal runs.
5. **Independent crash/restart stress test (new)** — the shipped `TestRaft_Integ` /
   `TestRaft_RestartFollower_LongInitialHeartbeat` crash-restart tests are TCP-based and gated by
   `INTEG_TESTS`, so they never run here. I wrote an in-memory equivalent,
   `zz_audit_crash_test.go:TestAudit_CrashRestartFollower` (diagnostic file added to the work copy,
   not part of the captured implementation). Per round it applies 20 entries, crash-shuts-down a
   follower, keeps committing 10 more entries without it (quorum = the remaining two nodes),
   restarts the follower with its same durable log/stable/snapshot stores, and requires the whole
   cluster to reconverge with **no committed entry lost** on the recovered node or the leader.
   Result: **3/3 PASS** (`go test -count=3`, ~10.5s each) and **PASS under `-race`** with no
   `DATA RACE`. Note: an earlier version of this harness replaced the crashed node's transport,
   which stalled (the library's own multi-node restart tests build a fresh transport for a *new*
   single-node env, not for re-insertion into a live cluster); switching to reuse of the un-closed
   in-memory transport made it deterministic. That was a defect in my harness, not in the
   implementation.
6. **Repeated crash/partition sweep under `-race`** — `go test -race -count=6 -timeout 850s -run
   'TestRaft_(LeaderFail|TripleNode|RemoveLeader|RemoveFollower|RecoverCluster|
   SendSnapshotAndLogsFollower|SendSnapshotFollower|BehindFollower|JoinNode|ReJoinFollower|PreVote|
   LeaderID_Propagated|LeaderLeaseExpire|SnapshotRestore|SingleNode|HasExistingState)$' .`
   (log `logs/test_race_sweep.log`) → exit 0, no `DATA RACE`. This repeatedly exercises
   leader-failure, membership-change, snapshot-transfer and jump-ahead paths under randomized
   timings.
7. **Randomized safety check (new)** — `zz_audit_crash_test.go:TestAudit_RandomizedSafety` drives a
   3-node cluster through 120 randomized steps (applies, leader transfer, node isolation, heal,
   snapshot), then heals and checks a core linearizability invariant: **every command whose apply
   future returned success must be present in every node's applied state.** Result: **PASS**
   non-race (2/2, ~50 and ~38 acked commands) and **PASS under `-race`** with no `DATA RACE`
   (log `logs/audit_randomized.log`). This is stronger than `EnsureSame` (which only checks
   node-to-node equality) because it independently anchors the acknowledged log prefix.
   The same test also asserts the **Raft Log Matching Property** directly from each node's
   `LogStore`: for any two logs and any shared index, the entry term/type/data must be identical
   (checked over all overlapping indices, including the uncommitted tail). PASS (non-race 2/2 and
   under `-race`).
8. **Transport-layer source review** — since every `NetworkTransport` test needs AF_INET, I read
   `net_transport.go` and `tcp_transport.go` directly: conn pooling (`getPooledConn`/`returnConn`
   with `maxPool`), `genericRPC` deadlines, `InstallSnapshot` size-scaled deadline + dedicated
   connection, `listen`/`handleConn`/`handleCommand` framing (heartbeat fast-path, `LimitReader`
   for snapshot payload), `sendRPC`/`decodeResponse` reuse rules, and the `netPipeline`
   in-flight/buffer arithmetic (`maxInFlight-2`, `minInFlightForPipelining`). All consistent with
   upstream and with the interface contracts; no defect found.
9. **Executed transport coverage without sockets (new)** —
   `zz_audit_transport_test.go:TestAudit_NetTransportPipe` drives `net_transport.go` through a
   `net.Pipe`-backed fake `StreamLayer` (Go's `net.Pipe` needs no AF_INET). It exercises the
   generic request/response path (`AppendEntries`, `RequestVote`, `RequestPreVote`, `TimeoutNow`),
   the heartbeat fast-path handler, `InstallSnapshot` request + streamed payload, and the pipelined
   `AppendEntries` path. Result: **PASS**, stable over `-count=20`, and **PASS under `-race`** with
   no `DATA RACE`. (A first attempt deadlocked; the cause was my harness not draining the
   pipeline's unbuffered `doneCh`, i.e. the documented back-pressure, not an implementation fault.)

## Source review of consensus-critical paths (no defect found)

Read directly (source-based, cross-checked against the Raft spec and the upstream design):

- **Election counting / quorum** — `runCandidate` (`raft.go:285`) counts a strict majority via
  `quorumSize()` (`voters/2 + 1`) for both pre-vote and vote; term-regression handling is correct.
- **Commit rule** — `commitment.recalculate` (`commitment.go`) takes `matched[(len-1)/2]` of the
  sorted match indexes and gates on `startIndex`, which is the correct "highest index on a
  quorum" rule for n = 2..5 (checked by enumeration); `match` ignores non-voters and never
  regresses an index.
- **AppendEntries** — `appendEntries` (`raft.go:1440`): term checks, previous-entry verification
  with `NoRetryBackoff`, conflicting-suffix truncation + configuration rollback, and
  `commitIndex = min(leaderCommit, lastIndex)` all match the spec.
- **Replication** — `replicateTo` (`replication.go:202`) next-index backoff
  `max(min(nextIndex-1, resp.LastLog+1), 1)`, `setPreviousLog` snapshot-boundary handling,
  `setNewLogs` batching, and `updateLastAppended` match-index update are correct.
- **Leader lease** — `checkLeaderLease` (`raft.go:1036`) counts self + recently-contacted voters
  and steps down below quorum; correct.
- **Snapshot handling** — `installSnapshot`, `restoreUserSnapshot`, `file_snapshot.go`
  create/retain, and the monotonic-store path were reviewed; index/term bookkeeping and the
  "higher of snapshot or current index, +1" hole creation for user restores are consistent.
- **State/index accessors** — `getLastIndex` = `max(lastLogIndex, lastSnapshotIndex)`,
  `getLastEntry`, `setLastLog`, and atomic term/commit/applied accessors (`state.go`) are correct.
- **Log dispatch / config change** — `dispatchLogs` (`raft.go:1244`, monotonic index assignment,
  local match, `setLastLog`) and `appendConfigurationEntry` + `nextConfiguration`
  (`configuration.go`) match upstream: prev-index guard, single-server semantics, last-voter
  protection via `checkConfiguration`.
- **FSM apply loop** — `runFSM`/`applySingle`/`applyBatch` (`fsm.go`): correct
  `lastIndex`/`lastTerm` bookkeeping, `LogConfiguration` skipped when the FSM is not a
  `ConfigurationStore`, batch-response length check, and futures always responded. Matches upstream.
- **Public API contracts** — `Apply`/`ApplyLog` (enqueue timeout vs `ErrRaftShutdown`), `Barrier`,
  `VerifyLeader`, `GetConfiguration`, `Shutdown`, and the leader/membership entry points
  (`api.go`): timeout channels, error futures, and response wiring match the documented contracts.

## Candidate issues considered and dismissed

- `TestRaft_SnapshotRestore_PeerChange` failing under `-race` — dismissed as a test-timing
  artifact (section "Checks executed", item 4).
- `TestNetworkTransport_*` / `TestTCPTransport_*` failing — dismissed as a sandbox limitation
  (`socket: operation not permitted`), not a code fault.
- `commitment.recalculate` index `matched[(len-1)/2]` — checked by enumeration for n = 2..5;
  it is the correct quorum-match index.

No confirmed defect remains open at this point.

## Unresolved / not covered

### Final broad check (executed)

`go test -race -count=1 -timeout 800s .` — the **entire** package test suite (including the three
audit tests) under the race detector: **0 `DATA RACE`** reports; the only failures are the same 17
AF_INET-blocked transport tests (22 `operation not permitted` occurrences). No logic assertion
failed. Log: `logs/test_race_full.log`. This is the widest single executed check performed.

- **TCP transport tests not executed here.** The ordinary shell cannot create AF_INET sockets
  (`socket: operation not permitted`; confirmed directly: `python3 -c "import socket;
  socket.socket(socket.AF_INET)"` → `[Errno 1] Operation not permitted`, while AF_UNIX works), so
  `TestNetworkTransport_*` and `TestTCPTransport_*` were not run. The run brief provides an
  `isolated_exec` MCP tool that allows private local TCP; from
  my side the tool was exposed but I could not dispatch it this turn (every attempted call routed
  to the ordinary shell), and `bwrap --unshare-net` is itself blocked by the sandbox
  (`Failed to create NETLINK_ROUTE socket`). `net_transport.go` / `tcp_transport.go` were reviewed
  by reading only.
- **`fuzzy/` and `raft-compat/`** are separate Go modules (excluded from the module zip, so not
  covered by the provenance diff). Their tests could not be built offline: the required
  `github.com/hashicorp/raft-boltdb` and `github.com/boltdb/bolt` zips are not in the local module
  cache. These are fuzz/compat harness modules, not the consensus implementation.
- If the runner wants a stronger crash/partition check, the intended next step is to run the
  `fuzzy` linearizability tests (and the full suite including TCP tests) through `isolated_exec`
  once dependencies are available.

## Reproduction

```sh
cd /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-08_19-48-15-hashicorp_raft-baseline/work
go test -count=1 -timeout 600s .                 # 173 pass; only AF_INET transport tests fail
go test -count=1 -v -timeout 900s . > logs/test_verbose.log
gofmt -l *.go ; go vet .
go test -race -count=40 -run TestRaft_SnapshotRestore_PeerChange .   # ~2/40 flake under -race
go test -count=60 -run TestRaft_SnapshotRestore_PeerChange .         # 0/60 without -race
go test -count=3 -run TestAudit_CrashRestartFollower .               # in-memory crash/restart
go test -race -count=1 -run TestAudit_RandomizedSafety .             # randomized safety invariant
```

Preserved artifacts: `logs/provenance.txt`, `logs/test_full.log`, `logs/test_verbose.log`,
`logs/test_race.log`, `logs/test_race_sweep.log`, `logs/audit_randomized.log`.

Diagnostic source (added to the work copy, not part of the captured implementation):
`zz_audit_crash_test.go` (`TestAudit_CrashRestartFollower`, `TestAudit_RandomizedSafety`) and
`zz_audit_transport_test.go` (`TestAudit_NetTransportPipe`). Run all three with
`go test -race -run 'TestAudit_' .` (log `logs/audit_transport.log`).
