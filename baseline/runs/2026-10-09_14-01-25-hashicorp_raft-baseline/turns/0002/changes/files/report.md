# Audit Report — hashicorp/raft (baseline, source_identity c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe)

Status: in progress (turn 3). Strong evidence the audited tree is the
**unmodified upstream v1.7.3 release**; no concrete injected defect found.

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

Independent corroboration of the cache (turn 3): the cache contains a
**sum.golang.org-signed** record for this exact module:

```
$ cat $GOMODCACHE/cache/download/sumdb/sum.golang.org/lookup/github.com/hashicorp/raft@v1.7.3
35446165
github.com/hashicorp/raft v1.7.3 h1:DxpEqZJysHN0wK+fviai5mFcSYsCkNpFUl1xpAW8Rbo=
github.com/hashicorp/raft v1.7.3/go.mod h1:DfvCGFxpAUPE0L4Uc8JLlTPtc3GzSbdH0MTJCLgnmJQ=

go.sum database tree
59045944
LE6Lx+GNVyuFBv/jKcFIiPkG1WC7DHwG0clpfN/TBlA=

— sum.golang.org Az3grk9ctaTv+CITXOwxCEHU3APAw5X7Ck14+fvFlh0GCktwX15+XPzy//GgL2G50ZgY05e8eXFTWcvW6pN5tozsLQQ=
```

and the local toolchain verifies the cached zip against that signed hash:

```
$ GOPROXY=off go mod download -json github.com/hashicorp/raft@v1.7.3
{ ... "Sum": "h1:DxpEqZJysHN0wK+fviai5mFcSYsCkNpFUl1xpAW8Rbo=",
  "Origin": { "Hash": "c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe",
              "Ref": "refs/tags/v1.7.3" } }
```

Interpretation (turn 3): the cached zip is the *genuine published* upstream
v1.7.3 (its `h1:` hash matches a record signed by sum.golang.org, which cannot be
forged offline), and the audited `work/`/`source/` tree is **byte-for-byte
identical** to that zip. Therefore the audited implementation is the unmodified
upstream v1.7.3 release: no source-level mutation is present in the audited scope.
The audit's remaining value is (a) confirming no *genuine* correctness defect is
present/reachable in the reviewed paths, and (b) recording reviewed coverage.

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
- `raft.go` `configurationChangeChIfStable`: gates config changes on
  `latestIndex == committedIndex && commitIndex >= commitment.startIndex` —
  canonical (matches upstream; unrelated to any mutation).
- `log.go` (`LogType`, `LogStore`/`MonotonicLogStore` contracts, `oldestLog`),
  `log_cache.go` (ring-buffer validity check, delete invalidation), `future.go`
  (`deferError` respond-once semantics) — canonical.
- `api.go` `BootstrapCluster` / `RecoverCluster` (state/validation/term/entry
  handling) reviewed; consistent with upstream intent.

`go vet ./...` — clean (exit 0).

## 4a. Conclusion so far

Executed evidence: the audited tree equals the sum.golang.org-verified upstream
v1.7.3 module byte-for-byte, builds, passes `go vet`, and passes all non-network
tests. Source review of the consensus-critical paths (commit index, leader
commitment, voting/pre-vote, log truncation, replication backtracking, snapshot
install/compaction, membership changes, FSM apply) found no contradiction with
Raft semantics. **No concrete correctness defect has been identified in the
audited implementation.** No fabricated finding is reported.

No concrete defect has been confirmed by execution or by a source-level
contradiction at this point. The areas above are the main consensus paths.

## 5. Unresolved / next work (for continuation)

1. ~~Obtain independent pristine reference~~ — resolved in turn 3 via the
   sum.golang.org-signed module hash; the tree is confirmed pristine upstream.
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
   (`go vet ./...` done, clean; `-race` on the in-memory subset still open.)

## 6. Reproduction artifacts

- `work/.runtime/test_short.log` — full `go test -short ./...` output (socket-only
  failures).
- `work/.runtime/zipcheck2/` — unzipped upstream v1.7.3 module for the byte-diff.
