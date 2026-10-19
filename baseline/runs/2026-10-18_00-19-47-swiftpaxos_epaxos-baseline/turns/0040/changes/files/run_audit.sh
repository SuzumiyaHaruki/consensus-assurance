#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"

# Captured-code finding suite (expected to fail).
go test ./epaxos -run TestAudit -v > audit_all_output.txt 2>&1
echo "epaxos finding suite exit=$? (nonzero expected)"

# Separate client and dlog failures.
go test ./client -run 'TestAuditFindClosestSkipsDeadReplica|TestAuditSendProposalToDeadClosestDoesNotPanic' -v \
  > audit_client_dead_closest_output.txt 2>&1
echo "client failover suite exit=$? (nonzero expected)"
go test ./dlog -run TestAuditNilLoggerDoesNotPanic -v \
  > audit_nil_logger_output.txt 2>&1
echo "dlog nil-logger suite exit=$? (nonzero expected)"

# Controls and investigations.
go test ./epaxos -run TestAuditClusterRandomNormalCampaign -v \
  > audit_cluster_random_output.txt 2>&1
echo "random normal-path control exit=$? (zero expected)"
go test ./epaxos -run TestInvestigationRandomFaultCampaign -v \
  > audit_random_fault_output.txt 2>&1
echo "random fault investigation exit=$? (nonzero expected)"

# Build and confirm the captured implementation is untouched.
go build ./... && echo "build_ok"
diff -q ../source/epaxos/epaxos.go epaxos/epaxos.go &&
  diff -q ../source/epaxos/defs.go epaxos/defs.go &&
  diff -q ../source/epaxos/exec.go epaxos/exec.go &&
  diff -q ../source/client/client.go client/client.go &&
  diff -q ../source/dlog/dlog.go dlog/dlog.go &&
  echo "captured_implementation_unchanged"
