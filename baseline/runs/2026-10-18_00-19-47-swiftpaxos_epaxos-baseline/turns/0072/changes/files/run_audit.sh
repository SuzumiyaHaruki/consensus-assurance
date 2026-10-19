#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"

# Captured-code finding suite (expected to fail).
go test ./epaxos -run TestAudit -v > audit_all_output.txt 2>&1
echo "epaxos finding suite exit=$? (nonzero expected)"
epaxos_fails=$(grep -c '^--- FAIL' audit_all_output.txt)
epaxos_passes=$(grep -c '^--- PASS' audit_all_output.txt)
if [ "$epaxos_fails" -ne 40 ] || [ "$epaxos_passes" -ne 5 ]; then
  echo "UNEXPECTED epaxos counts: $epaxos_fails failures, $epaxos_passes passes (expected 40/5)"
  exit 1
fi
echo "epaxos finding/control counts 40/5 (expected)"

# Separate client and dlog failures.
go test ./client -run 'TestAuditFindClosestSkipsDeadReplica|TestAuditSendProposalToDeadClosestDoesNotPanic' -v \
  > audit_client_dead_closest_output.txt 2>&1
echo "client failover suite exit=$? (nonzero expected)"
go test ./dlog -run TestAuditNilLoggerDoesNotPanic -v \
  > audit_nil_logger_output.txt 2>&1
echo "dlog nil-logger suite exit=$? (nonzero expected)"
go test ./config -run TestAuditNilProxyDoesNotPanic -v \
  > audit_nil_proxy_output.txt 2>&1
echo "config nil-proxy suite exit=$? (nonzero expected)"

# Controls and investigations.
go test ./epaxos -run TestAuditClusterRandomNormalCampaign -v \
  > audit_cluster_random_output.txt 2>&1
echo "random normal-path control exit=$? (zero expected)"
go test ./epaxos -run TestInvestigationRandomFaultCampaign -v \
  > audit_random_fault_output.txt 2>&1
echo "random fault investigation exit=$? (nonzero expected)"
AUDIT_FAULT_SEEDS=500 go test ./epaxos -run TestInvestigationRandomFaultCampaign -v \
  > audit_random_fault_500_output.txt 2>&1
echo "extended 500-seed fault sweep exit=$? (nonzero expected)"
AUDIT_FAULT_SEEDS=1000 go test ./epaxos -run TestInvestigationRandomFaultCampaign -v \
  > audit_random_fault_1000_output.txt 2>&1
echo "extended 1,000-seed fault sweep exit=$? (nonzero expected)"

# Build and confirm the captured implementation is untouched.
go build ./... && echo "build_ok"
diff -q ../source/epaxos/epaxos.go epaxos/epaxos.go &&
  diff -q ../source/epaxos/defs.go epaxos/defs.go &&
  diff -q ../source/epaxos/exec.go epaxos/exec.go &&
  diff -q ../source/client/client.go client/client.go &&
  diff -q ../source/dlog/dlog.go dlog/dlog.go &&
  diff -q ../source/config/proxy.go config/proxy.go &&
  diff -q ../source/config/config.go config/config.go &&
  echo "captured_implementation_unchanged"
