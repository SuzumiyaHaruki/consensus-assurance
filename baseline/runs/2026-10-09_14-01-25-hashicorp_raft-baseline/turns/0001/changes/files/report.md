# Audit Report — hashicorp/raft (baseline, source_identity c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe)

Status: in progress (turn 2). No concrete defect confirmed yet.

## 1. Target and identity

- Audited tree (implementation under test): the run `work/` directory, which is
  byte-identical to the read-only `source/` tree (verified with `diff -rq`; the
  only extra entries in `source/` are the empty/additional submodule checkouts
  `fuzzy/` and `raft-compat/`).
- Module: `github.com/hashicorp/raft`, `go 1.20`, version content = v1.7.3.
- The Go module cache contains an extracted copy `github.com/hashicorp/raft@v1.7.3`
  and the original module zip
  (`$GOMODCACHE/cache/download/github.com/hashicorp/raft/@v/v1.7.3.zip`), whose
  `@v/v1.7.3.info` records `Origin.Hash = c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`
  and `Ref = refs/tags/v1.7.3` — i.e. the exact commit in the run brief.

Key observation (executed): the audited tree is **byte-for-byte identical** to
the extracted v1.7.3 module zip. Evidence:

```
$ md5sum <cache>/github.com/hashicorp/raft@v1.7.3/raft.go source/raft.go
92d8f55e554659558d745c3f170cb008  .../raft@v1.7.3/raft.go
92d8f55e554659558d745c3f170cb008  .../source/raft.go

$ diff -rq <unzipped v1.7.3.zip> source     # (no output for any tracked file)
Only in .../source: fuzzy
Only in .../source: raft-compat
```

Interpretation / caveat: this shows the captured implementation matches the
published upstream v1.7.3 release. It does **not** by itself prove "no injected
bug", because if the harness seeded the module cache from the same (possibly
mutated) tree, a mutation would be mirrored in the cache. I have no independent
offline reference (no network) to break that tie, so this is treated as evidence
about *provenance*, not a correctness result. The audit therefore proceeds by
source review of the consensus-critical logic.

## 2. Environment limits

- Ordinary shell has no network. Creating TCP listeners is denied
  (`listen tcp 127.0.0.1:0: socket: operation not permitted`). No `isolated_exec`
  helper was discoverable on PATH in this session, so `*_test.go` cases that build
  real `NetworkTransport`/`TCPTransport` listeners cannot run.
- `go build ./...` succeeds. In-memory / pure-logic tests run fine.

## 3. Test runs

`GOCACHE=$PWD/.runtime/go-build GOMODCACHE=/home/nitro/go/pkg/mod go test -short -count=1 ./...`

Result: FAIL only for tests that open sockets. All 27 failures (18 top-level)
are `... socket: operation not permitted`, e.g. `TestNetworkTransport_*`,
`TestTCPTransport_*`, `TestRaft_runFollower_*`. Log preserved at
`work/.runtime/test_short.log`. No non-socket assertion failure was observed,
which is expected for a clean upstream tree but is weak evidence against a
well-hidden injected logic bug.

## 4. Source review so far (read, matched against Raft semantics)

Reviewed and found consistent with the Raft specification and upstream intent:

- `commitment.go`: quorum match index `matched[(len-1)/2]`, `>= startIndex`
  gate for committing current-term entries — correct majority rule.
- `raft.go` `appendEntries`: older-term ignore, term bump + step-down, leader
  save, prev-log term check, conflicting-suffix truncation, duplicate skip,
  commit-index advance via `min(LeaderCommitIndex, lastIndex)`, config commit
  bookkeeping — all canonical.
- `raft.go` `requestVote` / `requestPreVote`: term handling, config/membership
  checks, prior-vote dedup, up-to-date log comparison (`lastTerm` then
  `lastIdx`) — canonical.
- `raft.go` `installSnapshot`: version gate, term gate, deferred reader drain
  (issue #212), size check, restore, `lastApplied`/snapshot/config updates,
  compaction.
- `raft.go` `electSelf` / `preElectSelf`: term increment only in `electSelf`;
  self-vote; pre-vote does not change state/term; pre-vote responses for
  non-pre-vote peers treated as granted — matches upstream design.
- `raft.go` `runCandidate`: pre-vote tally → real election; `votesNeeded =
  quorumSize()` (= `voters/2 + 1`).
- `raft.go` `leaderLoop`: commitCh processing, inflight log grouping,
  config-commit + self-removal step-down, leadership-transfer state machine,
  leader-lease check via `checkLeaderLease`.
- `raft.go` `dispatchLogs` / `processLogs` / `prepareLog`: single-leader index
  assignment, local `commitment.match`, batched FSM application, `lastApplied`
  update — canonical.
- `replication.go` `replicateTo`: backoff, nextIndex decrement
  `max(min(nextIndex-1, resp.LastLog+1), 1)`, snapshot fallback — canonical.
- `configuration.go` `nextConfiguration` / `checkConfiguration`: add/demote/
  remove/promote handling, last-voter guard — canonical.
- `snapshot.go` `shouldSnapshot` / `takeSnapshot` / `compactLogsWithTrailing`:
  delta threshold, committed-config inclusion, `min(snapIdx, lastLogIdx-trailing)`
  truncation bound — canonical.
- `fsm.go` `runFSM`: single vs batch apply, config-store gating, barrier
  not sent to FSM, `lastIndex/lastTerm` tracking, restore updates — canonical.

`go vet ./...` — clean (exit 0).

No concrete defect has been confirmed by execution or by a source-level
contradiction at this point. The areas above are the main consensus paths.

## 5. Unresolved / next work (for continuation)

1. Obtain or reconstruct an independent pristine reference for v1.7.3 to turn
   the byte-equality observation into a real mutation-detection signal (blocked
   offline; may be impossible).
2. Read the remaining files not yet reviewed line-by-line: `api.go`
   (Apply/Barrier/VerifyLeader/Bootstrap/Snapshot/AddVoter paths),
   `log.go`, `log_cache.go`, `file_snapshot.go`,
   `net_transport.go`, `inmem_*.go`, `observer.go`, `saturation.go`,
   `future.go`, `config.go`.
3. Write targeted in-memory tests (no sockets) for boundary conditions that
   existing tests may miss, e.g.:
   - `commitment.recalculate` with single voter / startIndex boundary;
   - `appendEntries` suffix truncation when follower is ahead and config index
     is inside the truncated range;
   - `nextConfiguration` edge cases (remove unknown server, promote non-staging);
   - snapshot/compaction bounds at `lastLogIdx == trailingLogs` etc.
4. Consider `go vet ./...` and a `-race` run of the in-memory subset.

## 6. Reproduction artifacts

- `work/.runtime/test_short.log` — full `go test -short ./...` output (socket-only
  failures).
- `work/.runtime/zipcheck2/` — unzipped upstream v1.7.3 module for the byte-diff.
