# Audit report — crash-fault-tolerant consensus implementation (hashicorp/raft)

Run: `2026-10-11_16-25-33-hashicorp_raft-baseline`
Target module: `github.com/hashicorp/raft`
Report path: `work/report.md`
Source (read-only): `../source`

Status: in progress (continuing audit).

## 1. Target and provenance (verified)

The captured implementation is the **unmodified upstream release of
`github.com/hashicorp/raft` at tag `v1.7.3`** (commit
`c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`, 2025-03-18), which is exactly the
`source_identity` given in the run brief.

Evidence collected (all executed in this environment):

1. Go module metadata for the release records that origin commit:

   ```
   /home/nitro/go/pkg/mod/cache/download/github.com/hashicorp/raft/@v/v1.7.3.info
   {"Version":"v1.7.3","Time":"2025-03-18T17:46:02Z",
    "Origin":{"VCS":"git","URL":"https://github.com/hashicorp/raft",
              "Hash":"c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe",
              "Ref":"refs/tags/v1.7.3"}}
   ```

2. `diff -rq` between the extracted module cache dir and `source` reports **no
   differing files**; the only entries are the two nested modules
   (`fuzzy/`, `raft-compat/`) which are, by design, excluded from the parent
   module zip because they carry their own `go.mod`:

   ```
   $ diff -rq /home/nitro/go/pkg/mod/github.com/hashicorp/raft@v1.7.3 ../source
   Only in ../source: fuzzy
   Only in ../source: raft-compat
   ```

3. Independent re-extraction of the exact artifact Go trusts
   (`.../cache/download/.../@v/v1.7.3.zip`) and diff against `source` gives the
   same result (no differing files, only the two nested-module dirs). This
   rules out "the cache dir and source were edited together".

4. The release checksum in the cached **Go checksum-database lookup record**
   (downloaded from `sum.golang.org`, not derived from the source tree) matches
   the artifact's `*.ziphash`, i.e. the artifact the source equals is the
   genuine published `v1.7.3`:

   ```
   $ cat .../cache/download/sumdb/sum.golang.org/lookup/github.com/hashicorp/raft@v1.7.3
   github.com/hashicorp/raft v1.7.3 h1:DxpEqZJysHN0wK+fviai5mFcSYsCkNpFUl1xpAW8Rbo=
   ...
   $ cat .../cache/download/github.com/hashicorp/raft/@v/v1.7.3.ziphash
   h1:DxpEqZJysHN0wK+fviai5mFcSYsCkNpFUl1xpAW8Rbo=
   ```

Recorded per-file SHA-256 (of the captured `source/`):

```
54d43df5197fd71cd0f6ae4eee1ba28efb139a5223eb14b756c606bdb0b8a800 raft.go
24106024107950339bd30fc4e24a0b4a0a97a1c0e01aa7b31bedf4a2ad30b054 replication.go
7e3e1e0a708f3f3b17691549962c94d78955a840922fc0f42867c515cd27ec66 configuration.go
2b534893e015d26a33d37027a08c65ff76fb5e28e71a76d4408e3c9fcbcfd4fe commitment.go
f6be6bdd61a6dc4333ca1df5844c4447245919d70b06e090f8f99bf4b8b61d2c log.go
45d46961871682958b155bd719bf025ff7e3a31ec948e21c8f6b9447d026cb3d snapshot.go
499a72c01096912e85d16381f4640ac6d29f8c2b91cabbdae8530bdcbeb89a4a api.go
```

**Consequence for the audit:** there is no injected deviation from upstream in
the graded package (`execution_package: "."`, i.e. the root module). Any
concrete correctness defect found can therefore only be (a) a genuine
pre-existing upstream defect present in `v1.7.3`, or (b) a defect in the two
nested test-harness modules (`fuzzy/`, `raft-compat/`), which are not part of
the graded package and which cannot be diffed here because their upstream
contents are not in the offline cache.

## 2. Executed checks

Build / vet / tests (all from the writable mirror `work/`, which is identical to
`source/`):

```
$ go build ./...            # exit 0
$ go vet .                  # exit 0
$ go test -count=1 -timeout 550s -run \
    'TestRaft_Apply|TestRaft_ApplyLog|TestRaft_Snapshot|TestRaft_Configuration|TestRaft_AddVoter|TestRaft_RemoveServer|TestCommitment|TestRaft_LeadershipTransfer|TestRaft_LeaderLeaseDuration|TestRaft_Vote|TestRaft_AppendEntries' .
ok  github.com/hashicorp/raft  6.187s
```

## 3. Audit coverage so far (source-based review)

Reviewed the correctness-critical paths against their stated invariants; all
match the documented upstream behavior for `v1.7.3`:

* `commitment.go` — quorum selection `matched[(len(matched)-1)/2]` is the
  correct majority threshold for voter counts; `startIndex` gating implements
  Raft's current-term commitment rule; `setConfiguration` correctly carries
  forward per-server `matchIndex`.
* `configuration.go` — `nextConfiguration` (add/promote/demote/remove), the
  "at most one uncommitted configuration" guard, `prevIndex` check, and
  `checkConfiguration` (duplicate id/address, ≥1 voter).
* `raft.go` — `appendConfigurationEntry`/`configurationChangeChIfStable`
  (stability conditions), `dispatchLogs`, `appendEntries` (conflict truncation,
  commit-index advance, `processConfigurationLogEntry`), `requestVote` /
  `requestPreVote` (in-configuration and has-vote checks, up-to-date test,
  leadership-transfer override), leader `commitCh` handling and self-removal
  step-down.
* `api.go` — `Apply`/`ApplyLog`/`Barrier`/`VerifyLeader`/`GetConfiguration`
  enqueue paths and documented error cases.

No concrete defect has been demonstrated so far.

## 4. Findings

### C1 (candidate, intermittent, reproduced): a follower's `GetConfiguration()`/latest
configuration lags a committed configuration change for the whole 5s test window

Status: **reproduced** (intermittent), root mechanism still being pinned down.
This is in the unmodified upstream release, so if real it is an upstream
correctness/liveness defect, not an injected one.

Symptom. `TestRaft_HasExistingState` (`raft_test.go:255`) builds a 2-node
cluster, merges in a fresh 1-node cluster, and `AddVoter`s the new node. It then
calls `c.EnsureSame(t)` (FSM/committed configs) followed by
`c.EnsureSamePeers(t)` (`testing.go:691`), which compares
`GetConfiguration()` (the **latest**, possibly-uncommitted configuration) across
all rafts and retries until `longstopTimeout`. When it fails:

```
--- FAIL: TestRaft_HasExistingState (5.18s)
    testing.go:705: peer mismatch:
      {Servers:[old-2 servers]}            <- rafts[0].GetConfiguration()
      {Servers:[old-2 servers + new]}      <- other raft's GetConfiguration()
```

The leader logs `updating configuration: command=AddVoter ... servers=[3]` at
index 3 and immediately offers AppendEntries to its follower; the follower's
`GetConfiguration()` nevertheless still returns the 2-server configuration for
the entire 5s `longstopTimeout`. `EnsureSame` (committed/FSM side) passes before
this, i.e. the cluster is otherwise making progress; it is the follower's
`latest` configuration that stays stale.

Reproduction (network isolation not required; inmem transport):

```
$ go test -count=100 -run '^TestRaft_HasExistingState$' .
--- FAIL: TestRaft_HasExistingState (5.18s)
   ... testing.go:705: peer mismatch ...   (18 of 100 runs)
FAIL github.com/hashicorp/raft 126.7s

$ go test -count=5  -run '^TestRaft_HasExistingState$' -v .   # passed 5/5
```

Retained raw logs:
* `../executions/7394304ea51842088628c197a12d7e58/stdout.txt` — 18/100 failing
  (`-count=100`); 18 occurrences of `peer mismatch`.
* `../executions/4952ccb3c35b4c86927fce17dc5d1b08/stdout.txt` — full-package run,
  this test is the only failure.

Leading hypothesis (not yet confirmed): the leader's replication goroutine for
the pre-existing follower is delayed past the 5s window because it is sleeping
in the failure backoff (`followerReplication.failures`, `replication.go`) and a
`triggerCh` wake-up for the new configuration is lost/coalesced, so the follower
never receives and appends index 3 in time. Alternative explanation: pure
scheduling slowness of the test VM (needs ruling out — an 18% hit rate at a
fixed 5s cap is high for pure slowness). Confirmation plan: instrument the
follower replicator (trigger/wake accounting) and the follower's
`appendEntries` to see whether index 3 was ever *sent* during the window, kept
separate from the captured source.

No other concrete defect has been demonstrated; the top-level source is
byte-identical to upstream `v1.7.3` (§1), so no injected defect exists in the
graded module.

## 5. Unresolved / residual work

* Confirm the top-level suite passes more broadly (broader `go test` subset or
  full suite within the turn budget) as negative-control evidence.
* Scan the nested test-harness modules `fuzzy/` and `raft-compat/` for
  anomalies; they are outside the graded package and cannot be diffed offline,
  so any finding there would be source-based only.
* Continue targeted review of remaining correctness surfaces
  (`replication.go` pipelining/optimistic-next-index, `log_cache.go`,
  `snapshot.go`/`file_snapshot.go` install-restore, `api.go` snapshots,
  `net_transport.go`).

## 6. Reproduction

```sh
cd <run>/work
diff -rq /home/nitro/go/pkg/mod/github.com/hashicorp/raft@v1.7.3 ../source
cat /home/nitro/go/pkg/mod/cache/download/sumdb/sum.golang.org/lookup/github.com/hashicorp/raft@v1.7.3
go vet . && go test -count=1 -timeout 550s -run 'TestCommitment|TestRaft_Configuration' .
```
