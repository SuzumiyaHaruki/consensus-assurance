# Dragonboat correctness audit

Source: `dbb02a05b62bbf7823fa3f8b5eb2ef9b949e6cc8`, module `github.com/lni/dragonboat/v3`. Audit runs against the supplied working copy; implementation and dependencies are unchanged. Added tests use the repository's existing in-memory Raft fixtures. Findings below distinguish executed local behavior from inferred API effects.

## Confirmed: batching remote ReadIndex confirmations loses earlier request contexts

**Affected code:** `internal/raft/raft.go`, `handleReadIndexLeaderConfirmation` (around lines 1771–1788), with `internal/raft/readindex.go`, `confirm`.

**Expected:** Each confirmed read must return its own request context to its originating node. The ReadIndex queue deliberately confirms earlier requests when a later request obtains a quorum; each returned `readStatus` retains its own `ctx` and `from`. Followers match read completions by the full context (`request.go`, `pendingReadIndex.addReady`).

**Conditions:** At least two reads are pending at the leader, an earlier read originated remotely, and the later heartbeat round obtains quorum before the earlier round. Concurrent follower reads and ordinary delay/loss of earlier heartbeat messages suffice. No membership change, crash, malformed message, or Byzantine behavior is needed.

**Actual:** `confirm` returns and deletes all covered statuses. The local completion branch uses `s.ctx` correctly, but the remote response branch uses `m.Hint` and `m.HintHigh` from the latest heartbeat acknowledgment for *every* status. The earlier originator receives a response with the wrong context. Because its status has already been deleted, later acknowledgments cannot recover its completion.

**Executed evidence:** `internal/raft/audit_readindex_test.go`, `TestAuditBatchedRemoteReadContexts`, sets up three Raft nodes, commits a current-term no-op through real replication messages/replies, forwards two follower read requests through normal handlers, delays the first heartbeat round, and delivers one real later heartbeat/reply (a quorum with the leader). Both the different-followers and same-follower cases fail the assertion that every confirmed request returns its own context. The log shows responses with `(202,30)` twice, no response with `(101,30)`, and zero pending leader read requests. Output: `audit/readindex-output.txt`.

**Impact:** A valid confirmed read loses its completion. Source tracing through `handleFollowerReadIndexResp`, `pendingReadIndex.addReady`, and `pendingReadIndex.applied` shows that the unmatched request cannot become ready and is left to time out. This is a read-availability defect; no stale-read or cluster safety violation is claimed. End-to-end NodeHost timeout has not been executed.

**Alternative explanations checked:** Quorum confirmation of preceding reads is intentional and safe; it is implemented explicitly in `readIndex.confirm`. Sharing the confirmed index does not justify sharing request identity. The test uses actual follower-produced heartbeat replies, not fabricated acknowledgments. The same failure occurs with two requests from one follower, so cross-node context generation is not needed.

**Reproduce from work:**

```sh
go test ./internal/raft -run '^TestAuditBatchedRemoteReadContexts$' -count=1 -v
```

Expected on captured implementation: test failure with missing context `(101,30)` in both subtests. Potential correction: populate each response from `s.ctx.Low` and `s.ctx.High`.

## Confirmed: snapshot GC can discard a newly restarted transfer using an expired transfer's identity

**Affected code:** `internal/transport/chunk.go`, `Chunk.gc` (lines 139–152), `getTracked` (165–172), and `record` (194–248).

**Expected:** An expired, abandoned snapshot transfer may be removed, but a newly accepted restart must receive a fresh inactivity window. `record` explicitly supports a new first chunk replacing an incomplete transfer and stores its current tick. GC must examine the currently tracked transfer under its per-snapshot lock.

**Conditions and schedule:** An incomplete snapshot transfer has reached its timeout. A retry of the same cluster/node/snapshot index acquires the per-snapshot mutex and is briefly descheduled before `record`. GC copies the tracked map, retaining the expired `*tracked`, and then blocks on that mutex. The retry resumes, accepts a valid first chunk, replaces the map entry with a fresh `*tracked`, and releases the mutex. GC resumes with the old pointer. It does not reread the map or check pointer identity.

**Actual:** GC uses the expired transfer's timestamp to call `removeTempDir(td.first)` and `reset(key)`. For a retry from the same sender, this deletes the freshly recreated temporary directory as well as the fresh tracking entry. Subsequent valid chunks are rejected as untracked. For a retry from another sender, the new tracking entry is still deleted even though its temporary directory differs.

**Executed evidence:** `internal/transport/audit_chunk_gc_test.go`, `TestAuditSnapshotRetrySurvivesOldGC`. The test writes a real checksummed multipart snapshot with `rsm.NewSnapshotWriter` and loads its chunks using the normal snapshot helpers. Validation stays enabled. It advances the normal logical clock to timeout and controls the scheduling gap with the existing mutex; the retry invokes `addLocked` while holding the same mutex as `Add`. A goroutine stack observation verifies that the unmodified GC is blocked at the intended lock before the retry runs. No implementation or dependency changes, clock-underflow trick, network faults, or malformed chunks are used.

The executed log reports old tick `0`, fresh tick `900`, current tick `900`, timeout `900`, and restart accepted. After GC, both fresh tracking and its temporary file are absent; valid chunk 1 is rejected and no snapshot is delivered. A control retry of the identical full snapshot without concurrent GC succeeds and delivers one snapshot. Output: `audit/chunk-gc-output.txt`.

**Impact and limits:** A valid snapshot retry is discarded immediately, delaying catch-up and requiring another transfer. This is a concrete local availability defect. The reproduction controls internal scheduling rather than running a live TCP cluster; permanent unavailability, process crash, or consensus safety loss is not claimed. A later retry is demonstrably able to recover.

**Alternative explanations checked:** The new transfer is not itself expired (its age is zero), the checksums are valid, and the same data completes successfully in the control. The single transport ticker does not prevent the race: the timestamp does not need to advance during GC; replacing the tracked pointer at the same tick is sufficient.

**Reproduce from work:**

```sh
go test ./internal/transport -run '^TestAuditSnapshotRetrySurvivesOldGC$' -count=1 -v
```

Expected on captured implementation: failure for rejection of retry chunk 1 and zero deliveries, followed by successful control delivery. Potential correction: after acquiring the snapshot lock, fetch and evaluate the current map entry, or skip collection if its identity differs from the captured entry.

## Audit status

Existing focused Raft/ReadIndex tests also passed (`audit/readindex-controls-output.txt`); their coverage did not catch the batching failure. Continuing investigation is recorded separately in `audit/notes.md`. This is a partial audit, not an assertion that other code is defect-free.
