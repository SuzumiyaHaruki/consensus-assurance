# Retained audit artifacts

- `../report.md`: confirmed findings and evidence limitations.
- `../epaxos/audit*_test.go`: tests added alongside unchanged implementation.
- `run-tests.sh`: reproducible command; returns 1 when defect assertions fail.
- `test-output.txt`: latest actual Go test output (eight failing tests).
- `source-sha256.txt`: scoped original implementation file hashes.
- `source-verification.txt`: successful check against the hash manifest.
- `recovery-output.txt`, `liveness-output.txt`, `order-output.txt`: targeted observed runs.
- `unresolved.md`: unconfirmed leads and remaining work.

Environment used: Go 1.23.5, Linux amd64, offline module cache, GOFLAGS=-mod=readonly. No dependency changes or network access required. For a fresh source copy, add the epaxos/audit*_test.go files and run `go test ./epaxos -run TestAudit -v -count=1` at the module root. Fixtures use N=3/F=1 or N=5/F=2, with thriftiness enabled. The suite intentionally fails on the captured implementation.
