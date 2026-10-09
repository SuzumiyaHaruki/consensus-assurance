# Consensus implementation audit

Source identity supplied by the run: `91180476b404beeb5326194e3fcdfa1758d4f222` (`go.etcd.io/raft/v3`). Captured source is read-only at `../source`. Tests use an unchanged copy of production files in `raft/`, adding only `audit_test.go`. Go version: `go1.26.7 linux/amd64`; dependencies are local and network fetching is disabled.

## Confirmed: documented zero message-size configuration panics on committed entry delivery

**Expected behavior.** `Config.MaxSizePerMsg` explicitly documents zero as “at most one entry per message” (`raft.go:187–192`). `MaxCommittedSizePerReady` can be left unset; validation defaults it to `MaxSizePerMsg`. A valid zero message-size configuration should therefore operate, including delivery of committed entries to the application.

**Affected code and cause.** `Config.validate`, `raft.go:318–320`, copies zero into `MaxCommittedSizePerReady`. This initializes `raftLog.maxApplyingEntsSize` to zero. `raftLog.nextCommittedEnts`, `log.go:232–235`, panics if its available size is zero, before using the normal size limiter that supports returning at least one entry. `RawNode.Ready` calls this path through `readyWithoutAccept` (`rawnode.go:146`).

**Conditions and observed result.** A singleton with a valid snapshot/hard state, `MaxSizePerMsg=0`, and omitted `MaxCommittedSizePerReady` successfully constructs and campaigns. After persistence/Advance commits its new leader entry, the next `Ready()` panics: `applying entry size (0-0)=0 not positive`. No malformed network message, custom Storage implementation, concurrent calls, or implementation modification is involved. This prevents normal application progress and crashes callers that do not recover the panic.

**Reproduction.** `repro/audit_test.go`, test `TestAuditZeroMaxSizePerMsg`, copied to `raft/audit_test.go`. From `work`:

```sh
GOCACHE=$PWD/.runtime/go-cache GOTMPDIR=$PWD/.runtime GOPROXY=off GOSUMDB=off go test -C raft -run '^TestAuditZeroMaxSizePerMsg$' -v .
```

The executed initial combined test command used `-run '^TestAudit'`; its full failing output and stack are preserved in `logs/audit-initial.txt`. The first panic terminates that command before the second test executes. A positive control with `MaxSizePerMsg=1` applies the leader entry successfully (`TestAuditPositiveMessageLimit`, `logs/snapshot-conf.txt`). A second control keeps `MaxSizePerMsg=0` and explicitly sets `MaxCommittedSizePerReady=1`; it also passes (`TestAuditZeroMessageWithExplicitApplyLimit`). These isolate the zero apply-limit default rather than invalid bootstrap or Ready/Advance ordering. Setting an explicit positive apply limit is a workaround for this configuration.

## Confirmed: outstanding configuration entry overwrites newer snapshot membership

**Expected behavior and supported ordering.** Once a snapshot at index 4 is installed and applied, Raft's membership must agree with its `Snapshot.Metadata.ConfState`. The application is required to call `ApplyConfChange` for committed configuration entries it receives (`README.md:120`, `178–183`, `node.go:179–187`). Network reception is separately passed to `Node.Step` (`README.md:126–131`). The `Node` goroutine continues accepting incoming messages while a previously delivered `Ready` awaits `Advance` (`node.go:399–407`). Thus a snapshot can arrive while the application is processing an older committed configuration entry.

**Affected code and cause.** `raft.restore`, `raft.go:1917–1932`, immediately installs the snapshot's configuration on receipt of `MsgSnap`, even when earlier committed configuration entries have already been handed out for application. Later `ApplyConfChange` has no index argument and unconditionally changes that current configuration (`raft.go:1947–1965`; `node.go:405–407`). When the application eventually receives and applies the snapshot Ready, `appliedSnap` (`raft.go:769–773`) only marks the snapshot stable/applied; it does not restore its configuration again. The obsolete configuration therefore persists.

**Executed reproduction.** A follower (ID 2) starts at snapshot index 1 with voters `{1,2,3}`. It receives and persists a committed index-2 entry adding voter 4, and holds that Ready before applying the entry. It then receives a snapshot at index 4 with voters `{1,2,3}` (the leader has subsequently removed voter 4). The application calls `ApplyConfChange` for the older index-2 entry, advances that Ready, and then installs/applies/advances the snapshot Ready in order. Its final applied index is 4, but its voter set is `{1,2,3,4}`, contradicting the snapshot. Both the serial `RawNode` reproduction and the goroutine-based `Node` reproduction exhibit the error.

**Controls and alternative explanations.** Applying the index-2 change before delivering the snapshot produces the correct final membership. No node ID is reused: the history adds new node 4, then removes it. All messages/log entries/snapshots in this reproduction use the same term 1; no election/log-prefix inconsistency is required. The snapshot is newer than the follower's last entry, so the actual snapshot-restore path is exercised, not commit fast-forwarding. The application obeys Ready order, persists entries/hard state before Advance, and calls ApplyConfChange exactly once. The Node test uses its public API and a Status barrier to make the interleaving deterministic, without concurrent access to RawNode internals. The snapshot and append messages are valid local fixtures; a complete cluster producing them has not been executed. The necessary leader-side add/remove history can commit through nodes 1, 3, and 4 while node 2 is behind. No cluster-wide safety violation is claimed; the observed local membership corruption is the finding.

**Impact.** The follower retains a removed voter and uses an incorrect configuration for later quorum/election decisions. It does not converge to the installed snapshot's configuration through ordinary snapshot Advance. Further configuration transitions or restart may change that state, but do not negate the demonstrated error.

**Reproduction files and commands.** Tests are in `repro/audit_test.go` (copied unchanged to `raft/audit_test.go`). From `work`:

```sh
GOCACHE=$PWD/.runtime/go-cache GOTMPDIR=$PWD/.runtime GOPROXY=off GOSUMDB=off go test -C raft -run '^TestAuditSnapshotOvertakesConfApply$' -v .
GOCACHE=$PWD/.runtime/go-cache GOTMPDIR=$PWD/.runtime GOPROXY=off GOSUMDB=off go test -C raft -run '^TestAuditNodeSnapshotOvertakesConfApply$' -v .
```

Executed output: `logs/snapshot-conf.txt` (includes the ordered control and positive message-limit control), and `logs/node-snapshot-conf.txt` (Node API). Both reproduction assertions fail on the original production code.

## Reproduction bundle and validation

Run `./repro/run.sh` from `work` (or invoke it by path). It adds only the retained test file to the source copy and executes each case separately so the panic cannot hide subsequent results. Full current outputs are in `logs/reproductions/`, with command exit statuses in `logs/reproductions/status.txt`. The three confirmed-defect reproduction tests fail; both limit controls pass; the snapshot test also has an ordered subtest that passes. The quota observation is deliberately run separately and remains unconfirmed as a supported-behavior finding.

All 162 captured source files were compared byte-for-byte against the working copy and are identical (`logs/source-integrity.txt`). The only added file in that copy is `audit_test.go`. No production or dependency edits were made.

The original test suite passed (`go test ./...`, before adding audit tests), output in `logs/baseline.txt`. Environment: `GOCACHE=$PWD/../.runtime/go-cache GOTMPDIR=$PWD/../.runtime GOPROXY=off GOSUMDB=off`, working directory `work/raft`.

## Unresolved work

See `notes.md` for the separately tracked quota-rejection observation and remaining investigation targets. It is not counted as a confirmed finding here.
