# Executed commands

Run from the working tree with the provided offline environment (`GOPROXY=off`, `GOSUMDB=off`, `GOFLAGS=-mod=readonly`). Toolchain: `go version go1.25.8 linux/amd64`.

```sh
go test -run '^TestAuditVerifyLeaderNonvoter$' -count=1 -v . > audit-results/verify-leader.txt 2>&1
go test -run '^TestAuditInterruptedVotePersistence$' -count=1 -v . > audit-results/interrupted-vote.txt 2>&1
```

Both commands deliberately fail their regression assertions on the supplied implementation. Their paired negative controls pass. No implementation or dependency modifications are used.

Additional validation:

```sh
go test -race -run '^TestAudit(VerifyLeaderNonvoter|InterruptedVotePersistence)$' -count=3 -v . > audit-results/repeated-race.txt 2>&1
```

For the TCP heartbeat test, execute the following **inside the authorized `isolated_exec` private network namespace**, from the working tree:

```sh
go test -race -run '^TestAuditConcurrentHeartbeatTermRegression$' -count=3 -v . > audit-results/heartbeat-term.txt 2>&1
go test -race -run '^TestAuditConcurrentHeartbeatTermRegression$' -count=1 -v . > audit-results/heartbeat-term-control.txt 2>&1
```

The second command was run after adding a sequential-request control to the test. Isolated execution IDs: `bad0c05b0e4b472faba0bcfa67aedfcd` and `4d69acf0251a491c9a12b1dd64f8aea2`. Both deliberately exit 1 for the term monotonicity assertion; the sequential control passes. No race-detector reports occurred.

An earlier test harness had `defer node.Shutdown().Error()`, which evaluated `Shutdown()` immediately. That attempt timed out without exercising the defect. Its log is retained in `heartbeat-term-initial-harness-error.txt`; the corrected harness uses a deferred closure. Initial isolated execution: `e66627be26ff48a381d31c35275b997c`.
