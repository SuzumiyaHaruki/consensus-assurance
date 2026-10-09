# Continuing audit notes

## Executed but not promoted: rejected configuration proposal bookkeeping

`TestAuditRejectedConfChangePoisonsRetry` in `repro/audit_test.go`; output `logs/confchange-retry.txt`. Command from work:

```
GOCACHE=$PWD/.runtime/go-cache GOTMPDIR=$PWD/.runtime GOPROXY=off GOSUMDB=off go test -C raft -run '^TestAuditRejectedConfChangePoisonsRetry$' -v .
```

The leader sets `pendingConfIndex` before `appendEntry` checks the uncommitted-size quota (`raft.go:1335`, `1341`). Rejection leaves it pointing beyond the log. After quota drains, retry is replaced with an empty normal entry due to phantom pending configuration. The next retry after applying that no-op can recover. The API explicitly allows silent drops (`node.go:141–146`), so this is weak as a standalone supported-behavior violation. Do not claim permanent deadlock or safety failure.

## Potential next investigations (not findings)

- Async storage response ordering and snapshot/config application interaction beyond the confirmed synchronous Node case.
- Joint configuration auto-leave when leadership transfer fails without subsequent application activity.
- Read-index handling across configuration changes and empty contexts. API allows request drops and requires fresh contexts on retry; account for those documented limits.
- MemoryStorage boundary/error contracts and concurrent initialization are lower priority; avoid treating malformed input or unsupported call ordering as consensus bugs.

## Experiment refinements / setup

- Initial baseline invocation incorrectly pointed the Go cache under the copied read-only directory. Corrected to work/.runtime; original suite then passed. Production copy file modes were made writable, but production contents were not edited.
- Snapshot fixtures were refined before retention to use an add-then-remove history (no node-ID reuse) and a single term throughout. Current tests and retained final outputs reflect that valid history.
- No diagnostic modification to production code has been used.
