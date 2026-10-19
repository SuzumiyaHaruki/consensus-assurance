#!/usr/bin/env bash
# Reproduce the audit findings against the unmodified package.
# The audit tests are expected to fail; the controls are expected to pass.
set -u

cd "$(dirname "$0")"
mkdir -p audit_results

run() {
  local name=$1
  go test -run "^${name}$" -v . >"audit_results/${name}.txt" 2>&1
  local status=$?
  echo "${name}: exit=${status}"
}

run TestAuditRestoreCommittedLogsKeepsConfiguration
run TestAuditRestoreCommittedLogsConformingStore
run TestAuditGetConfigurationRestoreCommittedLogs
run TestAuditRestoreCommittedLogsSnapshotStaleMembership
run TestAuditRestoreCommittedLogsSingleNodeRestart
run TestAuditRestoreCommittedLogsAllVotersRestart
run TestAuditRestoreCommittedLogsLargeLogStartup
run TestAuditRestoreCommittedLogsBelowChannelCapacity
run TestAuditRestoreCommittedLogsDisabledKeepsConfiguration
run TestAuditRestoreCommittedLogsReplaysPostSnapshotCommands
run TestAuditCommitIndexPersistenceOnHeartbeatOnlyCommit
run TestAuditLogCacheDoesNotPreserveCommitTracking
run TestAuditCommitIndexBelowSnapshotAfterRestart
run TestAuditStaleSnapshotConfigElectsWithoutCommittedVoter
run TestAuditStaleConfigAllowsConflictingCommits
run TestAuditRealClusterStaleConfigConflict
run TestAuditRealClusterLargeLogRestartHangs

go test -run TestAudit -v . >audit_results/all_audit_tests.txt 2>&1
echo "combined: exit=$?"
