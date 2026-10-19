# Validation matrix

The captured implementation is `work/` (`35c69365...`); all tests below run
against it unless marked diagnostic.  Expected failing finding tests are run
with `go test ./epaxos -run TestAudit -v` (41 failures, 5 controls).  Client
tests are separate because EPaxos is leaderless and they exercise the client
failover path.

| Finding | Decisive tests | Captured output |
|---------|----------------|-----------------|
| F1 local PrepareReply masks remote values | `TestAuditRecoveryDoesNotDiscardCommittedRemoteValue`, `TestAuditRecoveryLocalReplyKeepsValueBallot`, `TestAuditRecoveryPrefersRemoteCommittedOverLocalPreaccepted`, `TestAuditRecoveryMatrix`, `TestAuditClusterRecoveryStalls`, `TestAuditClusterChosenValueSurvivesLeaderCrash`, `TestAuditClusterSlowPathChosenValueSurvivesLeaderCrash`, `TestAuditClusterPartitionedLeaderKeepsChosenValue`, `TestAuditClusterCommittedMajorityRecoveryDiverges`, `TestAuditClusterRecovererMatrix` | `audit_recovery_safety_output.txt`, `audit_recovery_local_value_output.txt`, `audit_recovery_matrix_output.txt`, `audit_cluster_recovery_output.txt`, `audit_cluster_chosen_output.txt`, `audit_cluster_slow_chosen_output.txt`, `audit_cluster_partitioned_output.txt`, `audit_cluster_majority_divergence_output.txt`, `audit_cluster_recoverer_matrix_output.txt` |
| F2 PrepareReply VBallot codec loss | `TestAuditRPCCodecRoundTrip`, `TestAuditPrepareRepliesPreserveValueBallotOrdering` | `audit_all_output.txt`, `audit_codec_recovery_output.txt` |
| F3 batched dependency loss | `TestAuditUpdateAttributesConsidersWholeBatch`, `TestAuditBatchedProposalUsesNewestDependency`; `diagnostic_fix6/` validates the break removal | `audit_batch_output.txt`, `audit_batch_flow_output.txt`, `diagnostic_fix6_output.txt` |
| F4 command-holding acceptor status | `TestAuditAcceptWithCommandMarksAccepted`; `diagnostic_fix9/` validates the command-holding fix; no-command investigation: `TestInvestigationAcceptStatus` | `audit_accept_command_output.txt`, `audit_accept_status_output.txt`, `diagnostic_fix9_output.txt` |
| F5 PreAccept wrong row / panic | `TestAuditPreAcceptStoresCommandInAddressedInstance`, `TestAuditPreAcceptOutOfPlaceStoreDoesNotPanic`; `diagnostic_fix9/` validates | `audit_all_output.txt`, `diagnostic_fix9_output.txt` |
| F6 TryPreAccept wrong VBallot | `TestAuditTryPreAcceptRecordsVBallot`; `diagnostic_fix9/` validates | `audit_test_output.txt`, `diagnostic_fix9_output.txt` |
| F7 unreachable AcceptReply nack | `TestAuditAcceptReplyCountsHigherBallotAsNack`; `diagnostic_fix9/` validates | `audit_test_output.txt`, `diagnostic_fix9_output.txt` |
| F8 Commit nil bookkeeping panic | `TestAuditCommitForUnknownOwnInstanceDoesNotPanic`; `diagnostic_fix9/` validates | `audit_extra_output.txt`, `diagnostic_fix9_output.txt` |
| F9 durable metadata layout | `TestAuditDurableMetadataLayout`; `diagnostic_fix10/` validates | `audit_extra_output.txt`, `diagnostic_fix10_output.txt` |
| F10 dead defer-cycle guard | `TestAuditTryPreAcceptBreaksDeferCycle`; `diagnostic_fix12/` validates the guard | `audit_defer_cycle_output.txt`, `diagnostic_fix12_output.txt`, `diagnostic_fix12_all_output.txt` |
| F11 reply robustness / retry omissions | `TestAuditReplyHandlersUnknownInstanceDoNotPanic`, `TestAuditPrepareReplyHigherBallotRetriesRecovery`; `diagnostic_fix11/` validates both fixes | `audit_unknown_reply_output.txt`, `audit_prepare_retry_output.txt`, `diagnostic_fix11_output.txt`, `diagnostic_fix11_all_output.txt` |
| F12 ConflictStatus always NONE | `TestAuditTryPreAcceptReportsConflictStatus`; `diagnostic_fix7/` validates the fix | `audit_tpa_status_output.txt`, `diagnostic_fix7_output.txt` |
| F13 N=7 slow-path threshold | `TestAuditSlowPathStartsWithMajority`, `TestAuditClusterN7FailureStalls`; `diagnostic_fix8/` validates the threshold fix | `audit_slowpath_output.txt`, `audit_cluster_n7_output.txt`, `diagnostic_fix8_output.txt` |
| F14 higher-VBallot reply blocks round | `TestAuditHigherVBallotReplyDoesNotBlockFurtherReplies`, cluster recovery; `diagnostic_fix4/` validates the guard (with F24 persistence caveat) | `audit_higher_vbal_output.txt`, `audit_cluster_recovery_output.txt`, `diagnostic_fix4_f14_output.txt` |
| F15 fast commit misses vbal | `TestAuditFastCommitRecordsValueBallot`; `diagnostic_fix9/` validates | `audit_fast_vbal_output.txt`, `diagnostic_fix9_output.txt` |
| F16 startup `defs.IP` panic | `TestAuditIPHelperDoesNotPanic`, `TestAuditReplicaConstructionDoesNotRequireExternalRoute`; `diagnostic_fix10/` validates | `audit_ip_output.txt`, `audit_startup_output.txt`, `diagnostic_fix10_output.txt` |
| F17 recovery misses conflict table | `TestAuditTryPreAcceptUpdatesConflicts`, `TestAuditPrepareReplyUpdatesConflicts`, `TestAuditPrepareReplyConflictMiss`; `diagnostic_fix7/` validates the fix | `audit_tpa_conflicts_output.txt`, `audit_prepare_conflicts_output.txt`, `audit_prepare_conflict_miss_output.txt`, `diagnostic_fix7_output.txt` |
| F18 oversized command truncation | `TestAuditLargeCommandRoundTrip`, `TestAuditLargeProposeRoundTrip`; `diagnostic_fix10/` validates 32-bit length | `audit_large_command_output.txt`, `audit_large_propose_output.txt`, `diagnostic_fix10_output.txt` |
| F19 client ClosestId fallback | `TestAuditFindClosestSkipsDeadReplica`, `TestAuditSendProposalToDeadClosestDoesNotPanic` (`./client`); `diagnostic_fix10/` validates | `audit_client_closest_output.txt`, `audit_client_dead_closest_output.txt`, `diagnostic_fix10_output.txt` |
| F20 recovery Commit old ballot | `TestAuditRecoveryCommitUsesCurrentBallot`; diagnostic cluster validation | `audit_recovery_commit_output.txt`, `diagnostic_fix_output.txt`, `diagnostic_fix2_output.txt` |
| F21 sub-case 1 no Commit broadcast | `TestAuditPrepareReplySubcase1PropagatesCommit` | `audit_prepare_subcase1_output.txt` |
| F22 nil dlog.Logger fallback | `TestAuditNilLoggerDoesNotPanic` (`./dlog`); `diagnostic_fix10/` validates | `audit_nil_logger_output.txt`, `diagnostic_fix10_output.txt` |
| F23 nil ProxyInfo config path | `TestAuditNilProxyDoesNotPanic` (`./config`); `diagnostic_fix10/` validates | `audit_nil_proxy_output.txt`, `diagnostic_fix10_output.txt` |
| F24 restart reuses committed instance number | `TestAuditClusterRestartReusesCommittedInstance`; positive control: `TestInvestigationRestartWithRestoredCounter` | `audit_cluster_restart_output.txt`, `audit_restart_restored_output.txt` |
| F25 recovery fallback proposes empty command | `TestAuditRecoveryAbandonProposesNoop`; `diagnostic_fix13/` validates `len(cmds) > 0`; 500-seed fix-chain sweep | `audit_recovery_noop_output.txt`, `diagnostic_fix5_campaign500_output.txt`, `diagnostic_fix13_noop_output.txt`, `diagnostic_fix13_campaign500_output.txt` |
| F26 PreAccept broadcast carries `-1` seq | `TestAuditPreAcceptBroadcastCarriesComputedSeq`; `diagnostic_fix14/` validates passing the computed seq | `audit_preaccept_seq_output.txt`, `audit_seed4_debug_output.txt`, `diagnostic_fix14_seq_output.txt` |

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
(100 fixed seeds) reports 41 pass, 58 NOOP-on-all losses, and 1 mixed-value
divergence; see `audit_random_fault_output.txt`.  Seed 57 is an all-alive
counterexample: replicas 0-2 committed "chosen", replicas 3-4 committed NOOP.
The isolated reproduction is `TestInvestigationRandomFaultSeed57`
(`audit_random_fault_seed57_output.txt`): pre-recovery 0-2 are COMMITTED,
3-4 have no instance, then recoverer 3 commits NOOP on 3-4.

The extended sweep (`AUDIT_FAULT_SEEDS=500`) reports 208 pass, 285
NOOP-on-all losses, and 7 mixed divergences (seeds 57, 220, 266, 277, 401,
428, 434); see `audit_random_fault_500_output.txt`.  Seed 266 reproduces a
1-PUT/4-NOOP split with the PUT already COMMITTED on replica 0 and
PREACCEPTED on 1-2 (`audit_random_fault_seed266_output.txt`).  In
`diagnostic_fix5/` the same seed commits the PUT on all five replicas
(`diagnostic_fix5_seed266_output.txt`), tying the divergence to F1/F2/F20/F21.

At 1,000 seeds the captured build is 407 pass / 582 NOOP-on-all / 11 mixed
(`audit_random_fault_1000_output.txt`); `diagnostic_fix13/` is 818 pass / 182
NOOP-on-all / 0 divergence (`diagnostic_fix13_campaign1000_output.txt`).

`TestInvestigationLossClassifier` classifies the all-NOOP losses by
pre-recovery holders.  Captured: `{1:36, 2:324, 3:222}`; fixed stack:
`{1:36, 2:146}`.  None of the three-holder cases had identical attributes
including the leader, so the fast-path-chosen-candidate count is 0 in both
copies.  Outputs: `audit_loss_classify_output.txt` (captured, fails on known
mixed divergences) and `diagnostic_fix13_loss_classify_output.txt` (passes).

## Diagnostic copies

`diagnostic_fix/` changes only the local `PrepareReply.VBallot`;
`diagnostic_fix2/` additionally changes the Commit ballot;
`diagnostic_fix3/` additionally serializes `PrepareReply.VBallot`.  These are
separate copies, not the captured implementation.  The two-line copy has 11
passing tests (controls plus the handler recovery/chosen cases) and 25
remaining failures; the three-line copy makes the full cluster
recoverer-matrix pass and gives 14 passes / 22 failures.  The extra passes are
the codec round-trip, PrepareReply ordering, and cluster recoverer matrix; all
F1/F2/F20 recovery cases pass, while unrelated findings remain.

`diagnostic_fix4/` builds on the three-line copy and relaxes the F14 guard.
The restart test then produces an all-alive divergence (restarted replica 0
commits "new", replicas 1-4 keep "old"), validating F24's latent safety risk.
With the restored counter/instance positive control, `diagnostic_fix4/` passes,
showing F14 + persistence resolves the restart case.

`diagnostic_fix5/` builds on the three-line copy and adds a Commit broadcast in
PrepareReply sub-case 1.  The minimal majority test then passes with all five
replicas COMMITTED on the chosen value, validating F21 as the missing
propagation step.

`diagnostic_fix11/` is an independent copy with nil/leader-bookkeeping guards
in `handlePrepareReply`, `handlePreAcceptReply`, and `handleAcceptReply`, plus
the majority-nack prepare retry.  Both F11 tests pass and the rest of the
suite is unchanged (39 failures / 7 passes).

`diagnostic_fix12/` initializes `possibleQuorum` to all-true and indexes the
count loop with `q`.  The defer-cycle test passes with two restarted
PreAccepts; controls and unrelated failures are unchanged (40 failures /
6 passes).

`diagnostic_fix13/` adds `len(cmds) > 0` to the recovery NOOP fallback.  The
recovery-abandon test passes, seed 6 commits explicit NOOPs, and the 500-seed
campaign is 406 pass / 94 NOOP-on-all / 0 divergence (27 failures / 19 passes
in the full diagnostic suite).

`diagnostic_fix14/` passes the computed phase-1 `seq` into leader bookkeeping.
The sequence test, happy/conflict controls, 500-seed campaign, and 1,000-seed
loss classifier pass; the full suite is 26 failures / 20 passes.
