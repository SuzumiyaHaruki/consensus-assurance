# Suggested remediation map

This is a fix-hypothesis map, not applied to the captured implementation.
Validated in separate diagnostic copies: F1, F2, F3, F4 (command-holding),
F5, F6, F7, F8, F12, F13, F14, F15, F17, F20, F21, and the F24
persistence/liveness pairing (`diagnostic_fix/` through `diagnostic_fix9/`),
plus F9/F16/F18/F19/F22/F23 in `diagnostic_fix10/`, the F11 guards/retry in
`diagnostic_fix11/`, and the F10 guard in `diagnostic_fix12/`.  The rest are
source-derived hypotheses with the tests that should validate them.

| Finding | Minimal fix hypothesis | Validation |
|---------|------------------------|------------|
| F1 | In `startRecoveryForInstance`, construct the local `PrepareReply` with the saved old value ballot (`lb.ballot`), not the overwritten `inst.vbal`. Keep the new ballot only for the Prepare message. | `diagnostic_fix/`; `TestAuditRecoveryDoesNotDiscardCommittedRemoteValue`, `TestAuditRecoveryMatrix`, `TestAuditClusterRecoveryStalls`, `TestAuditClusterChosenValueSurvivesLeaderCrash` |
| F2 | Add `VBallot` to `PrepareReply.Marshal`/`Unmarshal` (fixed header 21 bytes: 5×int32 + status), matching `PreAcceptReply`. | `diagnostic_fix3/`; `TestAuditRPCCodecRoundTrip`, `TestAuditPrepareRepliesPreserveValueBallotOrdering`, `TestAuditClusterRecovererMatrix` |
| F3 | Remove the per-replica `break`; evaluate every command in the batch and keep the maximum dependency/seq for each replica. | `diagnostic_fix6/`; both F3 tests pass with `seq=3 deps[1]=9` |
| F4 | When `Cmds` is present, set `inst.Status = ACCEPTED` in `handleAccept`. Decide separately whether no-command acceptors should remain `NONE` or reject. | `diagnostic_fix9/` validates the command-holding case; no-command policy needs TLA reference |
| F5 | In the accepted/no-command branch, assign `inst.Cmds = preAccept.Command`; never index `[LeaderId][Instance]`. | `diagnostic_fix9/`; both F5 tests pass |
| F6 | On a successful TryPreAccept, set `inst.vbal = tpa.Ballot` before constructing the reply. | `diagnostic_fix9/`; F6 test passes |
| F7 | Reorder `handleAcceptReply`: return for lower ballots, count higher ballots as nacks and retry. | `diagnostic_fix9/`; F7 test passes |
| F8 | Guard the own-row NOOP re-propose with `inst.lb != nil`. | `diagnostic_fix9/`; F8 test passes |
| F9 | Use non-overlapping metadata offsets; serialize the addressed row. Durable mode is not shipped by `run.go`. | `diagnostic_fix10/`; metadata test passes |
| F10 | Initialize `possibleQuorum` to all-true and index the count loop with `q`. | `diagnostic_fix12/`; `TestAuditTryPreAcceptBreaksDeferCycle` passes with two restarted PreAccepts |
| F11 | Nil-check `inst`/`lb` before dereference; count higher prepare ballots as nacks and retry at a new ballot. TryPreAccept has the same silent-return shape. | `diagnostic_fix11/`; both F11 tests pass (nil guards and majority-nack prepare retry); TryPreAccept retry remains source review |
| F12 | Set `confStatus` to the conflicting instance's status. | `diagnostic_fix7/`; `TestAuditTryPreAcceptReportsConflictStatus` passes |
| F13 | Use a slow-quorum threshold for the slow Accept branch, separate from the fast-commit threshold. | `diagnostic_fix8/`; both F13 tests pass |
| F14 | After adopting an `ACCEPTED`/`COMMITTED` reply, make progress (start Accept/Commit or continue counting) rather than rejecting all later replies.  Must be paired with the F24 restart-state fix; see `diagnostic_fix4/`. | `diagnostic_fix4/`; F14 test passes (preAcceptOKs=2, status=4), with F24 pairing |
| F15 | Set `inst.vbal` to the adopted/accepting value ballot on fast and slow commit paths. | `diagnostic_fix9/`; F15 test passes |
| F16 | Guard `net.Dial`/`conn` in `defs.IP`; do not require an external route when no latency file is configured. | `diagnostic_fix10/`; both startup tests pass |
| F17 | Call `updateConflicts` when TryPreAccept or PrepareReply sub-case 1 installs a command. | `diagnostic_fix7/`; all three F17 tests pass |
| F18 | Use a 32-bit value length, or reject `commandSize > 65535` in config/client. | `diagnostic_fix10/`; both large-payload tests pass |
| F19 | Track alive replica ids in the closest fallback; guard nil client writers before `SendProposal`. | `diagnostic_fix10/`; both client tests pass |
| F20 | Set `ec.Ballot = lb.lastTriedBallot` when broadcasting Commit (or the ballot used by the accept round). | `diagnostic_fix2/`; `TestAuditRecoveryCommitUsesCurrentBallot`, chosen/slow chosen cluster tests |
| F21 | On PrepareReply sub-case 1, broadcast a Commit to peers (or at least preaccepted/none replicas). | `TestAuditPrepareReplySubcase1PropagatesCommit`; `diagnostic_fix5/` makes the minimal majority test pass |
| F22 | Return after the nil-logger fallback log in `Println`/`Printf`/`Fatal`. | `diagnostic_fix10/`; nil-logger test passes |
| F23 | Default `Config.Proxy` to an empty `ProxyInfo` in `Read`, or make `ProxyOf`/`IsProxy`/`IsLocal` nil-safe. | `diagnostic_fix10/`; nil-proxy test passes |
| F24 | Persist/restore `crtInstance` and committed instances, or use a restart epoch/instance ID that cannot collide; recover existing instances before proposing new ones. | `TestAuditClusterRestartReusesCommittedInstance`; positive control passes in captured code and in `diagnostic_fix4/`; `diagnostic_fix4/` without restoration shows F14+liveness alone causes divergence |

The two validated diagnostic changes are deliberately isolated from the
captured source; applying fixes to the captured tree would require a separate
review and rerun of the full suite.
