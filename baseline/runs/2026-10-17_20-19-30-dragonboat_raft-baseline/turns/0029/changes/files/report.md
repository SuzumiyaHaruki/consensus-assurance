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

- Packages must be run one at a time. The root package and
  `internal/transport` use fixed ports (250xx/260xx) and the shared
  `singleNodeHostTestDir`; `go test ./...` with default package parallelism
  makes them collide and produces spurious failures (observed: root
  `TestGossip`, `TestNodeHostIDIsStatic`, ... and `TestMessageCanBeSent`
  failing only in the parallel run). Run sequentially, both packages pass.
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
- `internal/transport`: as captured, the suite cannot run to completion. It
  iterates `mutualTLSValues := []bool{true, false}` and the tree ships
  `internal/transport/tests/localhost.crt` but no `localhost.key`, so the
  first (TLS) iteration panics with `open tests/localhost.key: no such file or
  directory` and aborts the whole binary; every test after
  `TestMessageCanBeSent` (snapshot sending/streaming, connection failure
  handling, circuit breakers) never executes. In a diagnostic copy
  (`audit/diag-transport/`) the TLS setup was first disabled so every test ran
  on the non-TLS path (whole package passes, 13 s), then a fresh CA and
  `localhost` certificate were generated into the copy's `tests/` directory so
  the mutual-TLS variants ran too (whole package passes, 14 s; `-race` 32 s).
  The captured source was not modified.

The upstream test suite therefore does not detect the defects below.

## Summary

| ID | Region | Defect | Evidence |
|----|--------|--------|----------|
| F1 | `nodehost.go` `(*nodeUser).ReadIndex` | Enqueues a ReadIndex request without waking the execution engine; the request is only dispatched by the next tick. Up to one RTT added latency; a one-RTT timeout deterministically returns `RequestTimeout` on a healthy cluster, while `NodeHost.ReadIndex` with the same timeout completes. | Executed (5/5 failures), latency measurement, causality check in `audit/diag`. |
| F2 | `internal/raft/raft.go` `handleCandidateReadIndex` | The dropped ReadIndex is recorded twice, so `pb.Update.DroppedReadIndexes` contains the same `SystemCtx` twice for one request. Currently idempotent downstream; the raft update is wrong. | Executed at raft level and through exported `Peer.GetUpdate`. |
| F3 | `raftpb/raft.go` `(*Update).HasUpdate` | Ignores `DroppedReadIndexes`: `Peer.HasUpdate` reports an update for a node whose only pending work is a dropped read index, while `Update.HasUpdate()` returns false for the very same update. No production caller of `Update.HasUpdate` exists in this tree. | Executed (`TestAuditUpdateHasUpdateWithDroppedReadIndexes`). |
| F4 | `plugin/chan/chan.go` `ChanTransportFactory.Validate` | The exported channel transport factory panics from `Validate`, but `NodeHostConfig.Validate` calls the transport factory's `Validate` for `RaftAddress`; `NewNodeHost` with this factory therefore panics before anything can start. The plugin is documented as test-purpose, and upstream tests avoid it by defining their own factory with a real `Validate`. | Executed (`TestAuditChanTransportFactoryIsUsable`). |

Quick verification of the findings (a few seconds):

```
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAudit -v ./internal/raft/
# FAIL TestAuditCandidateReadIndexIsDroppedOnce, FAIL TestAuditPeerUpdateDroppedReadIndexes,
# FAIL TestAuditUpdateHasUpdateWithDroppedReadIndexes
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
    -run TestAuditNodeUserReadIndexOneTickTimeout -v .
# FAIL: timeout on the INodeUser path; the NodeHost control in the same test passes
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
    -run TestAuditChanTransportFactoryIsUsable -v .
# FAIL: NewNodeHost panics via ChanTransportFactory.Validate
```

Overall assessment: three concrete defects were found, one user-visible (F1,
the `INodeUser` read path) and two local/API-level (F2, F3). Beyond those, the
consensus core held up under a randomised 3/5-node protocol fuzz with loss,
reordering and partitions, a randomised model check of the in-memory log, a
crash-restart vote-safety check, and a property test of the entry codec; the
full buildable test matrix (including the transport suite with TLS in a
diagnostic copy) and the race detector are green. The three minimal fixes
listed under "Fix verification" resolve every reproduction without breaking
the upstream suites.

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

Boundary check: with the same setup, a two-RTT timeout on the `INodeUser`
path completes (`TestAuditNodeUserReadIndexTwoTickTimeout` passes), while the
one-RTT timeout times out. The failure is therefore exactly the one-tick
dispatch delay, not a general read-path failure.

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

Consequence at the node layer (executed,
`TestAuditDroppedReadIndexIsIdempotent`): feeding the same `SystemCtx`
through `pendingReadIndex.dropped` twice leaves exactly one notification on
the client's channel; the second call is a no-op because the batch was
deleted. So the duplicate does not double-complete a client request today;
the defect is the duplicated record in the raft update.

This function has 0.0% statement coverage in the upstream test suite, which is
consistent with the defect surviving it.

## Finding 3 (executed, minor): `pb.Update.HasUpdate` ignores dropped read indexes

`raftpb.Update.HasUpdate` (`raftpb/raft.go:112`) checks state, snapshot,
entries to save, committed entries, messages, ready-to-reads and dropped
entries, but not `DroppedReadIndexes`. A node whose only pending work is a
dropped read index therefore reports `Peer.HasUpdate() == true` (peer.go does
check the field) while the `pb.Update` produced for that node reports
`HasUpdate() == false`. No production code in this tree calls
`Update.HasUpdate`, so the impact is limited to API consumers, but the two
layers disagree about the same state.

Executed:

```
$ go test -tags dragonboat_no_rocksdb,dragonboat_audit \
    -run TestAuditUpdateHasUpdateWithDroppedReadIndexes -v ./internal/raft/
    zz_audit_repro_test.go:169: pb.Update.HasUpdate() reported false for an
        update carrying 2 dropped read index(es)
--- FAIL: TestAuditUpdateHasUpdateWithDroppedReadIndexes
```

The same test first asserts `Peer.HasUpdate()` is true for that state, so the
contradiction is between the two API layers, not a test artefact.

## Finding 4 (executed, minor): the exported channel transport factory cannot be used

`plugin/chan/chan.go` exports `ChanTransportFactory` implementing
`config.TransportFactory` ("a channel based module used for testing
purposes"). Its `Create` builds a working `ChanTransport`, but `Validate`
panics:

```go
func (ctm *ChanTransportFactory) Validate(addr string) bool {
	panic("not suppose to be called")
}
```

`NodeHostConfig.Validate` calls `GetRaftAddressValidator()`, which returns
`Expert.TransportFactory.Validate` when a transport factory is configured
(`config/config.go:709-714`, used at `config.go:551-554`), so simply creating
a NodeHost with this factory panics during configuration validation:

```
$ go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditChanTransportFactoryIsUsable -v .
    zz_audit_chantransport_test.go:50: NewNodeHost with the exported
        ChanTransportFactory panicked: not suppose to be called
--- FAIL: TestAuditChanTransportFactoryIsUsable
```

Expected behaviour: a `TransportFactory` shipped by the module should be
usable for the purpose it documents, or at least return `false` instead of
panicking from a validator that NodeHost invokes on user input. The upstream
tests work around this by defining their own `chanTransportFactory` whose
`Validate` accepts the test addresses (`nodehost_test.go:770-780`), which
confirms the plugin's transport itself works once wrapped. Impact is limited
to users of this test-purpose plugin; `NewChanTransport` used through a
custom factory is unaffected.

## Source-based observations not reported as defects

- `internal/transport/chunk.go:228-238` shadows `from`/`want` with identical
  values in the "chunk from another sender" check. Cosmetic; the branch
  behaves correctly.
- `pendingReadIndex.read` does not return the pooled `RequestState` to the pool
  when the queue is full or closed. Resource hygiene only, no correctness
  effect.
- Large entries vs. short election timeouts (executed, extreme configuration):
  with the race detector enabled, a 32 MB proposal between two nodes did not
  commit within 180 s, while the same proposal commits in ~1 s without the
  race detector and a 32 MB single-node proposal commits in ~4 s under
  `-race`. The logs show the follower campaigning repeatedly and dropping the
  leader's Replicate/Heartbeat messages as term-mismatched: processing a
  32 MB entry is slower than the test's election timeout (RTT 10 ms,
  ElectionRTT 10, i.e. 100-190 ms). This is a configuration/throughput
  interaction amplified ~50x by the race detector, not a logic defect; in
  production the RTT and election timeout must be scaled to the entry sizes
  used. The audit harness therefore runs only the 8 MB case across two nodes
  under `-race`.

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
  backwards, (d) a node never changes its vote within a term, and (e) a
  leader always voted for itself in its term, and (f) leader completeness: a
  leader in term T holds every entry from an earlier term that any node has
  committed. After healing the network it requires a leader and a new
  committed proposal. All 20 runs pass; no safety, election-safety,
  leader-completeness or liveness violation. (An earlier version of check (f)
  also demanded entries of the leader's own or newer terms and tripped on a
  legitimately stale leader; the final check follows the standard property.)
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
- `internal/logdb/kv`: compared the pebble and rocksdb `IKVStore`
  implementations (iteration bounds with `inc`, missing-key convention via an
  empty value, delete-range/compaction semantics) — they agree. Durability
  options are correct in both: pebble uses `WriteOptions{Sync: true}` and
  honours `WALDir`; rocksdb uses `SetUseFsync(true)`, a synced write options,
  and the WAL directory. `gorocksdb.Get` returns a nil slice with no error for
  a missing key, which matches the empty-value convention the logdb layer
  relies on.
- `raftpb` entry encoding: the colfer `Entry` encoding (used for raft log
  entries; the protobuf `MarshalTo`/`Unmarshal` for `Entry` is commented out)
  was fuzzed with 20 000 random entries covering boundary values (0, 1, 2^n,
  2^49, 2^63+1, MaxUint64) and 0-95 byte payloads. For every entry
  `Size() <= SizeUpperLimit()`, `MarshalTo` writes exactly `Size()` bytes,
  `Unmarshal` round-trips every field, and `Marshal()` produces the same
  encoding. No defect.
- `internal/transport`: chunk assembly (ordering, staleness, slot limits,
  sender checks, node-removed handling), chunk writer, node registry, circuit
  breaker, initial message and in-memory send-limit behaviour (executed);
  source review of `transport.go`, `tcp.go`, `job.go`, `snapshot.go`; the TLS
  path was executed in the diagnostic copy with generated certificates.
- `internal/transport/tcp.go`: message framing (magic number, header
  encode/decode with CRC, payload chunked read/write, CRC check skipped only
  when TLS is enabled), poison chunks, and rate-limited connection wrapper.
  Note: the header size field is used directly to size the receive buffer
  (`make([]byte, rheader.size)`), so a peer that can produce a valid header
  CRC can request a very large allocation; this is a hardening concern rather
  than a consensus defect and was not reproduced as a test.
- `internal/raft` handler map: every (state, message type) registration was
  checked against the handler names, the "must be nil" list, and the 26
  message-type constants (0-25, matching `numMessageTypes`); no mismatches.
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
- Root package witness path: the end-to-end witness election scenario was
  not covered by the upstream suite (`testWitnessIO` uses one regular node
  plus one witness, where the witness cannot provide an election vote).
  `TestAuditWitnessVotesInElection` builds a two-regular-plus-one-witness
  cluster, stops the leader's NodeHost, and requires the surviving regular
  node to be elected with the witness's vote and to commit a new proposal
  with the witness's acknowledgement. Passes 5/5.
- Root package crash/restart endurance:
  `TestAuditRestartEndurance` uses a snapshot-capable state machine on a
  single-node cluster and performs five stop/restart cycles, proposing twice
  per round and taking a snapshot every other round (snapshot indexes 4, 10,
  16). After each restart the applied count returned by `SyncRead` matches the
  number of committed proposals exactly, and proposals keep committing. This
  exercises both recovery paths: log replay (rounds without a snapshot) and
  snapshot recovery plus log replay. Passes 5/5.
- Root package linearizability under concurrency:
  `TestAuditLinearizableReadUnderConcurrency` runs 4 workers x 40
  propose-then-read iterations on a single-node cluster (160 write/read
  pairs); `TestAuditLinearizableReadAcrossNodes` runs 4 workers x 30
  iterations on a two-node cluster with proposals on one NodeHost and reads
  on the other (120 cross-node pairs). The check is the documented guarantee
  "once a write is completed, all later reads ... should return the value of
  that write or a later write": any read that starts more than 1 ms after a
  write completed must observe at least that write's counter value. No
  violation in 5/5 runs of each.
- Root package multi-cluster isolation:
  `TestAuditMultipleClustersOnOneNodeHost` runs two independent single-node
  clusters on one NodeHost, proposes 3 and 5 entries respectively, snapshots
  both, restarts the NodeHost and verifies each cluster recovers exactly its
  own count (3 and 5). This exercises per-cluster logdb sharding, snapshot
  directories and replay. Passes 5/5.
- Root package replica convergence:
  `TestAuditStateMachineConvergence` runs a three-node cluster with a
  state machine that accumulates a checksum of every applied payload. After
  40 proposals, a snapshot on node 1 and 20 more proposals, every node
  reports the same count (60) and checksum (1030). This checks that all
  replicas apply exactly the same sequence, including across snapshotting and
  log compaction. Passes 5/5.
- Root package leadership transfer: the captured
  `TestNodeHostLeadershipTransfer` is marked "FIXME: Leadership transfer is
  not actually tested" and only requests a transfer from a node to itself (a
  no-op). `TestAuditLeaderTransfer` sets up a real two-node cluster, commits a
  proposal, requests a transfer from the current leader to the follower, waits
  for both NodeHosts to report the follower as leader, and commits another
  proposal under the new leader. Passes 5/5.
  (The old leader briefly reports "no leader" after stepping down until the
  new leader's first heartbeat, so its view is polled rather than checked
  synchronously; with that, 20/20 consecutive runs pass.)
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
  dispatch-latency measurement, the one/two-RTT boundary tests and the
  follower-read check.
- `internal/raft/zz_audit_repro_test.go` — Finding 2 (three tests: raft-level
  duplicate, proposal control, and `Peer.GetUpdate` boundary) plus the
  vote-survives-restart crash check and the `Update.HasUpdate` check (F3).
- `internal/raft/zz_audit_memlog_test.go` — randomised model check of
  `inMemory` (passes; kept as evidence of the negative result).
- `internal/raft/zz_audit_fuzz_test.go` — randomised 3/5-node protocol check
  with message loss, reordering and partitions (passes; negative result).
- `zz_audit_observer_test.go` — observer proposal/ReadIndex end-to-end check
  (passes; negative result).
- `zz_audit_leader_transfer_test.go` — real end-to-end leader transfer
  (passes 5/5; covers the upstream FIXME gap).
- `zz_audit_witness_test.go` — witness election after leader loss, with a
  commit that needs the witness's ack (passes 5/5; negative result).
- `zz_audit_restart_test.go` — five stop/restart cycles with snapshots and a
  state machine that verifies applied state survives (passes 5/5; negative
  result).
- `zz_audit_linearizable_test.go` — concurrent propose/read ordering checks
  on one and two nodes (passes 5/5 each; negative result).
- `zz_audit_multicluster_test.go` — two clusters on one NodeHost across
  snapshot and restart, checking state isolation (passes 5/5; negative
  result).
- `zz_audit_convergence_test.go` — three-replica state machine convergence
  (count + payload checksum) across a snapshot (passes 5/5; negative result).
- `zz_audit_chantransport_test.go` — exported `ChanTransportFactory` cannot
  be used to create a NodeHost (F4 reproduction).
- `zz_audit_largepayload_test.go` — 1-32 MB proposals on one and two nodes,
  with and without Snappy (passes; covers the disabled-test gap).
- `zz_audit_dupdrop_test.go` — verifies the Finding 2 duplicate does not
  double-notify a client (passes; bounds the impact).
- `raftpb/zz_audit_entry_encoding_test.go` — colfer entry encoding property
  test (passes; negative result).
- `audit/diag/` — copy of the module with the Finding 1 diagnostic change,
  used only to confirm causality.
- `audit/diag-transport/` — copy of the module used to run the whole
  transport suite, first with TLS disabled and then with freshly generated
  test certificates (`audit/gencert.go`), because the captured tree is
  missing `internal/transport/tests/localhost.key`.
- `audit/diag-fixes/` — copy of the module with the three minimal fixes
  applied (see "Fix verification" below).
- `audit/cover/*.cov`, `audit/cover/*.log` — coverage and test logs.
  `audit/cover/audit_matrix.log` is the exact pass/fail matrix of the audited
  tree quoted above.
- `audit/tools/<name>/main.go` — source scanners and the certificate
  generator used during the audit (`shadowscan`, `shadowscan2`,
  `unusedparam`, `unusedfield`, `unreach`, `emptyblocks`, `siblings`,
  `gencert`). Each lives in its own package so `go build ./...` and
  `go vet ./...` stay clean; `audit/diag*` are separate modules and are
  excluded from the main module by their own `go.mod`.

## Fix verification

A diagnostic copy `audit/diag-fixes/` applies the three minimal fixes:

```go
// F1, nodehost.go
func (nu *nodeUser) ReadIndex(timeout time.Duration) (*RequestState, error) {
	req, err := nu.node.read(nu.nh.getTimeoutTick(timeout))
	nu.setStepReady(nu.node.clusterID)
	return req, err
}

// F2, internal/raft/raft.go: keep only
func (r *raft) handleCandidateReadIndex(m pb.Message) {
	plog.Warningf("%s dropped read index, no leader", r.describe())
	r.reportDroppedReadIndex(m)
}

// F3, raftpb/raft.go
... len(ud.DroppedEntries) > 0 ||
	len(ud.DroppedReadIndexes) > 0

// F4, plugin/chan/chan.go
func (ctm *ChanTransportFactory) Validate(addr string) bool {
	return len(addr) > 0
}
```

With those four changes every audit-tagged test passes (F1 one-tick timeout,
both F2 reproductions, F3, F4, plus the negative-result tests: protocol fuzz,
in-memory model, vote-restart, entry encoding, large payloads, follower and
observer reads, leader transfer, dropped-read-index idempotence, restart
endurance, linearizability, multi-cluster isolation, replica convergence and
witness elections). The default suites (`internal/raft`, `raftpb`, root
package) also still pass. The audited work tree itself is unchanged.

The fixed copy also passes the whole audit suite under `-race`
(`internal/raft`, `raftpb` and the root package), using race-aware timeouts
and the 8 MB cross-node payload case as described in the observations.

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
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
        -run TestAuditWitnessVotesInElection -v .                       # PASS x5 (witness election)
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
        -run TestAuditRestartEndurance -v .                             # PASS x5 (crash/restart)
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
        -run 'TestAuditLinearizable' -v .                               # PASS x5 (linearizability)
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
        -run TestAuditMultipleClustersOnOneNodeHost -v .                # PASS x5 (multi-cluster)
isolated_exec: go test -tags dragonboat_no_rocksdb,dragonboat_audit \
        -run TestAuditStateMachineConvergence -v .                      # PASS x5 (convergence)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAudit -v ./internal/raft/  # FAIL (F2)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditInMemoryLogModel ./internal/raft/  # PASS (model check)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditRaftSafetyFuzz ./internal/raft/     # PASS (protocol fuzz)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditVoteSurvivesRestart ./internal/raft/ # PASS (crash safety)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditEntryEncodingProperties ./raftpb/  # PASS (encoding)
isolated_exec (audit/diag): same F1 command                              # PASS (causality)
```

Final audit-tagged run summary:

```
root package (16): PASS DroppedReadIndexIsIdempotent, LargeProposal,
               LargeProposalTwoNodes, LeaderTransfer, LinearizableReadUnderConcurrency,
               LinearizableReadAcrossNodes, MultipleClustersOnOneNodeHost,
               NodeUserReadIndexDispatchLatency, FollowerReadIndex,
               NodeUserReadIndexTwoTickTimeout, ObserverReadAndPropose,
               RestartEndurance, StateMachineConvergence, WitnessVotesInElection
               FAIL NodeUserReadIndexOneTickTimeout            (Finding 1)
               FAIL ChanTransportFactoryIsUsable               (Finding 4)
internal/raft (7): PASS RaftSafetyFuzz, InMemoryLogModel, CandidateProposalIsDroppedOnce,
               VoteSurvivesRestart
               FAIL CandidateReadIndexIsDroppedOnce, PeerUpdateDroppedReadIndexes (Finding 2)
               FAIL UpdateHasUpdateWithDroppedReadIndexes      (Finding 3)
raftpb (1):    PASS EntryEncodingProperties
```

24 audit tests in total: 5 failing, all of them the deliberate defect
reproductions; 19 passing negative-result or characterisation tests.

Under `-race` (race-aware timeouts, 8 MB cross-node payload case) the audited
root package behaves the same: 13 PASS and only
`TestAuditNodeUserReadIndexOneTickTimeout` FAIL, and the fixed copy
(`audit/diag-fixes/`) is fully green.

## Unresolved work

- No executable coverage gap remains for the buildable code, except the
  rocksdb-backed packages (`internal/logdb/tee`, `plugin`, `plugin/tee`,
  `internal/logdb/kv/rocksdb/gorocksdb`), which cannot build offline.
- `tools/import.go` was reviewed read-only; no executable import/repair
  scenario was built.
- All `INodeUser`-style public entry points were checked against the wakeup
  pattern; `nodeUser.ReadIndex` is the only one missing it. A callee-set
  comparison across sibling methods (`audit/tools/siblings`) found no further
  missing-notification pattern, but a full mutant-based sweep of the root
  package was not performed.
- F2's node-layer consequence was bounded by
  `TestAuditDroppedReadIndexIsIdempotent` (one notification, not two); it was
  not explored beyond the current node implementation.
- The randomised model check covers `inMemory` directly; the composition in
  `entryLog` (with a LogDB underneath) was reviewed by hand but not model
  checked.
