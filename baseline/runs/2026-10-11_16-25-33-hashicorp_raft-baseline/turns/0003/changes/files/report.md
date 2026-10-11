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

Full package in the TCP-capable `isolated_exec` namespace (so `integ_test.go` /
net-transport cases can listen):

```
$ go test -count=1 -timeout 800s .          # isolated_exec, work/
--- FAIL: TestRaft_HasExistingState (5.18s) # the only failure; see C1 (§4)
FAIL github.com/hashicorp/raft  137.3s
```

In the ordinary (no-network) shell, the only failures are the `integ_test.go`
cases that require a TCP listener (`socket: operation not permitted`), which are
environmental, not defects.

Negative controls (isolated_exec, work/ == captured source):

```
$ go test -count=1 -timeout 800s -skip '^TestRaft_HasExistingState$' .   # whole package, no race
ok  github.com/hashicorp/raft  129.8s

$ go test -race -count=1 -timeout 560s -skip '^TestRaft_HasExistingState$' .   # whole package, race detector
ok  github.com/hashicorp/raft  136.5s        # no data races reported

$ go test -race -count=1 -run '^(TestRaft_SingleNode|TestRaft_TripleNode|TestRaft_JoinNode|TestRaft_AddVoter|TestRaft_RemoveServer|TestRaft_Snapshot|TestRaft_Apply|TestRaft_Vote|TestRaft_LeaderLeaseDuration|TestRaft_LeadershipTransfer)$' .
ok  github.com/hashicorp/raft  2.1s
```

Retained: `../executions/fa10228177b948898d48a79eaa4f5d2b` (skip, no race),
`../executions/8d2a3ca0881946baa31e9612d7288499` (whole package under `-race`),
`../executions/5838b7dcb98e4b1089f0bc562d40cfb9` (race subset).

Across four independent full-package runs, the only test that ever fails is
`TestRaft_HasExistingState`, and only because of the helper defect C1.

Two further full-package runs (skip-flaky) also pass:

```
$ for i in 1 2; do go test -count=1 -timeout 400s -skip '^TestRaft_HasExistingState$' . ; done
ok  github.com/hashicorp/raft  129.2s
ok  github.com/hashicorp/raft  132.1s
# retained: ../executions/e3453fc4adf94cef9566d6294f30c046/stdout.txt
```

Total: six full-package runs of the captured implementation; the only test that
ever fails is `TestRaft_HasExistingState` (helper defect C1). No consensus /
membership / snapshot / transport test failed, and the whole package is clean
under the race detector.

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
* `snapshot.go` — `takeSnapshot` (committed-config gating, persist/close/
  `compactLogs`), `compactLogsWithTrailing`, `removeOldLogs`; reviewed, no
  defect.

No concrete defect has been demonstrated so far.

## 4. Findings

### C1 (confirmed, reproduced): `EnsureSamePeers` test helper caches `rafts[0]`'s
configuration once and never refreshes it, producing a guaranteed 5s spurious failure

Status: **confirmed as a defect in the shipped test helper `cluster.EnsureSamePeers`
(`testing.go:691`), not in the consensus implementation.** Resolved as a
false-positive for implementation correctness; reported because it is a real
defect in the library's public testing utilities.

Location: `testing.go:691-710`

```go
func (c *cluster) EnsureSamePeers(t *testing.T) {
	limit := time.Now().Add(c.longstopTimeout)
	peerSet := c.getConfiguration(c.rafts[0])   // <-- sampled ONCE, never refreshed
CHECK:
	for i, raft := range c.rafts {
		if i == 0 { continue }
		otherSet := c.getConfiguration(raft)     // <-- refreshed every attempt
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

Expected behavior: the helper should retry until every raft reports the same
configuration, and `raft_test.go:255 TestRaft_HasExistingState` should not fail
while the cluster is converging.

What actually happens: `peerSet` is read from `rafts[0]` exactly once, *before*
the retry loop. `TestRaft_HasExistingState` immediately follows
`c.Leader().AddVoter(...)` (which returns when the leader has committed the
`AddVoter` entry) with `c.EnsureSame(t)` then `c.EnsureSamePeers(t)`. If
`rafts[0]` has not yet received the committed configuration entry at the instant
`EnsureSamePeers` is entered, `peerSet` is frozen at the old 2-server set while
every other raft's `otherSet` advances to the new 3-server set; the two can never
be equal, so the loop always times out and fails after `longstopTimeout` (5s)
even though `rafts[0]` catches up moments later.

Why `EnsureSame` does not prevent this: `EnsureSame` compares the mock FSMs'
applied command logs and tracked configurations, but the default `mockFSM` used
by `MakeCluster` does **not** implement `ConfigurationStore` (only
`MockFSMConfigStore` does — `testing.go:45,110`, `fsm.go:113-119`), and
`TestRaft_HasExistingState` applies no command entries. So both compared slices
are empty and `EnsureSame` returns immediately, providing no barrier that the
configuration change reached `rafts[0]`.

Evidence — the failure is a race on `rafts[0]`'s sample point (~18% of runs):

```
# unmodified work/ tree (captured implementation), repeated:
$ go test -count=100 -run '^TestRaft_HasExistingState$' .
grep -c '--- FAIL' -> 18        # 18/100 runs fail with "peer mismatch"

# same test, only change = refresh peerSet inside CHECK (scratch copy work/diag):
$ go test -count=100 -run '^TestRaft_HasExistingState$' .   # diag
ok  github.com/hashicorp/raft  31.5s         # 100/100 pass, 0 failures
```

Instrumentation of the leader's replication goroutine (scratch copy, `RAFT_DIAG=1`,
`[DIAG]` traces written to stderr; source kept separate under `work/diag/`) shows
the follower actually receives the new entry promptly in the failing run:

```
[DIAG] setLatestConfiguration local=leader   index=3 nservers=3
[DIAG] pipelineSend peer=follower nextIdx=3 lastIndex=3 entries=1
[DIAG] recvAppendEntries local=follower from=leader n=1 first=3 last=3
[DIAG] setLatestConfiguration local=follower index=3 nservers=3
```

i.e. the follower reaches the new configuration within the same instant, but the
already-cached `peerSet` (old 2-server set) is what is compared at the timeout,
matching the reported `peer mismatch: {2 servers} {3 servers}` where the
2-server value is `rafts[0]`'s *stale sample*.

Retained raw logs / scratch:
* `../executions/7394304ea51842088628c197a12d7e58/stdout.txt` — 18/100 failing (unmodified).
* `../executions/4952ccb3c35b4c86927fce17dc5d1b08/stdout.txt` — full-package run; this test is the only failure.
* `../executions/0260935a8bf444308368db86dc209fa1/` — instrumented 100x run (18 fails, 31k-line log written to `work/diag/diaglog.txt`).
* `../executions/ef0f528d76b34767860de6597bcdd82c/stdout.txt` — patched helper: 100/100 pass.
* `work/diag/` — scratch copy with the diagnostic patch (`EnsureSamePeers` refresh + `RAFT_DIAG` traces), kept distinct from the captured source.

Note: this does not demonstrate any consensus-correctness bug; the replication
path itself behaved correctly (entries replicated and applied). The defect is
that the helper's non-refreshed reference makes a transient lag a guaranteed
timeout failure. The same pattern could flake any other test that calls
`EnsureSamePeers` right after a membership change.

Blast radius check: `EnsureSamePeers` has 10 call sites (`raft_test.go` lines
241,285,618,669,862,1363,2270,2304,2338,3119). The ones that apply command
entries first (e.g. `TestRaft_JoinNode`, `TestRaft_RecoverCluster`,
`TestRaft_LeaderID_Propagated`) are protected because `EnsureSame` then performs
a real barrier; all three passed 30/30 in the TCP-capable namespace
(`../executions/5e2ffd13c8bf44738fd337c6fe2ea082/stdout.txt`). Only
`TestRaft_HasExistingState` applies no commands, so its `EnsureSame` is vacuous
and the cached-`peerSet` race is exposed.

No concrete defect has been demonstrated in the consensus implementation itself;
the top-level source is byte-identical to upstream `v1.7.3` (§1), so no injected
defect exists in the graded module.

## 5. Unresolved / residual work

* Nested test-harness modules `fuzzy/` and `raft-compat/` cannot be built or run
  in this environment (blocked, external prerequisite): `fuzzy` pins
  `raft-boltdb v0.0.0-20171010151810` and `go-msgpack/v2 v2.1.1`, whose module
  zips are not extracted, and the module cache is read-only
  (`go: open .../@v/*.lock: read-only file system`); `raft-compat` needs the
  `raft-previous-version` git submodule, which is not checked out. They are
  outside the graded package (`execution_package: "."`), so only source
  inspection is possible.
* Continue targeted review of remaining correctness surfaces
  (`replication.go` pipelining/optimistic-next-index, `log_cache.go`,
  `snapshot.go`/`file_snapshot.go` install-restore, `api.go` snapshots,
  `net_transport.go`). These have not yet been exercised by a dedicated
  differential/edge-case test; current status is source-based review only.
* Decide whether to search for other callers of `EnsureSamePeers` that may be
  flaky for the same cached-`peerSet` reason (test-only impact).

## 6. Reproduction

```sh
cd <run>/work
diff -rq /home/nitro/go/pkg/mod/github.com/hashicorp/raft@v1.7.3 ../source
cat /home/nitro/go/pkg/mod/cache/download/sumdb/sum.golang.org/lookup/github.com/hashicorp/raft@v1.7.3
go vet . && go test -count=1 -timeout 550s -run 'TestCommitment|TestRaft_Configuration' .
```
