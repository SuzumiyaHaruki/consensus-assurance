# Audit report — hashicorp/raft fixture (source identity c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe)

Run: `2026-10-09_12-07-16-hashicorp_raft-baseline`
Audited module: `github.com/hashicorp/raft` (Go), package `.`

## Bottom line

One concrete correctness defect was found and reproduced (Finding 1), plus one minor
diagnostic defect (Finding 2).

**`cluster.EnsureSamePeers` in `testing.go` compares against a stale snapshot of the
first node's configuration**, so its retry loop can never make progress when that node is
the one catching up. The helper then reports a peer mismatch even though every node has
converged. This makes the helper — and the shipped `TestRaft_HasExistingState` test that
uses it — fail sporadically (observed 4–9 failures per 40 runs, i.e. ~10–25%). The
affected file is a normal (non-`_test.go`) part of the package and the helper is reachable
by downstream users, so this is user-facing, not merely an internal test artifact.

I first classified this as a load-induced flake; instrumenting it disproved that. At the
moment of failure every node is fully converged (`last=3 commit=3 applied=3`, 3-voter
config) while the failing assertion prints the *old* 2-voter config — proving the compared
value is stale. Moving the snapshot read inside the loop removes 100% of failures
(60/60 pass) with no other change.

The audited source is otherwise the unmodified upstream `v1.7.3` release (see the
authenticated-hash evidence below), so this defect is an upstream latent bug, not an
injected edit. It is still a concrete defect within the authorized scope.

## Finding 1 — `EnsureSamePeers` compares a stale configuration snapshot (testing.go)

### Expected behavior and basis

`EnsureSamePeers` is documented as "EnsureSamePeers makes sure all the rafts have the same
set of peers." It is used by the package's own integration tests (e.g.
`TestRaft_HasExistingState`, `raft_test.go:255`) and is exported/reachable by downstream
users via `EnsureSame`/`EnsureSamePeers` on the value returned by `MakeCluster`. Because a
configuration change can lag on a follower for a heartbeat after it commits, the helper is
written as a bounded polling loop: re-read every node's current configuration, and retry
until they all match or `longstopTimeout` (5s, `testing.go:744`) elapses. For the retry to
ever succeed, every compared value must be re-read on each iteration.

### Affected code (verbatim, `testing.go:689-716`)

```go
func (c *cluster) EnsureSamePeers(t *testing.T) {
	limit := time.Now().Add(c.longstopTimeout)
	peerSet := c.getConfiguration(c.rafts[0])   // <-- read ONCE, outside the loop

CHECK:
	for i, raft := range c.rafts {
		if i == 0 {
			continue
		}

		otherSet := c.getConfiguration(raft)     // <-- re-read every iteration
		if !reflect.DeepEqual(peerSet, otherSet) {
			if time.Now().After(limit) {
				t.Fatalf("peer mismatch: %+v %+v", peerSet, otherSet)
			} else {
				goto WAIT
			}
		}
	}
	return

WAIT:
	c.WaitEvent(nil, c.conf.CommitTimeout)
	goto CHECK
}
```

`c.getConfiguration` calls `r.GetConfiguration()`, which returns
`getLatestConfiguration()` — an atomic snapshot of the node's current configuration. It is
read only once, before the loop; `otherSet` is refreshed each pass but `peerSet` is not.

### Necessary conditions

Node `c.rafts[0]` must be *behind* at the first read and catch up during the retry window.
Then the loop compares the recalculated `otherSet` (new config, e.g. 3 voters) against the
frozen `peerSet` (old config, 2 voters) forever. `TestRaft_HasExistingState` sets this up
exactly: it merges a 1-node cluster into a 2-node cluster and `AddVoter`s the merged node.
The leader applies the new configuration immediately, the other follower usually receives
it on the next heartbeat, and `c.rafts[0]` (a follower, since the leader here is a later
node) is the plausible straggler. If `c.rafts[0]` happens to read the new config first, the
loop can still converge, which is why the failure is intermittent rather than constant.

### What actually happens (executed)

Instrumented copy of the exact test (`/.runtime/audit/diag`, a copy of the tree with
`diagDump` added at the failure point), run 40×:

```
testing.go:706: peer mismatch: {Servers:[{...A} {...B}]}   <-- 2 voters
                                        {Servers:[{...A} {...B} {...C}]}  <-- 3 voters
    ... diagDump immediate before the failure ...
    [0] id=server-51cc6a1f-...: state=Follower last=3 commit=3 applied=3 latestCfgN=3
    [1] id=server-eafb9689-...: state=Leader   last=3 commit=3 applied=3 latestCfgN=3
    [2] id=server-3eab9bdc-...: state=Follower last=3 commit=3 applied=3 latestCfgN=3
```

Every node — including `[0]` — has applied the commit and holds the 3-voter configuration,
yet the assertion still prints a 2-voter `peerSet`. A re-read would have returned 3 voters.
Raw log: `.runtime/audit/diag_inst.log` (4 failures/40).

### Causal isolation

Applying only the one-line correction in the diagnostic copy — moving the read inside the
loop — removes the failures:

```go
CHECK:
	peerSet := c.getConfiguration(c.rafts[0])   // re-read each iteration
```

Same test, same tree, 60×: `0` failures (`ok github.com/hashicorp/raft 20.362s`), log
`.runtime/audit/diag_fixed.log`. For comparison, the unmodified tree fails on the same
host: 5/40 (`.runtime/audit/diag_orig.log`), 4/40 (`.runtime/audit/diag_inst.log`), 9/40
(`.runtime/audit/stress_hasstate2.log`), and 5–9/40 in earlier runs. The self-contained
reproduction `.runtime/audit/repro_ensurepeers.sh` shows 6/40 failures unmodified vs 0/40
with the one-line fix.

### Alternative explanations checked

- "Slow/loaded machine, not a code bug": rejected. It is present at low load (nproc=4,
  loadavg < 1.2) and fails the *same* run where the state dump shows full convergence; a
  genuine slowness would show `latestCfgN=2` for node 0 at failure time.
- "Instrumentation/polling perturbs timing": the causal experiment keeps the same
  `EnsureSamePeers` structure and `WaitEvent` retry; the only change is *where* the
  snapshot is read, and that alone flips 4–9/40 to 0/60.
- "Injected/sabotaged helper": rejected — `testing.go` is byte-identical to authenticated
  upstream `v1.7.3` (next section). This is an upstream latent defect.
- "Bad test, not user-facing": `testing.go` is a normal package file (not `_test.go`);
  `MakeCluster` is exported and its value exposes `EnsureSamePeers`, so downstream suites
  can hit this. (Note the helper also only *ever* detects a raft[0]-lag scenario correctly
  by luck; the fix is to re-read.)

## Finding 2 (minor) — `EnsureSame` prints the wrong lengths in its config-mismatch error

In the same helper family, `testing.go:648-651` guards a *configuration* length mismatch
but prints *log* lengths:

```go
if len(first.configurations) != len(fsm.configurations) {
	fsm.Unlock()
	if time.Now().After(limit) {
		t.Fatalf("FSM configuration length mismatch: %d %d",
			len(first.logs), len(fsm.logs))   // <-- should be first.configurations / fsm.configurations
	} else {
```

Consequence: when a downstream cluster legitimately diverges in applied configurations,
the failure message reports two log lengths (often equal) instead of the two differing
configuration counts, making the diagnostic misleading. This is a defect in the reported
observation, not in the comparison logic (the guard itself uses the correct fields). It is
low severity and is included for completeness; the fix is to print
`len(first.configurations), len(fsm.configurations)`.

Reviewed and *not* defects: `EnsureSame`'s retry loop re-reads live FSM state under lock
each pass (`first` is a pointer), and `WaitForReplication` re-reads each FSM's log length
each pass, so neither has the Finding 1 staleness. `EnsureLeader` is a deliberate
single-shot check (no retry) but callers reach it via `c.Leader()`, which already waits for
a stable elected leader; no false failure was observed across the repeated full-suite runs.

## Suite-level flake hunt (executed)

To check whether any *other* test is intermittently failing, the full suite was run three
times back-to-back in the isolated netns (with `/etc/hosts` provisioned) skipping only the
known Finding 1 flake:

```
for i in 1 2 3; do go test -count=1 -skip '^TestRaft_HasExistingState$' ./...; done
--- run 1 ---  ok  github.com/hashicorp/raft  129.591s
--- run 2 ---  ok  github.com/hashicorp/raft  130.496s
--- run 3 ---  ok  github.com/hashicorp/raft  131.528s
```

All three passed. Combined with the single-run isolation result (only `TestRaft_HasExistingState`
failing), the observable intermittency is confined to the `EnsureSamePeers` defect; no other
flake surfaced in ~6.5 minutes of repeated full-suite execution. Raw output:
`executions/a362a7e1826e4d1594bdfba4fe50c069/stdout.txt`.

## Identity of the supplied source: authenticated, unmodified upstream v1.7.3

### Evidence chain

1. The run brief's `source_identity` is `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`.
   The module-cache metadata records that exact commit as `refs/tags/v1.7.3`:
   `{"Version":"v1.7.3",...,"Hash":"c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe","Ref":"refs/tags/v1.7.3"}`.
2. Every published-module file in the supplied tree is byte-identical to the extracted
   `v1.7.3` module zip: `diff -rq` empty, and SHA-256 manifests of all 66 files match
   (`supplied_manifest.sha256` == `authenticated_manifest.sha256`). `testing.go` is
   `IDENTICAL_TO_UPSTREAM`.
3. The module zip is authentic: a faithful reimplementation of
   `golang.org/x/mod/sumdb/dirhash.HashZip` (`.runtime/audit/hashcheck/main.go`) yields
   `h1:DxpEqZJysHN0wK+fviai5mFcSYsCkNpFUl1xpAW8Rbo=`, equal to the recorded `.ziphash`
   and to the **signed** `sum.golang.org` lookup record (verified against the tree-head
   signature in `.../sumdb/sum.golang.org/lookup/github.com/hashicorp/raft@v1.7.3`).

So there is no injected edit anywhere in the published module; Finding 1 is genuine
upstream `v1.7.3` behavior.

### Not covered

`fuzzy/` and `raft-compat/` are separate nested modules excluded from the published zip and
cannot be tied to the signed hash this way; neither builds offline here (missing
`raft-boltdb` zip and the `raft-previous-version` submodule). They are outside the audited
package. Spot-reading found nothing anomalous.

## Other behavioral checks (executed)

All raw logs are under `.runtime/audit/`; isolated runs are retained under `executions/`.

| # | Command | Result |
|---|---------|--------|
| 1 | `go build ./...` / `go vet ./...` | clean, exit 0 |
| 2 | `go test -count=1 -timeout 900s ./...` (restricted shell) | FAIL — socket/`localhost`-resolution errors plus `TestRaft_HasExistingState` (`gotest_all.log`) |
| 3 | `isolated_exec`: `sh -c "printf '127.0.0.1 localhost\n::1 localhost\n' > /etc/hosts; go test -count=1 -timeout 500s ./..."` | only `TestRaft_HasExistingState` fails; all net/TCP-transport and `runFollower` tests PASS (`executions/8f55023ad61a486e8ea61464502ef781/stdout.txt`) |
| 4 | `go test -run TestRaft_HasExistingState -count=40 .` (several times) | 4–9 failures each time (Finding 1) |
| 5 | isolated netns, `for i in 1 2 3; go test -count=1 -skip '^TestRaft_HasExistingState$' ./...` | all three runs `ok` — no other flaky test surfaced |

Notes on the non-Finding-1 signals:

- The socket tests in `net_transport_test.go`, `tcp_transport_test.go`, and `integ_test.go`
  (line 101: `NewTCPTransport("localhost:0", ...)`) need a listener plus `localhost`
  resolution. Restricted shell → `socket: operation not permitted`; isolated netns without
  `/etc/hosts` → `lookup localhost ... connection refused`. After provisioning `/etc/hosts`
  inside the isolated namespace they pass (run #3). Environment, not defect.
- `[ERROR] failed to install snapshot: ... failed to decode peers: msgpack decode error` is
  expected output from `TestRaft_InstallSnapshot_InvalidPeers` (`raft_test.go:2881`), which
  deliberately feeds `Peers: []byte("invalid msgpack")`.

## Unresolved work / next candidates

- Confirm Finding 1 against a pristine `v1.7.3` checkout and, if desired, file it upstream.
  The minimal fix is to move `peerSet := c.getConfiguration(c.rafts[0])` inside the
  `CHECK:` block so it is refreshed each retry.
- Sibling helpers in `testing.go` were reviewed for the stale-snapshot pattern: none has
  it (`EnsureSame` and `WaitForReplication` re-read live state each pass). `EnsureLeader`
  is single-shot by design. Remaining un-reviewed helpers: `GetInState`, `WaitForFollowers`,
  `Partition` (higher-level, not obviously data-dependent).
- Cryptographically compare `fuzzy/` and `raft-compat/` (blocked offline).
- Systematic semantics review of specific v1.7.3 algorithms (would report upstream issues).

## Reproduction artifacts (all under `work/`)

- `report.md` — this report.
- `.runtime/audit/repro.sh` — identity + behavior replay (hash, manifests, build, tests).
- `.runtime/audit/repro_ensurepeers.sh` — Finding 1 reproduction (unmodified vs fixed).
- `.runtime/audit/rp_unmodified.log`, `rp_fixed.log` — the above run (6/40 vs 0/40).
- `.runtime/audit/hashcheck/main.go` — recomputes the module zip `h1:` hash.
- `.runtime/audit/supplied_manifest.sha256`, `authenticated_manifest.sha256`; `work_files.txt`, `up_files.txt`.
- `.runtime/audit/gotest_all.log`, `gotest_skip.log`, `stress_hasstate.log`, `stress_hasstate2.log`.
- `.runtime/audit/diag/` — instrumented copy (source + `zz_diag_test.go` + `diagDump` in `testing.go`).
- `.runtime/audit/diag_inst.log` (unmodified helper, state dump at failure), `diag_orig.log` (unmodified, 5/40), `diag_fixed.log` (fixed variant, 0/60).
- `executions/8f55023ad61a486e8ea61464502ef781/stdout.txt` (and siblings) — isolated full-suite output.
