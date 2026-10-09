# Audit report — hashicorp/raft fixture (source identity c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe)

Run: `2026-10-09_12-07-16-hashicorp_raft-baseline`
Audited module: `github.com/hashicorp/raft` (Go), package `.`

## Bottom line

No concrete correctness defect attributable to the supplied implementation was found.

The supplied module is, byte-for-byte, the unmodified upstream release
`github.com/hashicorp/raft v1.7.3` (git tag commit
`c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`, which is exactly the `source_identity`
recorded in the run brief). I verified this against the *authenticated* module
content recorded by the Go checksum database, not merely against a local copy.
Consequently there is no injected/edited logic in the audited package to find: any
behavior it exhibits is upstream v1.7.3 behavior.

The only test that ever failed for a non-environmental reason is
`TestRaft_HasExistingState`, a timing-sensitive harness assertion that (a) passes in
isolation, (b) flakes only under CPU load, and (c) is present verbatim in pristine
upstream v1.7.3. It is a flaky test, not an implementation defect. Details and the
alternative explanations I checked are below.

## Scope, environment, permissions

- Working copy (writable): the run `work/` directory (a copy of the source tree with a fresh, empty `.git`).
- Read-only source: `runs/.../source` (identical to `work/`).
- Toolchain: Go 1.20 module, offline. `GOPROXY=off`, `GOSUMDB=off`, `GOMODCACHE=/home/nitro/go/pkg/mod`.
- The ordinary shell cannot open listening TCP sockets (`socket: operation not permitted`).
  The `isolated_exec` tool provides a private net/PID namespace with loopback; its root
  `/etc` is writable (no `/etc/hosts` by default, so `localhost` does not resolve there).
- The implementation and dependencies were not modified. All artifacts written by this
  audit live under `work/.runtime/audit/`, plus this report. Hash/identity computations
  and diagnostic logs are kept separate from the source.

## Finding: the audited source is authenticated, unmodified upstream v1.7.3

### Evidence chain

1. The run brief's `source_identity` is `c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe`.
   The module-cache metadata
   `.../cache/download/github.com/hashicorp/raft/@v/v1.7.3.info` records that exact
   commit as `refs/tags/v1.7.3`:
   ```
   {"Version":"v1.7.3","Time":"2025-03-18T17:46:02Z","Origin":{"VCS":"git",
    "URL":"https://github.com/hashicorp/raft",
    "Hash":"c0dc6a0b2c7e889f31e5ab2f7ed90ceb159acffe","Ref":"refs/tags/v1.7.3"}}
   ```
2. `diff -rq work/ <extracted v1.7.3 module> -x .git -x .runtime ...` reports no
   differences for the published module files (`DIFF_EXIT=0`). A SHA-256 manifest of all
   66 published files in `work/` is identical to the manifest of the extracted module zip:
   `.runtime/audit/supplied_manifest.sha256` vs `.runtime/audit/authenticated_manifest.sha256`
   → `MANIFESTS_IDENTICAL`.
3. The module zip itself is authentic: I recomputed its Go `h1:` hash from the zip bytes
   (`.runtime/audit/hashcheck/main.go`, a faithful reimplementation of
   `golang.org/x/mod/sumdb/dirhash.HashZip`), obtaining
   `h1:DxpEqZJysHN0wK+fviai5mFcSYsCkNpFUl1xpAW8Rbo=`.
   This equals both the recorded `.ziphash` and the entry in the **signed**
   checksum-database lookup record
   `.../cache/download/sumdb/sum.golang.org/lookup/github.com/hashicorp/raft@v1.7.3`:
   ```
   github.com/hashicorp/raft v1.7.3 h1:DxpEqZJysHN0wK+fviai5mFcSYsCkNpFUl1xpAW8Rbo=
   ...
   — sum.golang.org Az3grk9ctaTv+CITXOwxCEHU3APAw5X7Ck14+fvFlh0GCktwX15+XPzy//GgL2G50ZgY05e8eXFTWcvW6pN5tozsLQQ=
   ```

Because the sumdb record is signature-backed and its hash matches the bytes I hashed,
the zip is authentic upstream content; the supplied tree equals that zip byte-for-byte;
therefore the supplied module is authentic upstream v1.7.3. (This closes the loophole of
"the harness could have planted a matching local copy": forging the sumdb signature is
not feasible locally.)

### What is *not* covered by this chain

Two directories in the tree, `fuzzy/` and `raft-compat/`, are separate nested Go modules
and are deliberately excluded from the published module zip, so they cannot be tied to
the signed hash this way. They are test/support code (not the audited `execution_package`
`.`), and neither can be built offline here (`raft-boltdb` zip and the
`raft-previous-version` submodule are absent). A read of `fuzzy/node.go`,
`fuzzy/verifier.go` etc. shows ordinary upstream-looking code; nothing anomalous was
noticed. See "Unresolved work".

## Behavioral checks (executed)

All commands run from `work/`. Raw logs are retained next to this report.

| # | Command | Result |
|---|---------|--------|
| 1 | `go build ./...` | clean, exit 0 |
| 1b | `go vet ./...` | clean, exit 0 |
| 2 | `go test -count=1 -timeout 900s ./...` (restricted shell) | FAIL — only socket/`localhost`-resolution errors + `TestRaft_HasExistingState` (`.runtime/audit/gotest_all.log`) |
| 3 | `go test -count=1 -skip 'Network\|TCP\|TestRaft_HasExistingState' .` (restricted shell) | only remaining failures are `TestRaft_runFollower_*`, which open a TCP listener (`.runtime/audit/gotest_skip.log`) |
| 4 | `isolated_exec`: `sh -c "printf '127.0.0.1 localhost\n::1 localhost\n' > /etc/hosts; go test -count=1 -timeout 500s ./..."` | **only** `TestRaft_HasExistingState` fails; all net/TCP transport and `runFollower` tests PASS (retained: `executions/8f55023ad61a486e8ea61464502ef781/stdout.txt`) |
| 5 | `go test -run TestRaft_HasExistingState -count=40 .` (restricted shell) | 5/40 failures, identical signature (`.runtime/audit/stress_hasstate.log`); a later 40x run gave 4/40 — the count varies with load |
| 6 | `go test -run TestRaft_HasExistingState -count=1 -v .` | PASS (`.runtime/audit/` inline) |
| 7 | `bash .runtime/audit/repro.sh` | end-to-end replay of the identity + behavior checks (`.runtime/audit/repro.out`) |

### Interpreting the two non-clean signals

1. Socket tests. `net_transport_test.go`, `tcp_transport_test.go`, `integ_test.go`
   (line 101: `NewTCPTransport("localhost:0", ...)`) require a listening socket plus
   `localhost` name resolution. Restricted shell → `socket: operation not permitted`;
   isolated netns without `/etc/hosts` → `lookup localhost ... connection refused`.
   After provisioning `/etc/hosts` inside the isolated namespace, run #4 shows these
   tests pass. These were environment limitations, not defects.

2. `TestRaft_HasExistingState` (`raft_test.go:255`). It builds 2- and 1-node in-memory
   clusters, merges them, `AddVoter`s the 3rd node, then calls `EnsureSamePeers`
   (`testing.go:689`), which polls `GetConfiguration()` on every node and requires all
   configs to be `reflect.DeepEqual` before `longstopTimeout = 5s` (`testing.go:744`).
   The failure is always the same: the *first* node still reports the 2-old-voter
   configuration while another node already reports all 3 voters, i.e. one follower had
   not yet applied the committed `AddVoter` entry when the 5s deadline expired.

   - Alternative "genuine replication defect": rejected. The same binary/binary-content
     passes the test in isolation (run #6) and 35/40 times back-to-back (run #5); the
     failures cluster when the machine is saturated (run #2, #4, and the 40x stress).
     A real replication bug would fail deterministically, not only under contention.
     The `AddVoter` future returns success in every failing run, so the entry *was*
     committed; only a follower's applied-config lag exceeded the harness's fixed 5s
     window.
   - Alternative "injected defect": rejected by the identity chain — the test *and* the
     code under test are byte-identical to authenticated upstream v1.7.3.
   - Separately, the run-log line
     `[ERROR] failed to install snapshot: error="failed to decode peers: msgpack decode error ..."`
     is expected output: `TestRaft_InstallSnapshot_InvalidPeers` (`raft_test.go:2881`)
     deliberately feeds `Peers: []byte("invalid msgpack")` and asserts this error. It is
     not a defect.

## Conclusion

Within the authorized scope, the supplied `github.com/hashicorp/raft` package contains no
concrete correctness defect introduced relative to its stated identity: it is the
authenticated, unmodified upstream v1.7.3. The single non-environmental test failure is a
load-sensitive timing flake in the upstream test harness, not in the implementation.

## Unresolved work / next candidates

- Cryptographically compare the nested modules `fuzzy/` and `raft-compat/` against
  upstream. Not possible offline here (missing `raft-boltdb` zip and the
  `raft-previous-version` submodule). They are outside the audited package and outside
  the published module.
- If desired, add load-independent stress (e.g. `-count=200` while pinning fewer CPUs, or
  raising `longstopTimeout`) to characterize the `TestRaft_HasExistingState` flake more
  precisely, and confirm it reproduces against a pristine `v1.7.3` checkout — but this
  only characterizes an upstream test, not an implementation defect.
- No evidence of an injected fault was found in any published-module file; a fresh angle
  would be a semantics review of specific v1.7.3 algorithms, which would report upstream
  (not injected) issues.

## Reproduction artifacts (all under `work/`)

- `.runtime/audit/hashcheck/main.go` — recomputes the module zip `h1:` hash.
- `.runtime/audit/supplied_manifest.sha256`, `.runtime/audit/authenticated_manifest.sha256` — 66-file SHA-256 manifests.
- `.runtime/audit/work_files.txt`, `.runtime/audit/up_files.txt` — file inventories.
- `.runtime/audit/gotest_all.log`, `.runtime/audit/gotest_skip.log`, `.runtime/audit/stress_hasstate.log` — test logs.
- `executions/8f55023ad61a486e8ea61464502ef781/stdout.txt` (and sibling isolated runs) — isolated full-suite output.
- `.runtime/audit/repro.sh` — script that re-runs the checks above.
