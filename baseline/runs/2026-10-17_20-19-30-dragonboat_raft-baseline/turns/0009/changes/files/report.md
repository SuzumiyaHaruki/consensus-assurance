# Dragonboat Raft audit — findings so far

Scope: captured tree `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`
(`github.com/lni/dragonboat/v3`, reports itself as v3.3.8 in
`nodehost.go:114-121`). Source is read-only; all work is in this directory.
Toolchain: go1.23.5, offline module cache. Ordinary shell has no network; tests
that listen on TCP were run through `isolated_exec`.

The reproduction tests are behind the `dragonboat_audit` build tag so the
default test run of the supplied code is unaffected. All commands below use
`-tags dragonboat_no_rocksdb,dragonboat_audit`.

Baseline evidence collected before any analysis:

- `go test -tags dragonboat_no_rocksdb -count=1 ./internal/...` passes except
  `internal/transport` (sandbox blocks `listen` in the ordinary shell; see the
  transport bullet below for the isolated-namespace result) and
  `internal/logdb/tee` (rocksdb cgo header unavailable, environmental).
- `go test -tags dragonboat_no_rocksdb -count=1 .` (root package) passes.
- Final default matrix run (all in the isolated namespace where sockets are
  needed): `./internal/raft ./internal/rsm ./internal/logdb ./internal/server
  ./tools ./client ./config ./raftpb .` all pass.
- Race detector: `./internal/raft ./internal/rsm ./internal/logdb
  ./internal/server` and the root package pass; the full transport suite
  (including mutual-TLS variants, in the diagnostic copy) passes under
  `-race` as well.
- `go test -race -tags dragonboat_no_rocksdb -count=1 .` passes.
- The consensus-critical root tests (`TestNodeHostReadIndex`,
  `TestNodeHostLeadershipTransfer`, `TestNodeCanBeAdded`,
  `TestNodeCanBeDeleted`, `TestSnapshotCanBeMade`, `TestNodesCanBeRestarted`,
  `TestLinearizableReadCanBeMade`, `TestNodeHostAddNode`,
  `TestNodeHostAddObserverRemoveNode`) pass 10/10 repetitions.
- Statement coverage: `internal/raft` 91.2%, root package 88.7%.
- `internal/transport`: the non-TLS tests (chunk assembly, chunk writer,
  registry, circuit breaker, initial message, in-memory send limits) pass in
  the isolated namespace. The TLS variants cannot run: the captured tree has
  `internal/transport/tests/localhost.crt` and `test-root-ca.crt` but no
  `localhost.key`, so `TestMessageCanBeSent` and the other mutual-TLS variants
  abort with `open tests/localhost.key: no such file or directory`. This is a
  packaging limitation, not an implementation failure; the TLS handshake path
  of `internal/transport/tcp.go` is therefore unaudited by execution.
  Because the TLS-first loops panic, the rest of the transport suite (snapshot
  sending/streaming, connection failure handling, circuit breakers) never
  ran in the captured tree. In a diagnostic copy (`audit/diag-transport/`)
  the TLS setup was first disabled to run every test on the non-TLS path
  (whole package passes, 13 s), then a fresh CA/server certificate pair was
  generated into the copy's `tests/` directory to run the mutual-TLS variants
  too (whole package passes, 14 s). The captured source was not modified.

The upstream test suite therefore does not exercise the defects below.

## Summary

| ID | Region | Defect | Evidence |
|----|--------|--------|----------|
| F1 | `nodehost.go` `(*nodeUser).ReadIndex` | Enqueues a ReadIndex request without waking the execution engine; the request is only dispatched by the next tick. Up to one RTT added latency; a one-RTT timeout deterministically returns `RequestTimeout` on a healthy cluster, while `NodeHost.ReadIndex` with the same timeout completes. | Executed (5/5 failures), latency measurement, causality check in `audit/diag`. |
| F2 | `internal/raft/raft.go` `handleCandidateReadIndex` | The dropped ReadIndex is recorded twice, so `pb.Update.DroppedReadIndexes` contains the same `SystemCtx` twice for one request. Currently idempotent downstream; the raft update is wrong. | Executed at raft level and through exported `Peer.GetUpdate`. |

Quick verification of both findings (about 3 seconds):

```
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAudit -v ./internal/raft/
# FAIL TestAuditCandidateReadIndexIsDroppedOnce, FAIL TestAuditPeerUpdateDroppedReadIndexes
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
    -run TestAuditNodeUserReadIndexOneTickTimeout -v .
# FAIL: timeout on the INodeUser path; the NodeHost control in the same test passes
```

## Finding 1 (executed): `INodeUser.ReadIndex` never wakes the execution engine

Affected code: `nodehost.go`, `(*nodeUser).ReadIndex` (around line 2063).

```go
func (nu *nodeUser) ReadIndex(timeout time.Duration) (*RequestState, error) {
	return nu.node.read(nu.nh.getTimeoutTick(timeout))
}
```

Expected behavior. `GetNodeUser` returns an `INodeUser`; its `ReadIndex` doc
says "Its semantics is the same as the ReadIndex() method in NodeHost"
(`nodehost.go:2020-2038`). `NodeHost.ReadIndex` calls
`nh.engine.setStepReady(clusterID)` after enqueueing the request
(`nodehost.go:1477-1481`), and the sibling method `(*nodeUser).Propose` does the
same via its `setStepReady` field (`nodehost.go:2056-2060`). `nodeUser` even
holds `setStepReady` for this purpose (`nodehost.go:2040-2046`,
`GetNodeUser` at `nodehost.go:1383-1398`). A queued read-index request is
dispatched by `node.handleReadIndex()` from `handleEvents`, which only runs
when the cluster is marked step-ready.

What actually happens. Without the wakeup the request sits in
`pendingReadIndexes.requests` until the next step for that cluster. In an idle
cluster the next step is the tick worker (`NodeHost.tickWorkerMain` calls
`sendTickMessage` + `setAllStepReady` once per RTT,
`nodehost.go:1849-1876`). That is up to one RTT late, and the request deadline
is measured in the same RTT ticks (`getTimeoutTick`,
`pendingReadIndex.read`). A request whose timeout is one RTT
(`timeoutTick == 1`) therefore expires exactly when the next tick dispatches
it, and is completed with `requestTimeout`.

Necessary conditions: use of the `INodeUser` API (not `NodeHost.ReadIndex`),
an otherwise idle cluster, and a timeout short enough (one RTT) that the
one-tick dispatch delay consumes it.

Executed observation (reproduction `zz_audit_nodeuser_test.go`, run in the
isolated network namespace):

```
$ go test -tags dragonboat_no_rocksdb,dragonboat_audit -count=1 -run TestAuditNodeUserReadIndexOneTickTimeout -v .
    zz_audit_nodeuser_test.go:87: NodeUser.ReadIndex did not complete within 10ms:
        completed=false dropped=false timeout=true rejected=false
--- FAIL: TestAuditNodeUserReadIndexOneTickTimeout (0.18s)
```

The same test's control, `nh.ReadIndex(1, 10*time.Millisecond)`, with the
identical timeout on the same single-node cluster, completes. The failure was
observed 5/5 times in the first batch (8/8 overall).

Dispatch latency with a 20-RTT timeout, so both paths are allowed to finish
(`TestAuditNodeUserReadIndexDispatchLatency`, same file):

```
round 0: NodeHost.ReadIndex=61.318µs (completed=true) NodeUser.ReadIndex=7.203107ms (completed=true) rtt=10ms
round 1: NodeHost.ReadIndex=9.619µs  (completed=true) NodeUser.ReadIndex=10.176404ms (completed=true) rtt=10ms
round 2: NodeHost.ReadIndex=12.922µs (completed=true) NodeUser.ReadIndex=10.310302ms (completed=true) rtt=10ms
```

The extra ~one RTT is exactly the tick-driven dispatch, i.e. the missing
wakeup; it is not a scheduler artifact of the test.

Why the upstream suite misses it: `TestNodeHostNodeUserRead`
(`nodehost_test.go:2166`) uses `pto()`, a 45-RTT timeout, so the one-tick
dispatch delay is invisible and the request still completes.

Causality check (diagnostic copy, not the audited tree): a copy of the module
under `audit/diag/` with only this change applied

```go
req, err := nu.node.read(nu.nh.getTimeoutTick(timeout))
nu.setStepReady(nu.node.clusterID)
return req, err
```

passes the same test:

```
$ cd audit/diag && go test -tags dragonboat_no_rocksdb,dragonboat_audit -count=1 -run TestAuditNodeUserReadIndexOneTickTimeout -v .
--- PASS: TestAuditNodeUserReadIndexOneTickTimeout (0.22s)
```

The audited file in the work tree was not modified. Note the fix above is a
diagnostic; the defect is the missing wakeup, not the exact wording of a patch.
The diagnostic copy passed the same test 5/5 times; the unmodified tree failed
8/8 times across the runs recorded above.

## Finding 2 (executed, minor): a candidate records a dropped ReadIndex twice

Affected code: `internal/raft/raft.go`, `(*raft).handleCandidateReadIndex`
(around line 1998).

```go
func (r *raft) handleCandidateReadIndex(m pb.Message) {
	plog.Warningf("%s dropped read index, no leader", r.describe())
	r.reportDroppedReadIndex(m)          // records ctx and publishes event
	ctx := pb.SystemCtx{Low: m.Hint, High: m.HintHigh}
	r.droppedReadIndexes = append(r.droppedReadIndexes, ctx) // records it again
}
```

Expected behavior. Each dropped request is reported once, as in the analogous
proposal path (`handleCandidatePropose` -> `reportDroppedProposal`) and the
follower/candidate request paths in general; `Update.DroppedReadIndexes` is the
list of dropped requests handed to the node layer.

What actually happens. One `ReadIndex` message delivered to a candidate
produces two identical `SystemCtx` entries in `r.droppedReadIndexes`, so every
`pb.Update` published for that step carries the request twice
(`Peer.getUpdate` copies the slice verbatim). The event/metric is published
once (`reportDroppedReadIndex`), so this is not double event reporting. The
node layer (`node.processDroppedReadIndexes` -> `pendingReadIndex.dropped`)
deletes the batch on the first call, so the duplicate is currently idempotent
there and clients are not notified twice; the observable defect is the
duplicated record in the raft update, i.e. the update does not represent the
one-dropped-request-per-message contract that the rest of the code follows.

Executed observation (reproduction `internal/raft/zz_audit_repro_test.go`):

```
$ go test -tags dragonboat_no_rocksdb,dragonboat_audit -count=1 -run TestAudit -v ./internal/raft/
    zz_audit_repro_test.go:29: one dropped ReadIndex request produced 2 records:
        [{Low:4660 High:22136} {Low:4660 High:22136}]
--- FAIL: TestAuditCandidateReadIndexIsDroppedOnce
--- PASS: TestAuditCandidateProposalIsDroppedOnce
    zz_audit_repro_test.go:76: one dropped ReadIndex produced 2 records in pb.Update:
        [{Low:11 High:22} {Low:11 High:22}]
--- FAIL: TestAuditPeerUpdateDroppedReadIndexes
```

`TestAuditPeerUpdateDroppedReadIndexes` goes through `raft.Launch` and the
exported `Peer.GetUpdate` API, so the duplicate is visible at the package
boundary (a candidate is reached by ticking, and the bootstrap entries are
marked applied first so the node is allowed to campaign).

This function has 0.0% statement coverage in the upstream test suite, which is
consistent with the defect surviving it.

## Source-based observations not reported as defects

- `raftpb.Update.HasUpdate()` (`raftpb/raft.go:112`) ignores
  `DroppedReadIndexes`. It is not used by production code in this tree
  (`Peer.HasUpdate` in `internal/raft/peer.go` does check the field), so no
  behavior is affected here; it is an API inconsistency only if a consumer
  reads `pb.Update` directly.
- `internal/transport/chunk.go:228-238` shadows `from`/`want` with identical
  values in the "chunk from another sender" check. Cosmetic; the branch
  behaves correctly.
- `pendingReadIndex.read` does not return the pooled `RequestState` to the pool
  when the queue is full or closed. Resource hygiene only, no correctness
  effect.

## Areas reviewed without finding a defect

- `internal/raft`: quorum (`quorum`, `tryCommit`/`sortMatchValues`,
  `leaderHasQuorum`), vote handling (`canGrantVote`, `upToDate`,
  `handleVoteResp`, `handleCandidateRequestVoteResp`), log matching
  (`matchTerm`, `getConflictIndex`, `tryAppend`, `commitTo`, `tryCommit`),
  in-memory log (`inMemory.merge`, `savedLogTo`, `appliedLogTo`,
  `entriesToSave`), flow control (`remote.go`), ReadIndex
  (`readindex.go`, leader/follower handlers), snapshot restore,
  leader transfer, membership change bookkeeping, witness/observer handlers.
- `internal/raft` in-memory log: a randomised model check
  (`TestAuditInMemoryLogModel`, 5 seeds x 400 rounds x 200 mixed
  append/overwrite/save/apply/snapshot-restore operations) matched a simple
  reference model on `markerIndex`, retained entries, `savedTo`,
  `entriesToSave`, `getEntries` and snapshot state after every operation. No
  divergence. (The harness only rewrites entries at or after `markerIndex`,
  matching production: `entryLog.append` rejects rewriting committed
  entries.)
- `internal/raft` protocol: a randomised multi-node check
  (`TestAuditRaftSafetyFuzz`) runs 3-node and 5-node clusters through 3000
  ticks with 20% message loss, reordering (0-2 tick delays) and periodic
  60-tick partitions. Per seed it produces ~700 proposals and ~650 committed
  entries across ~20 leader terms, checking after every 10 ticks that (a) no
  two nodes are leader in the same term, (b) all committed entries agree on
  term and payload across nodes, and (c) per-node commit indexes never move
  backwards. After healing the network it requires a leader and a new
  committed proposal. All 20 runs pass; no safety or liveness violation.
- `internal/raft` crash safety: `TestAuditVoteSurvivesRestart` drives a node
  into candidate state, persists its `pb.State` through `Peer.GetUpdate` /
  `Peer.Commit`, relaunches it from the same LogDB, and verifies the term/vote
  are restored and that a `RequestVote` from another node in the same term is
  rejected. Passes.
- `internal/rsm`: apply pipeline, session manager/LRU sessions, membership
  change acceptance rules, state machine recovery.
- `internal/logdb`: key encoding, plain/batched entry managers, cache,
  log reader bounds, `db` state/entries/snapshot persistence, durability
  (`Sync`/`SyncDir`) plumbing, sharded save/compaction paths.
- `internal/transport`: chunk assembly (ordering, staleness, slot limits,
  sender checks, node-removed handling), chunk writer, node registry, circuit
  breaker, initial message and in-memory send-limit behaviour (executed);
  source review of `transport.go`, `tcp.go`, `job.go`, `snapshot.go`
  (TLS path only partially reviewed).
- Root package: request state machine, pending proposals/read indexes,
  snapshots (`node.doSave`/`recover`/`compact`), engine scheduling order
  (replicate before persisting, other messages after), quiesce, NodeHost
  start/join/restart paths.
- Root package read paths on a healthy two-node cluster:
  `TestAuditFollowerReadIndex` measures `NodeHost.ReadIndex` on the leader and
  on the follower with a 30-RTT timeout. Both complete; leader ~1.0-1.8 ms,
  follower ~1.8-3.7 ms (RTT 10 ms), which is consistent with forwarding the
  request to the leader and confirming via heartbeats. This also shows the
  `NodeHost.ReadIndex` dispatch is immediate, unlike the `INodeUser` path in
  Finding 1.
- Root package observer path: `TestAuditObserverReadAndPropose` adds node 3
  as an observer to a two-node cluster, starts it with
  `StartCluster(nil, true, ..., IsObserver: true)` and verifies the observer
  can make a proposal (~7.6 ms) and perform three linearizable reads
  (0.4-3.1 ms). Passes.
- Root package leadership transfer: the captured
  `TestNodeHostLeadershipTransfer` is marked "FIXME: Leadership transfer is
  not actually tested" and only requests a transfer from a node to itself (a
  no-op). `TestAuditLeaderTransfer` sets up a real two-node cluster, commits a
  proposal, requests a transfer from the current leader to the follower, waits
  for both NodeHosts to report the follower as leader, and commits another
  proposal under the new leader. Passes 5/5.
- Root package large payloads: the upstream `TestLargeProposalCanBeProposed`
  is commented out because it allocates 8 GB. `TestAuditLargeProposal`
  exercises the same path at feasible sizes (1 MB, 8 MB, 32 MB, with and
  without Snappy): every proposal commits and the state machine observes the
  exact payload length (32 MB no-compression ~289 ms, snappy ~85 ms on a
  single node). `TestAuditLargeProposalTwoNodes` repeats 8 MB and 32 MB over
  the two-NodeHost transport path (8 MB ~131 ms, 32 MB ~1.0 s). Passes.
- Remaining packages: `./tools`, `./client`, `./config` and `./raftpb` pass
  their tests; `raftio`, `logger` and `statemachine` have no test files.
  `plugin` and `plugin/tee` cannot build offline because they import the
  rocksdb bindings; `plugin/chan` has no tests.

## Reproduction inventory

- `zz_audit_nodeuser_test.go` — Finding 1 (root package test; requires
  `isolated_exec` because the NodeHost listens on a TCP port); also holds the
  dispatch-latency measurement and the follower-read check.
- `internal/raft/zz_audit_repro_test.go` — Finding 2 (three tests: raft-level
  duplicate, proposal control, and `Peer.GetUpdate` boundary) plus the
  vote-survives-restart crash check.
- `internal/raft/zz_audit_memlog_test.go` — randomised model check of
  `inMemory` (passes; kept as evidence of the negative result).
- `internal/raft/zz_audit_fuzz_test.go` — randomised 3/5-node protocol check
  with message loss, reordering and partitions (passes; negative result).
- `zz_audit_observer_test.go` — observer proposal/ReadIndex end-to-end check
  (passes; negative result).
- `zz_audit_leader_transfer_test.go` — real end-to-end leader transfer
  (passes 5/5; covers the upstream FIXME gap).
- `zz_audit_largepayload_test.go` — 1-32 MB proposals on one and two nodes,
  with and without Snappy (passes; covers the disabled-test gap).
- `audit/diag/` — copy of the module with the Finding 1 diagnostic change,
  used only to confirm causality.
- `audit/diag-transport/` — copy of the module used to run the whole
  transport suite, first with TLS disabled and then with freshly generated
  test certificates (`audit/gencert.go`), because the captured tree is
  missing `internal/transport/tests/localhost.key`.
- `audit/cover/*.cov`, `audit/cover/*.log` — coverage and test logs.
- `audit/shadowscan.go`, `audit/shadowscan2.go`, `audit/unusedparam.go`,
  `audit/unreach.go`, `audit/emptyblocks.go` — source scanners used during the
  audit.

## Command log (abridged)

Run from the work directory; `isolated_exec` was used for anything that binds a
TCP socket.

```
go build ./...                                   # only gorocksdb fails (cgo header absent)
go test -tags dragonboat_no_rocksdb -count=1 ./internal/raft ./internal/rsm \
        ./internal/logdb ./internal/server ./raftpb ./config ./client
isolated_exec: go test -tags dragonboat_no_rocksdb -count=1 .
isolated_exec: go test -race -tags dragonboat_no_rocksdb -count=1 .
isolated_exec: go test -tags dragonboat_no_rocksdb -count=3 .          # 3x green
isolated_exec: go test -tags dragonboat_no_rocksdb -count=1 ./internal/transport \
        -run 'TestMaxSlotIsEnforced|TestOutOfOrderChunk|...|TestGetMessageFromChunk'
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
        -run TestAuditNodeUserReadIndexOneTickTimeout -v .              # FAIL (F1)
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
        -run TestAuditNodeUserReadIndexDispatchLatency -v .             # latency evidence
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
        -run TestAuditFollowerReadIndex -v .                            # PASS (follower reads)
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
        -run TestAuditObserverReadAndPropose -v .                       # PASS (observer I/O)
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
        -run TestAuditLeaderTransfer -v .                               # PASS x5 (leader transfer)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAudit -v ./internal/raft/  # FAIL (F2)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditInMemoryLogModel ./internal/raft/  # PASS (model check)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditRaftSafetyFuzz ./internal/raft/     # PASS (protocol fuzz)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditVoteSurvivesRestart ./internal/raft/ # PASS (crash safety)
isolated_exec (audit/diag): same F1 command                              # PASS (causality)
```

## Unresolved work

- No executable coverage gap remains for the buildable code, except the
  rocksdb-backed packages (`internal/logdb/tee`, `plugin`, `plugin/tee`,
  `internal/logdb/kv/rocksdb/gorocksdb`), which cannot build offline.
- `tools/import.go` was reviewed read-only; no executable import/repair
  scenario was built.
- All `INodeUser`-style public entry points were checked against the wakeup
  pattern; `nodeUser.ReadIndex` is the only one missing it, but a systematic
  mutant-based sweep of the root package was not performed.
- Whether F2 manifests anywhere outside `pb.Update` consumers (for example in
  a future node-layer change that stops making `dropped()` idempotent) was not
  investigated further, since the current node layer is unaffected.
- The randomised model check covers `inMemory` directly; the composition in
  `entryLog` (with a LogDB underneath) was reviewed by hand but not model
  checked.
