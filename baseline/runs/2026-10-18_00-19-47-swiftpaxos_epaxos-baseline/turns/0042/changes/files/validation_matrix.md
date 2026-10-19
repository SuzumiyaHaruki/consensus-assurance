# Validation matrix

The captured implementation is `work/` (`35c69365...`); all tests below run
against it unless marked diagnostic.  Expected failing finding tests are run
with `go test ./epaxos -run TestAudit -v` (34 failures, 4 controls).  Client
tests are separate because EPaxos is leaderless and they exercise the client
failover path.

| Finding | Decisive tests | Captured output |
|---------|----------------|-----------------|
| F1 local PrepareReply masks remote values | `TestAuditRecoveryDoesNotDiscardCommittedRemoteValue`, `TestAuditRecoveryLocalReplyKeepsValueBallot`, `TestAuditRecoveryPrefersRemoteCommittedOverLocalPreaccepted`, `TestAuditRecoveryMatrix`, `TestAuditClusterRecoveryStalls`, `TestAuditClusterChosenValueSurvivesLeaderCrash`, `TestAuditClusterSlowPathChosenValueSurvivesLeaderCrash`, `TestAuditClusterPartitionedLeaderKeepsChosenValue`, `TestAuditClusterRecovererMatrix` | `audit_recovery_safety_output.txt`, `audit_recovery_local_value_output.txt`, `audit_recovery_matrix_output.txt`, `audit_cluster_recovery_output.txt`, `audit_cluster_chosen_output.txt`, `audit_cluster_slow_chosen_output.txt`, `audit_cluster_partitioned_output.txt`, `audit_cluster_recoverer_matrix_output.txt` |
| F2 PrepareReply VBallot codec loss | `TestAuditRPCCodecRoundTrip`, `TestAuditPrepareRepliesPreserveValueBallotOrdering` | `audit_all_output.txt`, `audit_codec_recovery_output.txt` |
| F3 batched dependency loss | `TestAuditUpdateAttributesConsidersWholeBatch`, `TestAuditBatchedProposalUsesNewestDependency` | `audit_batch_output.txt`, `audit_batch_flow_output.txt` |
| F4 command-holding acceptor status | `TestAuditAcceptWithCommandMarksAccepted`; no-command investigation: `TestInvestigationAcceptStatus` | `audit_accept_command_output.txt`, `audit_accept_status_output.txt` |
| F5 PreAccept wrong row / panic | `TestAuditPreAcceptStoresCommandInAddressedInstance`, `TestAuditPreAcceptOutOfPlaceStoreDoesNotPanic` | `audit_all_output.txt` |
| F6 TryPreAccept wrong VBallot | `TestAuditTryPreAcceptRecordsVBallot` | `audit_test_output.txt` |
| F7 unreachable AcceptReply nack | `TestAuditAcceptReplyCountsHigherBallotAsNack` | `audit_test_output.txt` |
| F8 Commit nil bookkeeping panic | `TestAuditCommitForUnknownOwnInstanceDoesNotPanic` | `audit_extra_output.txt` |
| F9 durable metadata layout | `TestAuditDurableMetadataLayout` | `audit_extra_output.txt` |
| F10 dead defer-cycle guard | source review (`possibleQuorum` indexing) | report F10 |
| F11 reply robustness / retry omissions | source review | report F11 |
| F12 ConflictStatus always NONE | `TestAuditTryPreAcceptReportsConflictStatus` | `audit_tpa_status_output.txt` |
| F13 N=7 slow-path threshold | `TestAuditSlowPathStartsWithMajority`, `TestAuditClusterN7FailureStalls` | `audit_slowpath_output.txt`, `audit_cluster_n7_output.txt` |
| F14 higher-VBallot reply blocks round | `TestAuditHigherVBallotReplyDoesNotBlockFurtherReplies`, cluster recovery | `audit_higher_vbal_output.txt`, `audit_cluster_recovery_output.txt` |
| F15 fast commit misses vbal | `TestAuditFastCommitRecordsValueBallot` | `audit_fast_vbal_output.txt` |
| F16 startup `defs.IP` panic | `TestAuditIPHelperDoesNotPanic`, `TestAuditReplicaConstructionDoesNotRequireExternalRoute` | `audit_ip_output.txt`, `audit_startup_output.txt` |
| F17 recovery misses conflict table | `TestAuditTryPreAcceptUpdatesConflicts`, `TestAuditPrepareReplyUpdatesConflicts`, `TestAuditPrepareReplyConflictMiss` | `audit_tpa_conflicts_output.txt`, `audit_prepare_conflicts_output.txt`, `audit_prepare_conflict_miss_output.txt` |
| F18 oversized command truncation | `TestAuditLargeCommandRoundTrip`, `TestAuditLargeProposeRoundTrip` | `audit_large_command_output.txt`, `audit_large_propose_output.txt` |
| F19 client ClosestId fallback | `TestAuditFindClosestSkipsDeadReplica`, `TestAuditSendProposalToDeadClosestDoesNotPanic` (`./client`) | `audit_client_closest_output.txt`, `audit_client_dead_closest_output.txt` |
| F20 recovery Commit old ballot | `TestAuditRecoveryCommitUsesCurrentBallot`; diagnostic cluster validation | `audit_recovery_commit_output.txt`, `diagnostic_fix_output.txt`, `diagnostic_fix2_output.txt` |
| F21 sub-case 1 no Commit broadcast | `TestAuditPrepareReplySubcase1PropagatesCommit` | `audit_prepare_subcase1_output.txt` |
| F22 nil dlog.Logger fallback | `TestAuditNilLoggerDoesNotPanic` (`./dlog`) | `audit_nil_logger_output.txt` |
| F23 nil ProxyInfo config path | `TestAuditNilProxyDoesNotPanic` (`./config`) | `audit_nil_proxy_output.txt` |

## Controls

| Control | Result |
|---------|--------|
| `TestAuditClusterHappyPath` | pass |
| `TestAuditClusterConflictPath` | pass |
| `TestAuditClusterShuffledNormalPath` | pass |
| `TestAuditClusterShuffledSeeds` (1-20) | pass |
| `TestAuditClusterRandomNormalCampaign` (50 random mixes) | pass |
| `-count=3` controls | pass |

Randomized fault investigation: `TestInvestigationRandomFaultCampaign`
(20 fixed seeds) reports 11 pass, 9 NOOP losses, and 0 mixed-value
divergences; see `audit_random_fault_output.txt`.  It corroborates F1 but does
not independently establish chosen-value loss.

## Diagnostic copies

`diagnostic_fix/` changes only the local `PrepareReply.VBallot`;
`diagnostic_fix2/` additionally changes the Commit ballot.  These are separate
copies, not the captured implementation.  The two-line copy has 11 passing
tests (controls plus the recovery/chosen cases) and 25 remaining failures;
see `diagnostic_fix2_all_output.txt`.
