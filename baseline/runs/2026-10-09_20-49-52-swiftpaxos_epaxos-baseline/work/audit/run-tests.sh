#!/bin/bash
set -u
cd "$(dirname "$0")/.."
go test ./epaxos -run TestAudit -v -count=1 > audit/test-output.txt 2>&1
result=$?
cat audit/test-output.txt
printf '\ngo test exit status: %s\n' "$result"
exit "$result"
