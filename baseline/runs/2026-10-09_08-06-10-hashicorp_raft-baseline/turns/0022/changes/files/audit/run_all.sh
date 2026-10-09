#!/usr/bin/env bash
# Reproduce the audit evidence for the hashicorp/raft (baseline) run.
#
# Usage:  bash audit/run_all.sh
# Run from the working directory (the module root). Writes logs next to itself.
#
# Notes:
#  - Loopback TCP is unavailable in this sandbox, so the TCP-backed package
#    tests (net_transport/tcp_transport/integ) cannot run here and are expected
#    to fail with "socket: operation not permitted".
#  - The last step intentionally crashes the test process to demonstrate F1
#    end-to-end; a non-zero exit / "panic:" is the EXPECTED result.
set -u
cd "$(dirname "$0")/.." || exit 1
export GOFLAGS=-mod=readonly GOTOOLCHAIN=local
SRC=$(cd "$(dirname "$0")/../../source" 2>/dev/null && pwd)
REF=/home/nitro/go/pkg/mod/github.com/hashicorp/raft@v1.7.3

echo "### 1. provenance: source vs upstream module (expect: only fuzzy/ and dotfiles differ)"
if [ -n "${SRC:-}" ] && [ -d "$REF" ]; then
  diff -rq --exclude=.git --exclude=.runtime --exclude=.github --exclude=raft-compat "$REF" "$SRC" || true
else
  echo "  (skipped: reference or source path unavailable)"
fi

echo; echo "### 2. go vet"
go vet ./... 2>&1 | head

echo; echo "### 3. malformed-input panic battery (expect 3 PANIC lines + 4 handled controls)"
go test -count=1 -timeout 120s -run 'TestAudit_MalformedRPCByteBattery$' -v . 2>&1 | grep -E 'RUN|PANIC|handled|PASS|FAIL'

echo; echo "### 4. F1 direct-call panic (expect REPRODUCED ...)"
go test -count=1 -timeout 120s -run 'TestAudit_InstallSnapshot_MalformedConfigurationPanics$' -v . 2>&1 | grep -E 'REPRODUCED|PASS|FAIL'

echo; echo "### 5. F2 unknown-log-type panic (expect REPRODUCED ...)"
go test -count=1 -timeout 120s -run 'TestAudit_AppendEntries_UnknownLogTypePanics$|TestAudit_F2_ReachableViaProcessRPC$' -v . 2>&1 | grep -E 'REPRODUCED|PASS|FAIL'

echo; echo "### 6. benign-flake + durability + consistency (expect all PASS)"
go test -count=1 -timeout 600s -run 'TestAudit_ConfigConvergenceLag$|TestAudit_RandomizedConsistency$|TestAudit_RestartRecovery$' -v . 2>&1 | grep -E 'SUMMARY|--- PASS|--- FAIL|^ok|^FAIL'

echo; echo "### 7. F1 end-to-end crash (EXPECTED to abort the process with a panic)"
RAFT_AUDIT_CRASH=1 go test -count=1 -timeout 60s -run 'TestAudit_InstallSnapshot_NetworkCrash$' . 2>&1 | grep -E 'panic:|FAIL|ok ' | head

echo; echo "done."
