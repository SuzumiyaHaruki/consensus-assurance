# Suggested remediation map

This is a fix-hypothesis map, not applied to the captured implementation.
Only F1 and F20 have been validated in separate diagnostic copies
(`diagnostic_fix/`, `diagnostic_fix2/`); the rest are source-derived
hypotheses with the tests that should validate them.

| Finding | Minimal fix hypothesis | Validation |
|---------|------------------------|------------|
| F1 | In `startRecoveryForInstance`, construct the local `PrepareReply` with the saved old value ballot (`lb.ballot`), not the overwritten `inst.vbal`. Keep the new ballot only for the Prepare message. | `diagnostic_fix/`; `TestAuditRecoveryDoesNotDiscardCommittedRemoteValue`, `TestAuditRecoveryMatrix`, `TestAuditClusterRecoveryStalls`, `TestAuditClusterChosenValueSurvivesLeaderCrash` |
| F2 | Add `VBallot` to `PrepareReply.Marshal`/`Unmarshal` (fixed header 21 bytes: 5×int32 + status), matching `PreAcceptReply`. | `TestAuditRPCCodecRoundTrip`, `TestAuditPrepareRepliesPreserveValueBallotOrdering` |
| F3 | Remove the per-replica `break`; evaluate every command in the batch and keep the maximum dependency/seq for each replica. | `TestAuditUpdateAttributesConsidersWholeBatch`, `TestAuditBatchedProposalUsesNewestDependency` |
| F4 | When `Cmds` is present, set `inst.Status = ACCEPTED` in `handleAccept`. Decide separately whether no-command acceptors should remain `NONE` or reject. | `TestAuditAcceptWithCommandMarksAccepted`; no-command policy needs TLA reference |
| F5 | In the accepted/no-command branch, assign `inst.Cmds = preAccept.Command`; never index `[LeaderId][Instance]`. | `TestAuditPreAcceptStoresCommandInAddressedInstance`, `TestAuditPreAcceptOutOfPlaceStoreDoesNotPanic` |
| F6 | On a successful TryPreAccept, set `inst.vbal = tpa.Ballot` before constructing the reply. | `TestAuditTryPreAcceptRecordsVBallot` |
| F7 | Reorder `handleAcceptReply`: return for lower ballots, count higher ballots as nacks and retry. | `TestAuditAcceptReplyCountsHigherBallotAsNack` |
| F8 | Guard the own-row NOOP re-propose with `inst.lb != nil`. | `TestAuditCommitForUnknownOwnInstanceDoesNotPanic` |
| F9 | Use non-overlapping metadata offsets; serialize the addressed row. Durable mode is not shipped by `run.go`. | `TestAuditDurableMetadataLayout` |
| F10 | Initialize/track `possibleQuorum` correctly and index it with the loop variable `q`. | source review; recovery defer-cycle test still needed |
| F11 | Nil-check `inst`/`lb` before dereference; retry on higher prepare/TryPreAccept ballot with a new ballot. | source review; scheduler test still needed |
| F12 | Set `confStatus` to the conflicting instance's status. | `TestAuditTryPreAcceptReportsConflictStatus` |
| F13 | Use a slow-quorum threshold for the slow Accept branch, separate from the fast-commit threshold. | `TestAuditSlowPathStartsWithMajority`, `TestAuditClusterN7FailureStalls` |
| F14 | After adopting an `ACCEPTED`/`COMMITTED` reply, make progress (start Accept/Commit or continue counting) rather than rejecting all later replies. | `TestAuditHigherVBallotReplyDoesNotBlockFurtherReplies` |
| F15 | Set `inst.vbal` to the adopted/accepting value ballot on fast and slow commit paths. | `TestAuditFastCommitRecordsValueBallot` |
| F16 | Guard `net.Dial`/`conn` in `defs.IP`; do not require an external route when no latency file is configured. | `TestAuditIPHelperDoesNotPanic`, `TestAuditReplicaConstructionDoesNotRequireExternalRoute` |
| F17 | Call `updateConflicts` when TryPreAccept or PrepareReply sub-case 1 installs a command. | `TestAuditTryPreAcceptUpdatesConflicts`, `TestAuditPrepareReplyUpdatesConflicts`, `TestAuditPrepareReplyConflictMiss` |
| F18 | Use a 32-bit value length, or reject `commandSize > 65535` in config/client. | `TestAuditLargeCommandRoundTrip`, `TestAuditLargeProposeRoundTrip` |
| F19 | Track alive replica ids in the closest fallback; guard nil client writers before `SendProposal`. | `TestAuditFindClosestSkipsDeadReplica`, `TestAuditSendProposalToDeadClosestDoesNotPanic` |
| F20 | Set `ec.Ballot = lb.lastTriedBallot` when broadcasting Commit (or the ballot used by the accept round). | `diagnostic_fix2/`; `TestAuditRecoveryCommitUsesCurrentBallot`, chosen/slow chosen cluster tests |
| F21 | On PrepareReply sub-case 1, broadcast a Commit to peers (or at least preaccepted/none replicas). | `TestAuditPrepareReplySubcase1PropagatesCommit` |
| F22 | Return after the nil-logger fallback log in `Println`/`Printf`/`Fatal`. | `TestAuditNilLoggerDoesNotPanic` |
| F23 | Default `Config.Proxy` to an empty `ProxyInfo` in `Read`, or make `ProxyOf`/`IsProxy`/`IsLocal` nil-safe. | `TestAuditNilProxyDoesNotPanic` |

The two validated diagnostic changes are deliberately isolated from the
captured source; applying fixes to the captured tree would require a separate
review and rerun of the full suite.
