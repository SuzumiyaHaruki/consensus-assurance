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
- The `dragonboat_memfs_test` build tag routes the whole NodeHost through the
  channel transport (`internal/transport/transport.go`, `create()`, via
  `plugin/chan`) and an in-memory filesystem. The complete root-package test
  suite passes under that configuration (22 s), exercising the channel
  transport end to end across clusters, snapshots, membership changes and
  restarts — including the plugin whose factory-level `Validate` is
  Finding 4.
  The audit scenarios were also re-run on that path in the fixed copy (all 16
  root audit tests pass, 7 s), so linearizability, restart endurance, replica
  convergence, leader transfer, witness elections and large payloads behave
  the same on the channel transport as on the default TCP transport.

The upstream test suite therefore does not detect the defects below.

## Summary

| ID | Region | Defect | Evidence |
|----|--------|--------|----------|
| F1 | `nodehost.go` `(*nodeUser).ReadIndex` | Enqueues a ReadIndex request without waking the execution engine; the request is only dispatched by the next tick. Up to one RTT added latency; a one-RTT timeout deterministically returns `RequestTimeout` on a healthy cluster, while `NodeHost.ReadIndex` with the same timeout completes. | Executed (5/5 failures), latency measurement, causality check in `audit/diag`. |
| F2 | `internal/raft/raft.go` `handleCandidateReadIndex` | The dropped ReadIndex is recorded twice, so `pb.Update.DroppedReadIndexes` contains the same `SystemCtx` twice for one request. Currently idempotent downstream; the raft update is wrong. | Executed at raft level and through exported `Peer.GetUpdate`. |
| F3 | `raftpb/raft.go` `(*Update).HasUpdate` | Ignores `DroppedReadIndexes`: `Peer.HasUpdate` reports an update for a node whose only pending work is a dropped read index, while `Update.HasUpdate()` returns false for the very same update. No production caller of `Update.HasUpdate` exists in this tree. | Executed (`TestAuditUpdateHasUpdateWithDroppedReadIndexes`). |
| F4 | `plugin/chan/chan.go` `ChanTransportFactory.Validate` | The exported channel transport factory panics from `Validate`, but `NodeHostConfig.Validate` calls the transport factory's `Validate` for `RaftAddress`; `NewNodeHost` with this factory therefore panics before anything can start. The plugin is documented as test-purpose, and upstream tests avoid it by defining their own factory with a real `Validate`. | Executed (`TestAuditChanTransportFactoryIsUsable`). |
| F5 | `logger/logger.go` `getILogger` | The logger cache is keyed by package name only. Calling `GetMonkeyLogger(pkg)` first makes a later `GetLogger(pkg)` return that same monkey-mode logger, which suppresses all output for the package outside monkey builds. `GetMonkeyLogger` has no in-tree caller, so reachability is limited to external users of the monkey API. | Executed (`TestAuditMonkeyLoggerCache`). |
| F6 | `raftpb/raft_optimized.go` `messageCount` | The batch pre-sizing helper parses field headers from untrusted network data without the overflow/bounds checks the main parser performs. A crafted varint yields a negative length, then a negative index, and an index-out-of-range panic inside `MessageBatch.Unmarshal`; it is reached from `transport.(*TCP).serveConn` with no recover, crashing the NodeHost process. | Executed: unit reproduction plus a live NodeHost crash from a 15-byte frame (`audit/tools/e2ecrash`). |
| F7 | `internal/rsm/rwv.go` `getHeaderFromFirstChunk` | Panics ("first chunk is too small") when a streamed snapshot's first chunk is shorter than the 1024-byte header. Reached from `transport.Chunk.Add` on the network receive goroutine, so a malformed snapshot chunk crashes the NodeHost. | Executed (`TestAuditShortFirstChunkDoesNotPanic`). |
| F8 | `internal/transport/chunk.go` `Chunk.addLocked` | A first chunk that sets `HasFileInfo` skips the snapshot validator; with a non-zero `FileChunkId` it is appended to a file that does not exist yet, and the save error is turned into `panicNow`, crashing the NodeHost on peer-supplied data. | Executed (`TestAuditChunkWithUnexpectedFileChunkIDDoesNotPanic`). |
| F9 | `nodehost.go` `(*messageHandler).HandleMessageBatch` | Panics ("to field not set") on a peer-supplied message whose `To` field is zero. The transport only checks deployment ID and bin version (both guessable) before handing the batch over, so a crafted batch crashes the NodeHost. | Executed (`TestAuditMessageWithoutDestinationDoesNotPanic`). |
| F10 | `internal/raft/raft.go` `handleReplicateMessage` / `internal/raft/logentry.go` `tryAppend` | A `Replicate` message's `Entries[i].Index` is never checked against `LogIndex+1+i`. A peer entry that claims an index at or below `committed` (with the anchor term guessed correctly) makes `tryAppend` call `plog.Panicf("entry %d conflicts with committed entry")`; non-contiguous indices instead install a log hole and panic later in `getEntries`/`entriesToApply`. A live three-node cluster dies on the exec-engine step worker from 480 forged TCP batches. | Executed: raft-level tests plus a live NodeHost crash (`audit/tools/e2ereplicate`). |
| F11 | `internal/raft/raft.go` `handleHeartbeatMessage` | Passes the peer-supplied `Commit` straight to `entryLog.commitTo`, which panics when it exceeds `lastIndex()`. The Replicate handler clamps with `min(lastIdx, m.Commit)`; the heartbeat handler does not. One forged `Heartbeat` (no anchor or log-term matching needed) kills a live cluster member. | Executed: raft-level tests plus one forged TCP frame against a live cluster (`audit/tools/e2ereplicate heartbeat`). |
| F12 | `nodehost.go` `(*messageHandler).HandleMessageBatch` | Accepts every message type from the transport and queues it for the raft peer. Types that only the local node may originate (`Election`, `LeaderHeartbeat`, `CheckQuorum`, `BatchedReadIndex`) reach `Peer.Handle`, whose programming-error guard is `panic("local message sent to Step")`. One forged frame with `Type: Election` kills a live cluster member; a wire `LocalTick` would instead drive the node's clock. | Executed: one forged TCP frame against a live cluster (`audit/tools/e2ereplicate localmsg`). |

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
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditMonkeyLoggerCache -v ./logger/
# FAIL: GetLogger returns the monkey-mode logger cached for the same package
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditMalformedMessageBatchDoesNotPanic -v ./raftpb/
# FAIL: MessageBatch.Unmarshal panics with a negative index on a crafted batch
isolated_exec: go run ./audit/tools/e2ecrash
# panics: a live NodeHost is killed by a 15-byte frame
```

Overall assessment: five concrete defects were found — one user-visible (F1,
the `INodeUser` read path) and four local/API-level (F2 in the raft update,
F3 in `raftpb`, F4 in the channel transport plugin, F5 in the logger cache).
Beyond those, the consensus core held up under a randomised 3/5-node protocol
fuzz with loss, reordering and partitions (six safety invariants), a
randomised model check of the in-memory log, crash-restart vote safety,
replica convergence, linearizability under concurrency, leader transfer,
witness elections and a property test of the entry codec; the full buildable
test matrix (including the transport suite with TLS in a diagnostic copy, and
the memfs/channel-transport build) and the race detector are green. The four
minimal fixes listed under "Fix verification" resolve every reproduction
without breaking the upstream suites.

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
custom factory is unaffected. The module's own internal use of the factory
(`internal/transport/transport.go`, `create()`, selected when
`invariants.MemfsTest` is on) does not hit the panic because
`NodeHostConfig.Expert.TransportFactory` is nil in that path, so the validator
falls back to `stringutil.IsValidAddress`.

## Finding 5 (executed, minor): the logger cache ignores the monkey flag

`logger.GetLogger` and `logger.GetMonkeyLogger` share a cache keyed only by
package name (`logger/logger.go`, `getILogger`). `GetMonkeyLogger` creates a
`dragonboatLogger{monkeyLogger: true}`, and `get()` returns a null logger for
such loggers whenever `invariants.MonkeyTest` is false. A later
`GetLogger(pkg)` therefore returns that same monkey logger and all logging for
`pkg` is silently dropped in a normal build:

```
$ go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditMonkeyLoggerCache -v ./logger/
    zz_audit_cache_test.go:24: GetLogger("audit-pkg") returned the monkey-mode
        logger created by the earlier GetMonkeyLogger call
--- FAIL: TestAuditMonkeyLoggerCache
```

Expected behaviour: `GetLogger(pkg)` returns a normal logger for `pkg`
regardless of whether `GetMonkeyLogger(pkg)` was requested earlier (for
example by keying the cache on `(pkgName, monkey)`). The defect is latent:
`GetMonkeyLogger` has no caller in this tree, so only external users of the
monkey-test API can trigger it.

## Finding 6 (executed): a malformed network frame crashes the NodeHost

`MessageBatch.Unmarshal` and `Message.Unmarshal` (`raftpb/raft_optimized.go`)
pre-size their repeated fields with `messageCount` and `entryCount`, both of
which re-parse field headers without the checks the main parser performs (no
`shift >= 64` guard, no `msglen < 0` check, no bounds check on `postIndex`). A
10-byte varint whose top bit lands in the sign position makes `msglen`
negative, then `iNdEx` negative, and the next loop iteration indexes the
buffer with a negative index:

```
$ go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditMalformedMessageBatchDoesNotPanic -v ./raftpb/
    MessageBatch.Unmarshal panicked on malformed input:
        runtime error: index out of range [-9223372036854775797]
--- FAIL: TestAuditMalformedMessageBatchDoesNotPanic
```

The `Message`-level helper (`entryCount`, repeated `Entries` field) has the
same defect and is triggered by the analogous 13-byte payload:

```
    Message.Unmarshal panicked on malformed input:
        runtime error: index out of range [-9223372036854775797]
--- FAIL: TestAuditMalformedMessageEntriesDoNotPanic
```

This is reachable from the network. `internal/transport/tcp.go`'s `serveConn`
reads a frame (magic number, header with CRC, payload with CRC), then calls
`batch.Unmarshal(buf)` with no recover (`tcp.go:560-566`); the magic number
and CRC are not secrets, and the deployment-ID/bin-version checks happen only
after unmarshalling. A 15-byte frame sent to a running NodeHost crashes the
whole process:

```
$ go run ./audit/tools/e2ecrash
panic: runtime error: index out of range [-9223372036854775797]
  raftpb.(*MessageBatch).messageCount(...)  raft_optimized.go:1022
  raftpb.(*MessageBatch).Unmarshal(...)     raft_optimized.go:1107
  internal/transport.(*TCP).serveConn(...)
```

Expected behaviour: malformed input is rejected with an error, as the main
parser already does for a negative length ("proto: negative length found
during unmarshaling"). Adding the same guards to both helpers in the fix
verification copy makes both unit reproductions pass with that error. Severity:
availability only (no log or state corruption), but any peer that can reach
the Raft port can kill the process in the default (non-TLS) configuration.

## Finding 7 (executed): a short snapshot chunk crashes the receiver

`getHeaderFromFirstChunk` (`internal/rsm/rwv.go`) panics when the first chunk
of a streamed snapshot is shorter than the 1024-byte header. The snapshot
validator runs inline on the transport's receive path:
`transport.(*TCP).serveConn` -> `chunk.Unmarshal` -> chunk handler
(`chunks.Add`, wired at `internal/transport/transport.go:229`) ->
`Chunk.addLocked` (`chunk.go:212`) -> `SnapshotValidator.AddChunk` ->
`getHeaderFromFirstChunk`, so a malformed chunk from a peer crashes the
process in the same way as Finding 6:

```
$ go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditShortFirstChunkDoesNotPanic -v ./internal/transport/
    Chunk.Add panicked on a short first chunk: first chunk is too small
--- FAIL: TestAuditShortFirstChunkDoesNotPanic
```

Expected behaviour: reject the chunk (as the validator does for other bad
input) instead of panicking; returning `(nil, nil, false)` in the fix
verification copy makes the reproduction pass and `Chunk.Add` returns false.

## Finding 8 (executed, minor): a forged chunk skips validation and panics on save

`Chunk.addLocked` (`internal/transport/chunk.go`) treats any `save` error as
fatal (`panicNow`). A peer can reach that path without passing the snapshot
validator by setting `HasFileInfo` on the first chunk (`record` only validates
`!chunk.HasFileInfo`). With a non-zero `FileChunkId` the chunk is written with
`OpenChunkFileForAppend` although no file has been created, so the save fails
and the error is turned into a panic:

```
    Chunk.Add panicked on a chunk with an unexpected file chunk id:
        failed to save chunk 0:0:0: open .../snapshot-0000000000000001.gbsnap:
        no such file or directory
--- FAIL: TestAuditChunkWithUnexpectedFileChunkIDDoesNotPanic
```

As with F6/F7 this is a peer-triggered process crash (availability only).
Rejecting the chunk (log + `return false`) in the fix verification copy makes
both chunk reproductions pass.

### Common pattern across F6-F12

All three are on the transport receive path, which handles peer-supplied bytes
with `panic` instead of returning an error:

| Site | Trigger | Result |
|------|---------|--------|
| `raftpb` `messageCount` / `entryCount` | crafted varint length | negative index panic in `Unmarshal` |
| `internal/rsm` `getHeaderFromFirstChunk` | first chunk < 1024 bytes | "first chunk is too small" panic |
| `internal/transport` `Chunk.addLocked` | `HasFileInfo` + non-zero `FileChunkId` | `panicNow` on the save error |

In all three cases the frame itself is valid (magic number and CRCs are not
secrets), so any peer able to reach the Raft port can terminate the NodeHost in
the default non-TLS configuration. The minimal fixes (bounds/overflow checks;
return `false` on malformed input; do not convert chunk-save errors into
panics) are in the fix-verification copy and make the reproductions pass.
F9, F10 and F11 extend the same list one and two layers up - a zero `To` field
in the message handler, entry indexes that do not follow the Replicate anchor,
and a heartbeat `Commit` beyond the end of the log - with the same cause (peer
input answered by `panic`) and the same effect (process termination).
F12 is the same statement about message *types*: the transport boundary does
not restrict which kinds of message a peer may inject.
Related, source-only robustness notes that were not reproduced: `Chunk.locks`
grows per distinct peer-supplied `(cluster, node, index)` key without
eviction, and `transport.handleRequest` feeds peer-supplied
`SourceAddress`/node IDs into the node registry, both of which can grow memory
under forged traffic.

## Finding 9 (executed): a peer message with no destination crashes the NodeHost

`(*messageHandler).HandleMessageBatch` (`nodehost.go`) panics when a request in
an incoming batch has `To == 0`:

```go
	for _, req := range msg.Requests {
		if req.To == 0 {
			plog.Panicf("to field not set, %s", req.Type)
		}
```

`transport.handleRequest` only checks the deployment ID and bin version (both
public/guessable in the default configuration) before calling the handler, so
a crafted batch containing one message with no destination kills the process:

```
    HandleMessageBatch panicked on a peer message with To == 0:
        to field not set, Heartbeat
--- FAIL: TestAuditMessageWithoutDestinationDoesNotPanic
```

Logging a warning and skipping the message in the fix verification copy makes
the reproduction pass. This is the same class as F6-F11: peer input reaching a
`panic` on the transport receive path.

## Finding 10 (executed): a forged `Replicate` kills the node from the raft layer

`handleReplicateMessage` (`internal/raft/raft.go:1354`) validates only the
anchor, `m.LogIndex`/`m.LogTerm`, and then hands the raw entry slice to
`r.log.tryAppend(m.LogIndex, m.Entries)`. Nothing checks that
`Entries[i].Index == LogIndex+1+i`, and `entryLog` lives up to its own
invariants with `plog.Panicf`:

```go
// internal/raft/logentry.go:290
conflictIndex := l.getConflictIndex(ents)
if conflictIndex != 0 {
	if conflictIndex <= l.committed {
		plog.Panicf("entry %d conflicts with committed entry, committed %d",
			conflictIndex, l.committed)
	}
```

Two concrete consequences of the missing check:

1. An entry that claims an index at or below `committed` with a different term
   makes `tryAppend` panic on the conflict with the committed region - the
   region Raft promises never to rewrite.
2. Non-contiguous indices are accepted outright: `lastIdx` is computed as
   `m.LogIndex + len(m.Entries)`, not from the entries, and
   `checkEntriesToAppend` only validates the seam with the first appended
   entry. A `Replicate` with `LogIndex=3` and entries at 4 and 9 leaves the log
   holding indices 1,2,3,4,9 with `committed=5`; the next apply attempt panics
   in `inMemory.getEntries` ("invalid high value 10, upperBound 6"), or in
   `(*node).entriesToApply` ("has hole in to be applied logs") a layer up.

Reachability is the same chain as F9: `transport.handleRequest` checks only
the deployment ID and bin version (defaults 1 and 210, both guessable),
`HandleMessageBatch` checks `To`/`ClusterId`, `Peer.Handle` accepts a
`Replicate` whose `From` is any known member, and the exec engine recovers
panics only when error injection is enabled (`engine.go:1035`), so the panic
on the step worker terminates the process. No knowledge beyond small integers
is needed: the attacker brute-forces `LogIndex` and `LogTerm`; the anchor term
has to match the term of a committed entry, which the harness hits within 480
frames.

Raft-level reproductions (`internal/raft/zz_audit_forgedreplicate_test.go`):

```
--- FAIL: TestAuditForgedReplicateCannotPanicOnCommittedConflict
    forged Replicate panicked: entry 1 conflicts with committed entry, committed 2
--- FAIL: TestAuditForgedReplicateCannotCreateLogHole
    forged Replicate installed an unreadable log: invalid high value 10, upperBound 6
--- PASS: TestAuditWellFormedReplicateStillAccepted
```

Live reproduction (`audit/tools/e2ereplicate`, run through `isolated_exec`):
three real NodeHosts on 127.0.0.1:26991-26993 form cluster 128, two proposals
commit, and 480 forged `Replicate` batches are written to node 2's Raft
address. The captured tree dies with:

```
panic: entry 4 conflicts with committed entry, committed 5
  internal/raft.(*entryLog).tryAppend          logentry.go:294
  internal/raft.(*raft).handleReplicateMessage raft.go:1365
  internal/raft.(*raft).handleFollowerReplicate raft.go:1927
  internal/raft.(*Peer).Handle                 peer.go:195
  dragonboat.(*node).handleReceivedMessages   node.go:1286
  dragonboat.(*engine).stepWorkerMain         engine.go:1240
```

The full log is `audit/cover/f10/e2e_stderr.txt`. The fix rejects a
`Replicate` whose entries do not directly follow the anchor with the same
`ReplicateResp{Reject: true}` shape the follower already uses for a log
mismatch; the leader then backs off normally. With it the three raft tests
pass, the upstream `TestHandleMTReplicate` table still passes, and the same
480-batch attack leaves the live cluster running
(`NODEHOSTS SURVIVED THE FORGED REPLICATE BATCHES`).

## Finding 11 (executed): one forged `Heartbeat` kills a follower

`handleHeartbeatMessage` (`internal/raft/raft.go:1316`) is three lines:

```go
func (r *raft) handleHeartbeatMessage(m pb.Message) {
	r.log.commitTo(m.Commit)
```

`entryLog.commitTo` panics when the requested index is beyond the end of the
log ("invalid commitTo index %d, lastIndex() %d"). The Replicate handler a few
lines below clamps (`commitTo(min(lastIdx, m.Commit))`), and the leader's own
`sendHeartbeatMessage` clamps to its believed match index, but the follower
applies the received value unchecked. A `Heartbeat` needs no anchor index and
no matching log term - only `Term >= r.term` and a known `From` - so a single
frame with a huge `Commit` is enough:

```
--- FAIL: TestAuditForgedHeartbeatCannotPanic
    forged Heartbeat panicked: invalid commitTo index 1000000, lastIndex() 3
--- PASS: TestAuditHeartbeatStillCommits
```

Live reproduction, one frame to node 2 of the three-node cluster
(`audit/tools/e2ereplicate heartbeat`):

```
panic: invalid commitTo index 1099511627776, lastIndex() 5
  internal/raft.(*entryLog).commitTo             logentry.go:328
  internal/raft.(*raft).handleHeartbeatMessage   raft.go:1317
  internal/raft.(*raft).handleFollowerHeartbeat  raft.go:1933
  internal/raft.(*Peer).Handle                   peer.go:195
  dragonboat.(*node).handleReceivedMessages      node.go:1286
  dragonboat.(*engine).stepWorkerMain            engine.go:1240
```

Full log: `audit/cover/f11/e2e_heartbeat_stderr.txt`. The fix clamps in the
handler (`commitTo(min(m.Commit, r.log.lastIndex()))`), matching the Replicate
path and etcd's `commitTo(min(m.Commit, lastnewi))`; the two new tests and the
upstream `TestHandleHeartbeat` table pass, the full fixed raft suite is green,
and the same single frame now leaves the cluster running
(`NODEHOSTS SURVIVED THE FORGED HEARTBEAT BATCH`).

This is the cheapest member-kill found: one small batch, no guessed term or
index. It also covers a benign-looking failure mode - a leader whose belief
about a follower's match index is ahead of that follower's actual log (for
example after the follower restarts from older storage) sends an ordinary
heartbeat whose `Commit` is too large, and the follower dies on it.

## Finding 12 (executed): a peer can deliver local-only message types

`HandleMessageBatch` inspects `To` and `ClusterId` and then queues the message
for the node. Message types that only the local node is allowed to originate
are not filtered, so a frame with `Type: Election` goes through
`node.handleReceivedMessages` into `Peer.Handle`, whose first statement is a
programming-error assertion:

```go
// internal/raft/peer.go:185
func (p *Peer) Handle(m pb.Message) {
	if IsLocalMessageType(m.Type) {
		panic("local message sent to Step")
	}
```

One forged frame to node 2 of the live three-node cluster
(`audit/tools/e2ereplicate localmsg`):

```
panic: local message sent to Step
  internal/raft.(*Peer).Handle              peer.go:187
  dragonboat.(*node).handleReceivedMessages node.go:1286
  dragonboat.(*engine).stepWorkerMain       engine.go:1240
```

Full log: `audit/cover/f12/e2e_localmsg_stderr.txt`. The same gap covers
`LeaderHeartbeat`, `CheckQuorum` and `BatchedReadIndex`; `LocalTick` is
intercepted by `node.handleMessage` instead, which means a wire `LocalTick`
currently *advances the raft clock* (elections and heartbeats fire early or
late at a peer's choosing) rather than being ignored.

The fix filters local message types at the transport boundary, next to the
existing `To` check; the same frame leaves the cluster running
(`NODEHOSTS SURVIVED THE FORGED LOCAL-TYPE MESSAGE`). With it, type,
destination, term, log index and commit index are all checked before they
reach raft state.

## Source-based observations not reported as defects

- `internal/transport/chunk.go:228-238` shadows `from`/`want` with identical
  values in the "chunk from another sender" check. Cosmetic; the branch
  behaves correctly.
- `pendingReadIndex.read` does not return the pooled `RequestState` to the pool
  when the queue is full or closed. Resource hygiene only, no correctness
  effect.
- `internal/settings/overwrite.go` defines `logHardChange` as an empty
  function; the caller logs the setting change with `plog.Infof` first, so no
  information is lost. Dead code only. The same file converts JSON numbers to
  `uint64` with `uint64(val.(float64))`, so a negative value in
  `dragonboat-soft-settings.json` wraps to a huge value; that file is
  documented as expert-only and the behaviour was not reproduced as a defect.
- Observer promotion validates the target: the `RequestAddNode` doc says the
  target "is ignored when promoting an observer", but `node.requestConfigChange`
  validates it first, so an empty target returns `ErrInvalidAddress` before the
  promotion is attempted. Passing the observer's real address works (verified).
  Documented wording vs. validation-order nuance, not reported as a defect.
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
- Root package observer promotion: `TestAuditObserverPromotion` adds node 3 as
  an observer to a two-node cluster, promotes it with `RequestAddNode`, and
  verifies the membership becomes nodes {1,2,3} with no observers. It then
  stops the old leader (node 1) and requires the surviving regular node plus
  the promoted node to elect a new leader and commit a proposal — i.e. the
  promoted node really votes. Promotion had no NodeHost-level test upstream
  (only raft/rsm unit tests). Passes 5/5.
- Root package membership rejections: `TestAuditMembershipRejections` builds a
  two-voter + one-witness cluster and submits `RequestAddNode` for the witness
  and `RequestAddWitness` for a voter. Both requests complete with
  `Rejected()`, the membership is unchanged (node 3 stays a witness, node 1
  stays a voter) and the cluster still commits a proposal. This verifies the
  rejections happen in the state machine rather than reaching the raft layer,
  where promoting a witness panics. Passes 5/5.
- Root package leader self-removal: `TestAuditLeaderSelfRemoval` has the leader
  of a two-node cluster delete itself. The removal completes, the surviving
  node becomes the leader of the remaining single-node cluster and commits a
  new proposal, and the removed node drops the cluster from its NodeHost
  (`GetLeaderID` then returns `ErrClusterNotFound`). Passes 5/5.
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
- `zz_audit_promotion_test.go` — observer→voter promotion with a leadership
  failover that needs the promoted node's vote (passes 5/5; negative result).
- `zz_audit_membership_reject_test.go` — witness↔voter conversion attempts are
  rejected cleanly and leave membership intact (passes 5/5; negative result).
- `zz_audit_selfremove_test.go` — leader removes itself; survivor becomes a
  working single-node cluster and the removed node drops the cluster (passes
  5/5; negative result).
- `zz_audit_chantransport_test.go` — exported `ChanTransportFactory` cannot
  be used to create a NodeHost (F4 reproduction).
- `logger/zz_audit_cache_test.go` — logger cache ignores the monkey flag
  (F5 reproduction).
- `raftpb/zz_audit_batch_parse_test.go` — malformed `MessageBatch` panics in
  the parser (F6 reproduction).
- `audit/tools/e2ecrash/main.go` — standalone client that kills a live
  NodeHost with a 15-byte frame (F6 end-to-end evidence).
- `internal/transport/zz_audit_chunk_parse_test.go` — short first snapshot
  chunk panics the receiver (F7) and a forged `HasFileInfo` chunk panics on
  save (F8).
- `zz_audit_msgdest_test.go` — peer message with `To == 0` panics the
  message handler (F9).
- `internal/raft/zz_audit_forgedreplicate_test.go` — a forged `Replicate`
  panics on a committed-index conflict (F10) and one with a hole in the entry
  indexes leaves an unreadable log; the well-formed control still commits.
  Logs: `audit/cover/f10/raft_tests.log` and `audit/cover/raft_matrix_f10.txt`.
- `internal/raft/zz_audit_forgedheartbeat_test.go` — a forged `Heartbeat`
  with an out-of-range `Commit` panics in `commitTo` (F11); the in-range
  control still commits and answers. Log: `audit/cover/f11/raft_tests.log`,
  matrix: `audit/cover/raft_matrix_f11.txt`.
- `audit/tools/e2ereplicate/main.go` — standalone harness that forms a real
  three-node cluster, commits a proposal and writes 480 forged `Replicate`
  batches to a follower's Raft port; the captured tree dies
  (`audit/cover/f10/e2e_stderr.txt`), the fixed copy survives. With the
  `heartbeat` argument it sends a single forged `Heartbeat` instead (F11);
  the captured tree dies (`audit/cover/f11/e2e_heartbeat_stderr.txt`) and the
  fixed copy survives. The `localmsg` argument sends one frame of type
  `Election` instead (F12): captured tree dies
  (`audit/cover/f12/e2e_localmsg_stderr.txt`), fixed copy survives.
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
  `gencert`), plus the two live-process harnesses `e2ecrash` (F6) and
  `e2ereplicate` (F10). Each lives in its own package so `go build ./...` and
  `go vet ./...` stay clean; `audit/diag*` are separate modules and are
  excluded from the main module by their own `go.mod`.

## Fix verification

A diagnostic copy `audit/diag-fixes/` applies a minimal fix for each finding:

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

// F5, logger/logger.go: key the cache on (pkgName, monkey)
	key := pkgName
	if monkey {
		key = pkgName + "-monkey"
	}

// F6, raftpb/raft_optimized.go messageCount: add the main parser's guards
	if shift >= 64 || iNdEx >= l { return count }
	...
	if msglen < 0 { return count }
	postIndex := iNdEx + msglen
	if postIndex > l { return count }
	// same guards applied to Message.entryCount

// F7, internal/rsm/rwv.go getHeaderFromFirstChunk
	if uint64(len(data)) < HeaderSize {
		return nil, nil, false
	}

// F8, internal/transport/chunk.go addLocked: reject instead of panicNow
	if err := c.save(chunk); err != nil {
		plog.Errorf("failed to save chunk %s, %v", key, err)
		c.removeTempDir(chunk)
		return false
	}

// F9, nodehost.go HandleMessageBatch: skip malformed requests
	if req.To == 0 {
		plog.Warningf("to field not set, %s", req.Type)
		continue
	}

// F10, internal/raft/raft.go handleReplicateMessage: reject a Replicate whose
// entries do not directly follow the anchor
	if !entriesFollowLogIndex(m.LogIndex, m.Entries) {
		resp.Reject = true
		resp.LogIndex = m.LogIndex
		resp.Hint = r.log.lastIndex()
		r.send(resp)
		return
	}

// F11, internal/raft/raft.go handleHeartbeatMessage: clamp like Replicate does
	r.log.commitTo(min(m.Commit, r.log.lastIndex()))

// F12, nodehost.go HandleMessageBatch: drop message types a peer may not send
	if raft.IsLocalMessageType(req.Type) {
		plog.Warningf("ignored local message type %s from the transport", req.Type)
		continue
	}
```

With those changes every audit-tagged test passes (F1 one-tick timeout,
both F2 reproductions, F3, F4, F10's two reproductions and still accepts a
well formed Replicate, plus the negative-result tests: protocol fuzz,
in-memory model, vote-restart, entry encoding, large payloads, follower and
observer reads, leader transfer, dropped-read-index idempotence, restart
endurance, linearizability, multi-cluster isolation, replica convergence and
witness elections). The default suites (`internal/raft`, `raftpb`, root
package) also still pass. The audited work tree itself is unchanged.

The end-to-end harness was run against both trees: the captured code dies on
the 480 forged `Replicate` batches (`audit/cover/f10/e2e_stderr.txt`), the
fixed copy prints `NODEHOSTS SURVIVED THE FORGED REPLICATE BATCHES` and exits
0. The `heartbeat` mode behaves the same way: captured code dies
(`audit/cover/f11/e2e_heartbeat_stderr.txt`), fixed copy prints
`NODEHOSTS SURVIVED THE FORGED HEARTBEAT BATCH`.
The `localmsg` mode sends a single `Election` frame (F12): captured code dies
(`audit/cover/f12/e2e_localmsg_stderr.txt`), fixed copy prints
`NODEHOSTS SURVIVED THE FORGED LOCAL-TYPE MESSAGE`.

The fixed copy also passes the whole audit suite under `-race`
(`internal/raft` 37.7 s, `raftpb`, `logger` and the root package 19.3 s),
using race-aware timeouts and the 8 MB cross-node payload case as described in
the observations.

Upstream-suite regression check on the fixed copy (all fixes applied, generated
TLS certs in place): root package 46.2 s, `internal/transport` (including the
mutual-TLS variants) 14.5 s, `internal/rsm` 2.8 s, `raftpb` — all pass, so the
patches do not change any behaviour the project's own tests assert.

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
isolated_exec: go test -tags 'dragonboat_memfs_test dragonboat_no_rocksdb' -count=1 .  # memfs + chan transport
isolated_exec (audit/diag-fixes): same tags plus dragonboat_audit, -run TestAudit .   # all audit tests green
isolated_exec: go test -tags dragonboat_no_rocksdb -run 'TestClusterWithoutQuorumCanBeRestoreByImportingSnapshot|TestImportedSnapshotIsAlwaysRestored|TestSnapshotCanBeExported|TestSnapshotCanBeExportedAfterSnapshotting|TestOnDiskStateMachineCanExportSnapshot' .   # all PASS (repair path)
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
go test -tags dragonboat_no_rocksdb,dragonboat_audit \
        -run 'TestAuditForgedReplicate|TestAuditWellFormedReplicate' ./internal/raft  # FAIL x2 (F10)
isolated_exec: go run -tags dragonboat_no_rocksdb ./audit/tools/e2ereplicate  # live cluster panic (F10)
isolated_exec (audit/diag-fixes): same e2e command                          # survives (F10 fix)
go test -tags dragonboat_no_rocksdb,dragonboat_audit \
        -run 'TestAuditForgedHeartbeat|TestAuditHeartbeatStillCommits' ./internal/raft  # FAIL (F11)
isolated_exec: go run -tags dragonboat_no_rocksdb ./audit/tools/e2ereplicate heartbeat  # live panic (F11)
isolated_exec (audit/diag-fixes): same heartbeat command                    # survives (F11 fix)
isolated_exec: go run -tags dragonboat_no_rocksdb ./audit/tools/e2ereplicate localmsg  # live panic (F12)
isolated_exec (audit/diag-fixes): same localmsg command                     # survives (F12 fix)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditInMemoryLogModel ./internal/raft/  # PASS (model check)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditRaftSafetyFuzz ./internal/raft/     # PASS (protocol fuzz)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditVoteSurvivesRestart ./internal/raft/ # PASS (crash safety)
go test -tags dragonboat_no_rocksdb,dragonboat_audit -run TestAuditEntryEncodingProperties ./raftpb/  # PASS (encoding)
isolated_exec (audit/diag): same F1 command                              # PASS (causality)
```

Final audit-tagged run summary:

```
root package (20): PASS DroppedReadIndexIsIdempotent, LargeProposal,
               LargeProposalTwoNodes, LeaderTransfer, LinearizableReadUnderConcurrency,
               LinearizableReadAcrossNodes, MembershipRejections, MultipleClustersOnOneNodeHost,
               NodeUserReadIndexDispatchLatency, FollowerReadIndex,
               NodeUserReadIndexTwoTickTimeout, ObserverPromotion, ObserverReadAndPropose,
               RestartEndurance, StateMachineConvergence, WitnessVotesInElection,
               LeaderSelfRemoval
               FAIL NodeUserReadIndexOneTickTimeout            (Finding 1)
               FAIL ChanTransportFactoryIsUsable               (Finding 4)
               FAIL MessageWithoutDestinationDoesNotPanic       (Finding 9)
internal/raft (12): PASS RaftSafetyFuzz, InMemoryLogModel, CandidateProposalIsDroppedOnce,
               VoteSurvivesRestart, WellFormedReplicateStillAccepted,
               HeartbeatStillCommits
               FAIL CandidateReadIndexIsDroppedOnce, PeerUpdateDroppedReadIndexes (Finding 2)
               FAIL UpdateHasUpdateWithDroppedReadIndexes      (Finding 3)
               FAIL ForgedReplicateCannotPanicOnCommittedConflict,
                    ForgedReplicateCannotCreateLogHole          (Finding 10)
               FAIL ForgedHeartbeatCannotPanic                 (Finding 11)
raftpb (3):    PASS EntryEncodingProperties
               FAIL MalformedMessageBatchDoesNotPanic          (Finding 6)
               FAIL MalformedMessageEntriesDoNotPanic           (Finding 6)
transport (2): FAIL ShortFirstChunkDoesNotPanic                 (Finding 7)
               FAIL ChunkWithUnexpectedFileChunkIDDoesNotPanic    (Finding 8)
logger (1):    FAIL MonkeyLoggerCache                             (Finding 5)
```

38 audit tests in total: 14 failing, all of them the deliberate defect
reproductions; 24 passing negative-result or characterisation tests.

Under `-race` (race-aware timeouts, 8 MB cross-node payload case) the audited
root package behaves the same: 17 PASS with only
`TestAuditNodeUserReadIndexOneTickTimeout` and
`TestAuditChanTransportFactoryIsUsable` failing, and the fixed copy
(`audit/diag-fixes/`) is fully green.

## Unresolved work

- No executable coverage gap remains for the buildable code, except the
  rocksdb-backed packages (`internal/logdb/tee`, `plugin`, `plugin/tee`,
  `internal/logdb/kv/rocksdb/gorocksdb`), which cannot build offline.
- `tools/import.go` was reviewed read-only; no executable import/repair
  scenario was built, but the upstream repair scenarios were executed
  explicitly and pass: `TestSnapshotCanBeExported`,
  `TestSnapshotCanBeExportedAfterSnapshotting`,
  `TestOnDiskStateMachineCanExportSnapshot`,
  `TestImportedSnapshotIsAlwaysRestored` and
  `TestClusterWithoutQuorumCanBeRestoreByImportingSnapshot`.
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
- F10's fix validates entries at the raft boundary, which is where the
  untrusted data enters. The `entryLog` panics themselves were left as they
  are; they are still reachable from any future internal bug that hands
  `entryLog` inconsistent entries.
