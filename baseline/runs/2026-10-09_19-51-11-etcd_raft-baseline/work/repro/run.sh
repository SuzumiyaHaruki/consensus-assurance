#!/bin/bash
# Run from any directory. Production code is copied verbatim; only tests added.
set -eu
cd "$(dirname "$0")/.."
if [ ! -d raft ]; then
    cp -a ../source raft
    chmod -R u+w raft
fi
mkdir -p .runtime logs/reproductions
export GOCACHE="$PWD/.runtime/go-cache"
export GOTMPDIR="$PWD/.runtime"
export GOPROXY=off GOSUMDB=off
cp repro/audit_test.go raft/audit_test.go
: > logs/reproductions/status.txt
for test in TestAuditZeroMaxSizePerMsg TestAuditPositiveMessageLimit TestAuditZeroMessageWithExplicitApplyLimit TestAuditSnapshotOvertakesConfApply TestAuditNodeSnapshotOvertakesConfApply TestAuditRejectedConfChangePoisonsRetry; do
    status=0
    go test -C raft -count=1 -timeout=30s -run "^${test}$" -v . > "logs/reproductions/${test}.txt" 2>&1 || status=$?
    printf '%s exit=%s\n' "$test" "$status" | tee -a logs/reproductions/status.txt
done
