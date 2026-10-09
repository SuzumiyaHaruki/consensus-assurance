# Retained audit artifacts

- `../report.md`: confirmed findings and evidence limitations.
- `../epaxos/audit_test.go`: tests added alongside unchanged implementation.
- `run-tests.sh`: reproducible command; returns 1 when defect assertions fail.
- `test-output.txt`: latest actual Go test output (four failing tests).
- `source-sha256.txt`: scoped original implementation file hashes.
- `source-verification.txt`: successful check against the hash manifest.
- `unresolved.md`: unconfirmed leads and remaining work.

Environment used: Go 1.23.5, Linux amd64, offline module cache, GOFLAGS=-mod=readonly. No dependency changes or network access required. For a fresh source copy, add only epaxos/audit_test.go and run `go test ./epaxos -run TestAudit -v -count=1` at the module root. All fixtures use N=3/F=1 and thriftiness enabled. The suite intentionally fails on the captured implementation.
