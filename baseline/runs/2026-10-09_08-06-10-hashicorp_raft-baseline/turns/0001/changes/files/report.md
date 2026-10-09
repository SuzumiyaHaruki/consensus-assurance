# Audit report — hashicorp/raft (baseline)

Run: `2026-10-09_08-06-10-hashicorp_raft-baseline`
Source identity (run brief): `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`
Working dir (writable): `/home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-09_08-06-10-hashicorp_raft-baseline/work`
Read-only source: `/home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-09_08-06-10-hashicorp_raft-baseline/source`

## Summary

No concrete implementation-level correctness defect has been demonstrated so far.
The supplied tree is **byte-identical to the upstream released module
`github.com/hashicorp/raft@v1.7.3`**, git hash
`c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe` (the `v1.7.3` tag).
In other words, no local mutation / injected defect was found in the captured
implementation, and none is claimed. What follows distinguishes executable
evidence from source-based reasoning, and records one reproducible
*test-level* flake plus the environment limitation that blocks the TCP-backed
tests.

## Propagated guidance (from the run brief)
- Crash-fault-tolerant consensus system, expected module `github.com/hashicorp/raft`.
- Offline Go toolchain; ordinary shell has **no network**; `isolated_exec`
(bwrap with `--unshare-net`) supports **private local TCP** only.
- Source/logs read-only, work dir writable. Do not modify the captured
  implementation or dependencies to manufacture a defect.

## 1. Provenance / "was anything changed?" (executed)

Reference: the pristine module cache copy extracted by Go from the downloaded
module zip, `/home/nitro/go/pkg/mod/github.com/hashicorp/raft@v1.7.3`, whose
`@v/v1.7.3.info` records
`{"Version":"v1.7.3","Origin":{"Hash":"c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe","Ref":"refs/tags/v1.7.3"}}`.

Commands (run from the working dir):

```
# Byte-for-byte comparison of the whole tree (top-level .go/.md/.mod/.sum,
# bench/, docs/) against the module-cache extraction.
diff -rq --exclude=.git --exclude=.runtime --exclude=.github --exclude=raft-compat \
  /home/nitro/go/pkg/mod/github.com/hashicorp/raft@v1.7.3 \
  /home/nitro/Desktop/consensus-assurance/baseline/runs/2026-10-09_08-06-10-hashicorp_raft-baseline/source
# -> only difference reported: "Only in <source>: fuzzy"

# Also re-extracted the module .zip itself and diffed it against the source:
Z=$(mktemp -d); cd "$Z"; unzip -q \
  /home/nitro/go/pkg/mod/cache/download/github.com/hashicorp/raft/@v/v1.7.3.zip
diff -rq "github.com/hashicorp/raft@v1.7.3" <source>
# -> identical (differences are only the nested-module/dotfile paths absent from a module zip: fuzzy/, raft-compat/, .github/, dotfiles)
```

Per-file SHA-256 spot checks (`raft.go`, `api.go`, `replication.go`, `log.go`,
`snapshot.go`, `config.go`) are identical between source and the module-cache
reference.

Interpretation and caveat:
- The module zip's content matches the source, and the zip's recorded origin is
  the `v1.7.3` tag at commit `c0dc6a0b...` (which equals the brief's
  `source_identity`). Directories with their own `go.mod` (`fuzzy/`,
  `raft-compat/`) are excluded from a Go module zip, so they have no reference
  here; they are test/fuzz harnesses, not the consensus engine.
- This evidence shows the *supplied tree* is not a locally-modified variant of
  the released module. It cannot, by itself, prove the module zip equals
  github.com/hashicorp/raft's published bytes (that check needs network), but
  combined with the recorded tag hash it is strong evidence the audit target is
  the unmodified upstream release.
- Consequence: no diff-based "injected defect" exists to point at. Any finding
  must therefore be a defect that is genuinely present in upstream v1.7.3.
  None has been demonstrated yet (see §3, §4).

## 2. Build & test environment (executed)

```
go version                       # go1.25.8 linux/amd64
go env GOPATH GOMODCACHE GOPROXY  # GOMODCACHE=/home/nitro/go/pkg/mod, GOPROXY=off
go build ./...                    # success (exit 0)
go vet ./...                      # no findings
```

Limitation discovered (executed): the interactive shell sandbox denies the
`socket` syscall outright, so any test that binds/connects TCP fails with
`socket: operation not permitted` regardless of code correctness:

```
python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0))"
# PermissionError: [Errno 1] Operation not permitted
```

The private-network bwrap exec used by the harness *does* support loopback
(the retained canary `executions/ac79a4b.../result.json` prints
`ISOLATED_TCP_VERIFIED`), so the TCP-backed tests need that path, which is not
available to this shell. This is an environment constraint, not a code defect.

Attempting to reach that path from this shell also fails (executed):
```
bwrap --die-with-parent --unshare-net ... -- python3 -c "...bind(('127.0.0.1',0))"
# bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted
```
so nested network-namespace setup is denied here and the TCP tests cannot be
reached from inside this agent's sandbox.

### Full suite (`go test -count=1 ./...`, 131 s)
Result: FAIL, but the failures are entirely:
- TCP/loopback tests that cannot open sockets in this sandbox
  (`net_transport_test.go`, `tcp_transport_test.go`, `integ_test.go`), and
- one flaky timing failure, `TestRaft_HasExistingState` (see §3).

### Race subset (`go test -race`, in-memory transport only)
```
GOMAXPROCS=4 go test -race -count=1 -timeout 1200s \
  -run 'TestRaft|TestConfiguration|TestLeader|TestSnapshot|TestRestore|TestVote|TestPreVote|TestRollback|TestLog|TestFuture|TestCommitment|TestObserver' .
```
Result: **no `DATA RACE` and no panic**. Only socket-blocked tests failed
(`integ_test.go`). Log: `audit/race_subset.log` (DATA RACE count = 0).

## 3. Reproducible observation: flaky `EnsureSamePeers` (test-level)

`TestRaft_HasExistingState` (and, under `-race`,
`TestRaft_SnapshotRestore_PeerChange`) intermittently fail inside
`cluster.EnsureSamePeers` (`testing.go:705`).

Reproduction (6 runs; failure ~1 in 6):
```
for i in $(seq 1 6); do
  go test -count=1 -timeout 120s -run 'TestRaft_HasExistingState$' .
done
```
Observed: 5 × `ok`, 1 × `FAIL ... peer mismatch` after `longstopTimeout`
(~5 s). Log: `audit/flaky_hasstate.log`.

Failure shape (executed):
```
testing.go:705: peer mismatch:
  {Servers:[<A> <B>]}                 # rafts[0] view
  {Servers:[<A> <B> <C>]}             # leader view (newly-added voter C)
```
and in the `-race` run of `TestRaft_SnapshotRestore_PeerChange`:
```
testing.go:705: peer mismatch: {Servers:[]} {Servers:[<A> <B> <C>]}
```

Assessment (source-based, consistent with the logs):
- `EnsureSamePeers` calls `Raft.GetConfiguration()` on each node and requires
  all nodes to agree before `longstopTimeout` (default 5 s).
  `GetConfiguration` returns the node's **latest** (possibly not-yet-committed,
  and possibly not-yet-replicated) configuration, not the committed one
  (`api.go`, `GetConfiguration` -> `getLatestConfiguration`).
- `AddVoter` commits when a quorum has stored the entry; a non-quorum follower
  may legitimately still be behind, and `GetConfiguration` on that straggler
  then returns the older (or, transiently, empty) view.
- Therefore the mismatch is a *read-lag* observed via an uncommitted-view
  accessor, and the test asserts convergence within a wall-clock window. Under
  load/`-race` that window is occasionally missed.

This is presented as a test-level flakiness / observability nuance, **not** as a
demonstrated consensus-safety defect: no committed-then-lost entry, no
divergent committed configuration, and no data race were observed. It is
recorded because it is reproducible and a future reviewer may want to confirm
or refute the convergence claim.

## 4. Source review performed (no demonstrated defect)

Read and cross-checked against expected Raft behavior; nothing anomalous was
found relative to the released implementation, and no defect was demonstrable:
- `runCandidate` pre-vote path and `preElectSelf` / `requestPreVote` tallying
  (term handling, self pre-vote, `quorumSize`): consistent.
- `appendEntries` (follower): prev-log match, suffix truncation, configuration
  entry processing, commit-index advance: consistent.
- `installSnapshot` (follower): version check, term handling, config/`lastApplied`
  updates, log compaction: consistent.
- `requestVote` (real vote): leader check, `LeadershipTransfer`, non-voter
  rejection, persisted-vote duplicate handling, log up-to-date check: consistent.
- `configuration.go` (`nextConfiguration`, `checkConfiguration`): consistent.
- `replication.go` (`replicate`/`replicateTo`, `nextIndex` backtrack,
  `sendLatestSnapshot`): consistent.
- `checkLeaderLease` / `quorumSize`: consistent.

## 5. Unresolved work / next steps

1. Re-run the TCP-backed suite through an `isolated_exec` (bwrap, private
   loopback) to clear the ~15 socket-blocked tests (`net_transport`,
   `tcp_transport`, `integ_test.go`), which currently cannot be evaluated here.
2. Stress the two flaky tests with `-race -count=N` to measure the failure rate
   and to decide whether the lag is purely scheduling or reflects a genuine
   delayed-replication condition.
3. Continue adversarial review of the pre-vote extension (newest in the 1.7.x
   line) and of leader-lease / leadership-transfer edge cases, since these have
   the least test coverage and are the most likely homes for a real (vs.
   injected) defect.
4. If a sibling non-baseline variant of this scenario is available, diff it
   against this tree to isolate the intended defect; on the *baseline* tree it
   is not present.

## 6. Artifacts

- `audit/flaky_hasstate.log` — 6-run flake reproduction of `TestRaft_HasExistingState`.
- `audit/race_subset.log` — `-race` run of an in-memory-transport subset (0 data races).

## 7. Honesty note

No execution output in this report is fabricated. Findings labelled "executed"
were produced by the commands shown; items labelled "source-based" are
reasoning not backed by a failing run. No implementation or dependency file was
modified.
