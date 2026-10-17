#!/usr/bin/env bash
# Audit reproduction driver (added by the auditor; the report is work/report.md).
#
# Runs every audit test file against the *unmodified* captured source and prints a summary,
# then re-runs the finding-1 repros against the diagnostic copy that carries the candidate fix.
# Expected outcome, for the record:
#   finding 1 file      2 passed / 6 failed   (the 2 passes are the controls)
#   finding 2 file      0 passed / 2 failed
#   StopSign probe      1 passed / 0 failed   (negative result)
#   core probes         4 passed / 1 failed   (the failure is the deterministic finding-3 repro)
#   diag copy (fixes)   8 passed / 0 failed and 2 passed / 0 failed
#   captured runtime    24 passed / 0 failed
#
# The two lines marked "isolated executor" (captured core suite, recovery tests) need a private
# network namespace because kompact binds TCP sockets; everything else runs anywhere.
set -u
cd "$(dirname "$0")"
export CARGO_NET_OFFLINE=true

run() {
    local label="$1"; shift
    local out
    out="$("$@" 2>&1 | grep -E '^test result|^error' | tail -2 | tr '\n' ' ')"
    printf '  %-46s %s\n' "$label" "${out:-<no test result>}"
}

echo "=== audit test files, unmodified captured source ==="
run "finding 1: append_notify index" \
    cargo test -p omnipaxos_runtime --features tokio_runtime --test audit_batch_alignment_test
run "finding 2: compacted subscription" \
    cargo test -p omnipaxos_runtime --features tokio_runtime --test audit_subscription_compaction_test
run "negative: StopSign boundary" \
    cargo test -p omnipaxos_runtime --features tokio_runtime --test audit_reconfiguration_boundary_test
run "finding 3 + negatives: core probes" \
    cargo test -p omnipaxos --features "logging,toml_config" --test audit_leader_change_adoption_test

echo
echo "=== candidate fix for finding 1 (applied only in the diagnostic copy) ==="
pushd diag/omnipaxos_runtime >/dev/null
run "diagnostic copy: all 8 expected to pass" \
    cargo test --features tokio_runtime --test audit_batch_alignment_test
run "diagnostic copy: finding 2 repros expected to pass" \
    cargo test --features tokio_runtime --test audit_subscription_compaction_test
popd >/dev/null

echo
echo "=== captured runtime suite (green baseline) ==="
run "captured async_runtime_test" \
    cargo test -p omnipaxos_runtime --features tokio_runtime --test async_runtime_test

echo
echo "=== need the isolated executor (private netns; kompact binds TCP) ==="
echo "  cargo test -p omnipaxos --features \"logging,toml_config\" --no-fail-fast"
echo "  cargo test -p omnipaxos --features \"logging,toml_config\" --test recovery_test -- --ignored"
echo
echo "See work/report.md for the findings, mechanisms, log references and open questions."
