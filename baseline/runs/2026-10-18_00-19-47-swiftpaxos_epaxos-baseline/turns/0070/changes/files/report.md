# EPaxos audit report

One-page handoff: `executive_summary.md`.

Source under audit: `../source` (identity `35c69365f1c7737a08e237bfbaf828ee68897080`).
The `work/` tree is a byte-identical copy of that source; the only added files are
the `epaxos/audit_*_test.go` tests, the `client/audit_findclosest_test.go`
failover test, the `dlog/audit_nil_test.go` robustness test, captured output
files, the `config/audit_nilproxy_test.go` test, this report, and the separate
`diagnostic_fix/`, `diagnostic_fix2/`, `diagnostic_fix3/`, `diagnostic_fix4/`,
`diagnostic_fix5/`, `diagnostic_fix6/`, `diagnostic_fix7/`, and
`diagnostic_fix8/`, `diagnostic_fix9/`, `diagnostic_fix10/`,
`diagnostic_fix11/`, `diagnostic_fix12/` copies used only to validate root
causes and fix
hypotheses.  The diagnostic copies are not the captured
implementation.

Method: source review of the EPaxos state machine and wire codecs, followed by
synchronous handler tests that construct a replica without starting its network
loop.  Outbound RPCs are routed to a `bufio.Writer` over `bytes.Buffer` when the
reply itself is part of the observable behavior.  A second harness
(`epaxos/audit_cluster_test.go`) routes real marshaled RPCs between five
or seven in-process replicas, so the normal path, conflicting proposals, a
partitioned-replica recovery, and an N=7 failure case are exercised as
multi-replica event sequences.  The tests do not patch or otherwise alter the
implementation.

Five cluster controls pass and show the harness itself is not failing
everything: `TestAuditClusterHappyPath` (one proposal commits and executes on
all five replicas), `TestAuditClusterConflictPath` (two concurrent proposals on
the same key commit and produce the same final value), and
`TestAuditClusterShuffledNormalPath` / `TestAuditClusterShuffledSeeds` (fixed
seeds 1-20 with randomly reordered message delivery converge on the same
committed instances and state), and
`TestAuditClusterRandomNormalCampaign` (50 random mixes of 1-3 proposals on
random keys with random delivery converge on the same committed instances and
state).

Determinism check: the cluster controls pass with `-count=3`, and the five
cluster finding scenarios (recovery stall, N=7 failure, fast-chosen value,
slow-chosen value, partitioned leader) fail with `-count=3` on every run.
Outputs: `audit_cluster_controls_count3.txt` and
`audit_cluster_findings_count3.txt`.

Reproduction:

```
cd work
go test ./epaxos -run TestAudit -v
# or refresh the main captured outputs, controls, and investigations:
./run_audit.sh
```

Cluster controls (all pass):

```
go test ./epaxos -run 'TestAuditClusterHappyPath|TestAuditClusterConflictPath|TestAuditClusterShuffledNormalPath|TestAuditClusterShuffledSeeds' -v
```

Cluster failure reproductions (all fail):

```
go test ./epaxos -run 'TestAuditClusterRecoveryStalls|TestAuditClusterN7FailureStalls|TestAuditClusterChosenValueSurvivesLeaderCrash|TestAuditClusterSlowPathChosenValueSurvivesLeaderCrash|TestAuditClusterPartitionedLeaderKeepsChosenValue|TestAuditClusterRecovererMatrix' -v
```

Current result: the five cluster controls pass; 39 epaxos finding tests fail,
each with an assertion that states the expected protocol behavior.  The
separate client failover tests (`client/audit_findclosest_test.go`) also fail.
The `dlog` nil-logger test (`dlog/audit_nil_test.go`) also fails.
The `config` nil-proxy test (`config/audit_nilproxy_test.go`) also fails.
The tests are supposed to fail against the captured implementation.

Captured output: `audit_all_output.txt`.  Individual captures:
`audit_cluster_happy_output.txt`, `audit_cluster_recovery_output.txt`,
`audit_cluster_n7_output.txt`, `audit_cluster_conflict_output.txt`,
`audit_cluster_chosen_output.txt`,
`audit_cluster_slow_chosen_output.txt`,
`audit_cluster_partitioned_output.txt`,
`audit_cluster_recoverer_matrix_output.txt`,
`audit_cluster_restart_output.txt`,
`audit_cluster_majority_divergence_output.txt`,
`audit_restart_restored_output.txt`,
`audit_cluster_shuffled_output.txt`, `audit_cluster_shuffled_seeds_output.txt`,
`audit_cluster_random_output.txt`,
`audit_random_fault_output.txt`,
`audit_random_fault_seed57_output.txt`,
`audit_cluster_controls_count3.txt`, `audit_cluster_findings_count3.txt`,
`audit_codec_recovery_output.txt`, `audit_recovery_safety_output.txt`,
`audit_recovery_local_value_output.txt`,
`audit_recovery_matrix_output.txt`,
`audit_recovery_commit_output.txt`, `diagnostic_fix_output.txt`,
`diagnostic_fix2_output.txt`,
`diagnostic_fix3_output.txt`,
`diagnostic_fix3_all_output.txt`,
`diagnostic_fix4_output.txt`,
`diagnostic_fix4_restored_output.txt`,
`diagnostic_fix4_f14_output.txt`,
`diagnostic_fix5_output.txt`,
`diagnostic_fix6_output.txt`,
`diagnostic_fix7_output.txt`,
`diagnostic_fix8_output.txt`,
`diagnostic_fix9_output.txt`,
`diagnostic_fix10_output.txt`,
`diagnostic_fix11_output.txt`,
`diagnostic_fix11_all_output.txt`,
`diagnostic_fix12_output.txt`,
`diagnostic_fix12_all_output.txt`,
`diagnostic_fix2_all_output.txt`,
`audit_prepare_retry_output.txt`,
`audit_defer_cycle_output.txt`,
`audit_prepare_subcase1_output.txt`,
`audit_unknown_reply_output.txt`,
`audit_nil_logger_output.txt`,
`audit_nil_proxy_output.txt`,
`final_verification.txt`,
`run_audit_output.txt`,
`handoff_check.txt`,
`go_vet_output.txt`,
`audit_loopback_output.txt`,
`audit_exec_order_output.txt`,
`audit_batch_flow_output.txt`, `audit_batch_output.txt`,
`audit_slowpath_output.txt`, `audit_higher_vbal_output.txt`,
`audit_fast_vbal_output.txt`, `audit_tpa_status_output.txt`,
`audit_tpa_conflicts_output.txt`,
`audit_prepare_conflicts_output.txt`,
`audit_prepare_conflict_miss_output.txt`,
`audit_large_command_output.txt`,
`audit_large_propose_output.txt`,
`audit_conflict_output.txt`, `audit_extra_output.txt`,
`audit_startup_output.txt`, `audit_ip_output.txt`,
`audit_accept_status_output.txt`, `audit_accept_command_output.txt`,
`audit_client_closest_output.txt`, `audit_client_dead_closest_output.txt`.

`validation_matrix.md` maps each finding to its decisive tests and captured
output; `remediation.md` records minimal fix hypotheses and their validation
tests without changing the captured implementation.
`handoff_check.txt` confirms every referenced output file exists and every
named test is present; the lone `MISS TestAudit` entry is the `-run TestAudit`
pattern, not a test function.

The unclaimed investigation `TestInvestigationSelfConflictSkip` can be run
separately; it is intentionally excluded from the `TestAudit` pattern:

```
go test ./epaxos -run TestInvestigationSelfConflictSkip -v
go test ./epaxos -run TestInvestigationExecOrderUsesReplicatedIdentity -v
go test ./epaxos -run TestInvestigationAcceptStatus -v
go test ./client -run 'TestAuditFindClosestSkipsDeadReplica|TestAuditSendProposalToDeadClosestDoesNotPanic' -v
go test ./epaxos -run TestInvestigationRandomFaultCampaign -v
```

## Summary

| ID | Severity | Kind | Location | Evidence |
|----|----------|------|----------|----------|
| F1 | Critical | Safety: recovery commits NOOP while a partitioned/crashed leader retains the chosen value; all-alive divergence after healing | `epaxos/epaxos.go:1153-1159` | executed (handler + 5-replica clusters) |
| F2 | Critical | Safety: `PrepareReply.VBallot` is dropped by the codec; recovery selects a stale value | `epaxos/defs.go:153-253` | executed; diagnostic_fix3 validates the codec root |
| F3 | High | Safety/linearizability: batched proposals miss the newest conflicting dependency and use a too-small seq | `epaxos/epaxos.go:668-680` | executed; diagnostic_fix6 validates the break |
| F4 | Medium | Recovery semantics: an acceptor that already holds the command does not record `ACCEPTED`; possible semantic deviation, failure not isolated | `epaxos/epaxos.go:992-1000` | executed; diagnostic_fix9 validates command-holding case; no-command case investigated separately |
| F5 | High | State corruption / panic: PreAccept stores the command in the leader's row | `epaxos/epaxos.go:810` | executed; diagnostic_fix9 validates |
| F6 | Medium | Liveness: successful TryPreAccept is reported with the wrong `VBallot` and counted as a nack | `epaxos/epaxos.go:1345-1349`, `1425` | executed; diagnostic_fix9 validates |
| F7 | Medium | Liveness: higher-ballot AcceptReply branch is unreachable | `epaxos/epaxos.go:1024-1036` | executed; diagnostic_fix9 validates |
| F8 | Medium | Crash: Commit for an unknown instance in the replica's own row dereferences nil bookkeeping | `epaxos/epaxos.go:1088-1095` | executed; diagnostic_fix9 validates |
| F9 | Low | Durability: metadata layout overwrites `bal` and overlaps `Status`/`Seq` | `epaxos/epaxos.go:199-215` | executed; diagnostic_fix10 validates layout; durable mode is not selected by `run.go` |
| F10 | Medium | Liveness: recovery defer-cycle guard is dead code | `epaxos/epaxos.go:1459-1464`, `1521` | executed; diagnostic_fix12 validates |
| F11 | Medium | Crash/robustness: all three reply handlers dereference `inst.lb` before checking an unknown instance; higher-ballot prepare replies never trigger a retry | `epaxos/epaxos.go:848-849`, `1009-1010`, `1205-1218` | executed nil panic and stalled retry |
| F12 | High | TryPreAccept conflict replies always report `ConflictStatus=NONE` | `epaxos/epaxos.go:1332-1348` | executed; diagnostic_fix7 validates |
| F13 | High | Liveness: the slow accept path requires a fast-quorum number of PreAccept replies; N=7 with f failures stalls | `epaxos/epaxos.go:919-971` | executed; diagnostic_fix8 validates |
| F14 | High | Liveness: a higher-VBallot ACCEPTED reply blocks all later PreAccept replies | `epaxos/epaxos.go:870-881` | executed; diagnostic_fix4 validates the guard, with F24 persistence caveat |
| F15 | Medium | Fast commit sets `bal` to the adopted value ballot but leaves `vbal` at the old ballot | `epaxos/epaxos.go:919-927` | executed; diagnostic_fix9 validates |
| F16 | High (startup) | Panic when the host has no route to 8.8.8.8, even with no latency file | `replica/defs/latency.go:234-238`, `replica/replica.go:101`, `client/client.go:102` | executed; diagnostic_fix10 validates the guard |
| F17 | High | Recovery/ordering: TryPreAccept and PrepareReply sub-case 1 install values without updating the conflict table | `epaxos/epaxos.go:1291-1296`, `1338-1345` | executed; diagnostic_fix7 validates |
| F18 | Medium | Command values over 65535 bytes are silently truncated by the `state.Value` wire codec | `state/state.go:230-255` | executed; diagnostic_fix10 validates 32-bit length; default `commandSize` is 1000 |
| F19 | Medium | Client closest-replica fallback uses the Ping-slice index as a replica id and can select a dead replica | `client/client.go:371-378` | executed; diagnostic_fix10 validates |
| F20 | High | Recovery Commit is broadcast at the old value ballot; acceptors at the current ballot ignore it | `epaxos/epaxos.go:595-605`, `1086-1087` | executed; isolated by diagnostic fix |
| F21 | Medium | PrepareReply sub-case 1 installs a committed value but broadcasts no Commit | `epaxos/epaxos.go:1298-1299` | executed; diagnostic_fix5 validates |
| F22 | Low | Nil `*dlog.Logger` fallback logs, then panics on `l.verbose` | `dlog/dlog.go:32-54` | executed; diagnostic_fix10 validates; production callers pass a non-nil logger |
| F23 | Low | Config without a Proxy section leaves `c.Proxy` nil; client/replica proxy methods panic | `config/proxy.go:53-78`, `main.go:132` | executed; diagnostic_fix10 validates; default aws.conf has a Proxy section |
| F24 | High | Restarted owner reuses a committed instance number and creates a conflicting PREACCEPTED value | `epaxos/epaxos.go:724-745`, `run.go` fresh-replica construction | executed 5-replica cluster; no durable state in shipped run |

Most consequential for the recovery claim: F1 and F2 (the prepare phase can
discard a chosen/committed value or select a stale one), with F1 now reproduced
end to end: both a fast-chosen and a slow-Accept-chosen value are replaced by
NOOP on the recovering replicas; with a partitioned leader, all replicas are
alive after healing but disagree on the committed value.  F14 (a higher-value-ballot reply stalls the
round), F13 (N=7 loses liveness under f failures), and F3 (batched proposals
miss dependencies) are also high-impact.  F12 and F17 add recovery-ordering
errors (missing conflict status and missing conflict-table updates).  F16 is a
deployment blocker in this no-network environment rather than a consensus-logic
defect.  F4 is a Medium protocol-state question when the command is already
present; its no-command variant remains an investigation, and the F1/F2/F20
diagnostic path does not require F4 to pass.  F20 is a separate
agreement-completion defect; the two one-line diagnostic fixes (local
`VBallot` and Commit ballot) make the recovery-stall, fast-chosen, and
slow-chosen cluster tests pass, validating F1/F20 as those scenarios' roots.

Diagnostic fix validation: `diagnostic_fix9/` combines minimal fixes for the
command-holding F4 case, F5, F6, F7, F8, and F15; all seven corresponding
tests pass (F4/F5 each have two tests).  See `diagnostic_fix9_output.txt`.

`diagnostic_fix10/` validates the boundary fixes: F9 metadata
(`bal=7 vbal=3 status=1`), F16 startup (`defs.IP()=""`, replica construction),
F18 large command/Propose round trips (`70000` bytes, timestamp preserved),
F19 client failover (`ClosestId=1`, no `SendProposal` panic), F22 nil logger,
and F23 nil proxy.  All eight tests pass; see `diagnostic_fix10_output.txt`.

`diagnostic_fix11/` guards the three reply handlers against an unknown
instance or missing leader bookkeeping and adds the majority-nack prepare
retry.  Both F11 tests pass and the remaining 37 finding failures are
unchanged; see `diagnostic_fix11_output.txt` and
`diagnostic_fix11_all_output.txt`.

`diagnostic_fix12/` initializes the recovery `possibleQuorum` set and indexes
it with the loop variable.  The defer-cycle test passes and the remaining 38
finding failures are unchanged; see `diagnostic_fix12_output.txt` and
`diagnostic_fix12_all_output.txt`.

## F1. Recovery masks remote values with a local reply at the new ballot

**Expected.**  A recovery leader that has no value for an instance must include
its own empty vote without claiming a value ballot.  The other replies, which
may report a `PREACCEPTED`, `ACCEPTED`, or `COMMITTED` value at a real value
ballot, must win the `VBallot` comparison in `handlePrepareReply`
(`epaxos.go:1239-1246`).  This is the recovery invariant encoded by the saved
`lb.ballot = inst.vbal` at `epaxos.go:1145` and by the "only replies from the
highest ballot are taken into account" comment at `1229`.
The local reply must likewise report the local value's existing value ballot
(or -1 if it has none), not the new prepare ballot.

**Affected code.**  `startRecoveryForInstance`, `epaxos.go:1153-1161`:

```go
inst.bal = lb.lastTriedBallot
inst.vbal = lb.lastTriedBallot       // old value ballot is discarded
preply := &PrepareReply{
    r.Id, replica, instance,
    inst.bal, inst.vbal,             // VBallot is now the new prepare ballot
    inst.Status, inst.Cmds, inst.Seq, inst.Deps}
```

When the local instance is `NONE`, `inst.Cmds` is nil and `inst.Status` is
`NONE`, but the synthetic reply claims `VBallot == lastTriedBallot`.  In
`handlePrepareReply` the local reply is the first element of
`prepareReplies`; `element.VBallot >= lb.ballot` is therefore true, and it
installs `lb.cmds = nil`, `lb.status = NONE`, and `lb.ballot = lastTriedBallot`.
Every remote reply at a lower value ballot is then ignored.  The resulting
sub-case is 6, so `startPhase1` is called with `state.NOOP()`.

**Necessary conditions.**  `executeCommands` has queued
`instancesToRecover` for an instance this replica does not have (or has only a
lower-ballot value), and a slow quorum of prepare replies reports a
pre-accepted, accepted, or committed command.  The replica need not be the
instance owner; recovery is started by the execution timeout for any row.

**Observed.**  `TestAuditRecoveryDoesNotDiscardCommittedRemoteValue` starts
recovery for instance 2.0 with no local copy, then delivers two replies for
that instance with `Status: COMMITTED`, `VBallot: 7`, and a PUT command.  The
recovering replica instead starts phase 1 with NOOP:

```
recovery discarded the committed command: Status=1 Cmds=[{0 0 []}] (phase-1 result)
```

`TestAuditRecoveryLocalReplyKeepsValueBallot` shows the local reply itself:

```
old bal=5 old vbal=2 new lastTriedBallot=5 local reply Ballot=5 VBallot=5 Status=3
```

The local reply reports `VBallot=5` although the stored value was at `vbal=2`.

`TestAuditRecoveryPrefersRemoteCommittedOverLocalPreaccepted` covers the case
where the recovering replica already has a local `PREACCEPTED` value.  The
local value is a PUT on key 1 at `vbal=2`; two remote replies report a
`COMMITTED` PUT on key 2 at `VBallot=5`.  After recovery the phase-1 instance
still contains the local key 1:

```
recovery kept local=[{1 1 [108 111 99 97 108]}]; selected key=1
recovery did not prefer the remote COMMITTED value at VBallot 5 over the local PREACCEPTED value at VBallot 2
```

The synthetic local reply claims the new prepare ballot and masks the
committed remote values, so the stale local preaccepted value wins.

`TestAuditRecoveryMatrix` generalizes this across local states
(`NONE`/`PREACCEPTED`) and remote statuses (`PREACCEPTED_EQ`/`ACCEPTED`/
`COMMITTED`).  All six combinations fail: a local `NONE` recovers to NOOP, and
a local `PREACCEPTED` value wins, while the remote key at `VBallot=5` is never
selected.

The five-replica harness `TestAuditClusterRecoveryStalls` shows the same path
with real marshaled RPCs: replicas 0-3 commit a PUT, replica 4 is partitioned
for the initial proposal/commit, and then replica 4 starts recovery for the
instance.  The test sets `crtInstance[0]=0` on replica 4 to simulate the later
protocol message that tells it the instance exists; that is the state in which
`executeCommands` detects the hole and calls `startRecoveryForInstance`.
After recovery messages are drained:

```
replica 4 after recovery: status=1 bal=9 vbal=9 cmds=[{0 0 []}]
replica 4 bookkeeping: status=4 ballot=0 lastTried=9 preAcceptOKs=1
```

`status=1` is `PREACCEPTED` and `cmds=[{0 0 []}]` is NOOP; the committed PUT
was not installed at the recovering replica.  The happy-path control
`TestAuditClusterHappyPath` passes, so this is not a harness-wide failure.

`TestAuditClusterChosenValueSurvivesLeaderCrash` turns this into a cluster-wide
safety failure.  A fast quorum {0,1,2} chooses a PUT, the Commit broadcast is
dropped, and leader 0 crashes: replica 0 has `COMMITTED` PUT, replicas 1 and 2
have `PREACCEPTED` copies, and replica 4 has no copy.  Replica 4 then recovers
from 1 and 2.  The premise matches the implementation's own fast-commit rule:
`FastQuorumSize()` is 3 for `N=5` (`replica/replica.go:120-122`), and
`handlePreAcceptReply` commits after two equal PreAccept replies
(`preAcceptOKs >= FastQuorumSize()-1` with `allEqual` and the initial ballot).
After recovery:

```
replica 0: status=4 cmds=[{1 7 [99 104 111 115 101 110]}]   // "chosen"
replica 1: status=4 cmds=[{0 0 []}]                          // NOOP
replica 2: status=4 cmds=[{0 0 []}]                          // NOOP
replica 3: status=4 cmds=[{0 0 []}]                          // NOOP
replica 4: status=4 cmds=[{0 0 []}]                          // NOOP
```

The prepare replies from 1 and 2 contain the preaccepted PUT, but the local
synthetic reply claims the new value ballot and masks them.  Phase 1 then
sends NOOP PreAccept to 1 and 2, which replaces their preaccepted PUT; the
resulting Accept/Commit writes NOOP to every live replica.  The chosen value
survives only on the crashed leader.  This is a violation of agreement, not
only a prepare-phase or liveness error.

`TestAuditClusterRecovererMatrix` varies the recoverer:

- Recoverers 1 and 2 already hold the preaccepted chosen value; both preserve
  the chosen PUT on all four live replicas.
- Recoverers 3 and 4 have no local value; both follow the F1 NOOP path and
  commit NOOP on the live replicas.

This confirms the failure condition: a recoverer that lacks the value lets
the synthetic local reply mask the preaccepted copies; a recoverer that
already holds the value re-proposes it successfully.

`TestAuditClusterSlowPathChosenValueSurvivesLeaderCrash` reproduces the same
loss for a value chosen through the **slow Accept path** rather than the fast
PreAccept path.  A conflicting pivot on replica 1 forces the leader into
Accept; the accept quorum {0,1,2} chooses the value; the commits are dropped
and leader 0 crashes; replica 4 recovers.  The result is identical:

```
replica 0: status=4 cmds=[{1 7 [99 104 111 115 101 110]}]   // "chosen"
replica 1: status=4 cmds=[{0 0 []}]                          // NOOP
replica 2: status=4 cmds=[{0 0 []}]                          // NOOP
replica 3: status=4 cmds=[{0 0 []}]                          // NOOP
replica 4: status=4 cmds=[{0 0 []}]                          // NOOP
```

Both the fast-chosen and slow-chosen values are lost by the same recovery
path.

`TestAuditClusterPartitionedLeaderKeepsChosenValue` removes the question of
whether a crashed leader's in-memory state survives.  Leader 0 is partitioned
rather than crashed; replicas 1-4 recover to NOOP; the partition is healed and
the recovery Commit is re-broadcast.  Replica 0 ignores it because its instance
is already COMMITTED, so all five replicas are alive but disagree:

```
replica 0: status=4 cmds=[{1 7 [99 104 111 115 101 110]}]   // "chosen"
replica 1: status=4 cmds=[{0 0 []}]                          // NOOP
replica 2: status=4 cmds=[{0 0 []}]                          // NOOP
replica 3: status=4 cmds=[{0 0 []}]                          // NOOP
replica 4: status=4 cmds=[{0 0 []}]                          // NOOP
```

This is a persistent live-cluster divergence, not merely a lost value on a
crashed replica.  Executing instance 0.0 on all five replicas shows the state
machines diverging:

```
replica 0 state: key7=[99 104 111 115 101 110] present=true   // "chosen"
replica 1 state: key7=<nil> present=false
replica 2 state: key7=<nil> present=false
replica 3 state: key7=<nil> present=false
replica 4 state: key7=<nil> present=false
```

`TestAuditClusterCommittedMajorityRecoveryDiverges` is the minimal
deterministic form: replicas 0-2 are seeded with the chosen value
COMMITTED at instance 0.0, replicas 3-4 have no instance, and replica 3
initiates recovery.  The result is:

```
replica 0-2: status=4 cmds=[{1 7 [99 104 111 115 101 110]}]  // "chosen"
replica 3-4: status=4 cmds=[{0 0 []}]                         // NOOP
```

No random drops are involved; a value already committed on a majority is
lost on the two recovering replicas.

With the F1/F2/F20/F21 diagnostic fixes (`diagnostic_fix5/`), this same test
passes with all five replicas COMMITTED on the chosen value.

The 100-seed randomized initial-drop campaign independently produced the same
kind of mixed divergence at seed 57.  Before recovery, replicas 0-2 already
had the chosen value COMMITTED and replicas 3-4 had no instance.  Recoverer 3
then committed NOOP on 3-4:

```
pre-recovery replica 0-2: status=4 cmds=[{1 7 [99 104 111 115 101 110]}]  // "chosen"
pre-recovery replica 3-4: no instance
recoverer=3
replica 0: status=4 cmds=[{1 7 [99 104 111 115 101 110]}]   // "chosen"
replica 1: status=4 cmds=[{1 7 [99 104 111 115 101 110]}]   // "chosen"
replica 2: status=4 cmds=[{1 7 [99 104 111 115 101 110]}]   // "chosen"
replica 3: status=4 cmds=[{0 0 []}]                          // NOOP
replica 4: status=4 cmds=[{0 0 []}]                          // NOOP
```

All five replicas are alive with conflicting committed values.  The campaign
finding is in `audit_random_fault_output.txt`; the isolated reproduction is
`TestInvestigationRandomFaultSeed57` in
`audit_random_fault_seed57_output.txt`.

**Impact.**  The prepare-phase decision is wrong: a replica that has no value
concludes that no value exists even when a slow quorum of replies reports a
preaccepted or committed one, and starts phase 1 with NOOP.  The cluster test
shows that the rest of recovery does not necessarily re-learn the value; it
can commit NOOP on the recovering replicas while the partitioned or crashed
leader holds the chosen value.  After healing, all replicas can be alive yet
disagree on the committed value and execute to different state.  This is
independent of the codec defect in F2.

## F2. `PrepareReply` does not serialize `VBallot`

**Expected.**  `PrepareReply` has a `VBallot int32` field (`epaxos/defs.go:20-28`)
and `handlePrepareReply` relies on it to choose the newest value
(`epaxos.go:1239-1246`, `1261`).  A wire round trip must preserve every field.
The sibling messages `PreAcceptReply` and `TryPreAcceptReply` both encode their
`VBallot` fields (`defs.go:841`, `1181`).

**Affected code.**  `PrepareReply.Marshal` (`defs.go:153-208`) uses a 17-byte
fixed header containing `AcceptorId`, `Replica`, `Instance`, `Ballot`, and
`Status`; it never writes `VBallot`.  `PrepareReply.Unmarshal`
(`defs.go:210-253`) never reads it.  The header is 4+4+4+4+1 bytes, matching a
struct without `VBallot`.

**Necessary conditions.**  Any prepare reply that travels between replicas and
reports a nonzero value ballot.  Recovery is the only path that sends
`PrepareReply`.

**Observed.**  `TestAuditRPCCodecRoundTrip` round-trips one instance of every
EPaxos message.  `PrepareReply` is the only failure:

```
PrepareReply: round trip mismatch
 in=... VBallot:5 ...
out=... VBallot:0 ...
```

`TestAuditPrepareRepliesPreserveValueBallotOrdering` sends an `ACCEPTED` value
at `VBallot=7`, then a stale `PREACCEPTED` value at `VBallot=5`.  Both decode
with `VBallot=0`:

```
decoded VBallots: high=0 low=0
recovery selected [{1 1 [115 116 97 108 101]}] (Status=1)
```

`[115 116 97 108 101]` is "stale"; the accepted value "accepted" was not kept.

Diagnostic validation: with the local-`VBallot` and Commit-ballot fixes,
recoverers 1/2 still ended with empty `Cmds` because remote `NONE` replies
decoded `VBallot=0` and overwrote the value.  Adding the 21-byte
`PrepareReply` codec (`diagnostic_fix3/`) makes the recovery-stall, fast/slow
chosen, and all four recoverer-matrix subtests pass.  This validates F2 as the
third recovery root cause.

**Impact.**  Even if F1 is fixed, recovery cannot order prepare replies by
their value ballot.  The order in which replies happen to arrive decides which
value is selected, so a stale pre-accepted value can overwrite an accepted
value.  This violates the recovery safety rule.

## F3. Batched proposals lose dependencies and use a too-small seq

**Expected.**  For every replica `q`, `updateAttributes` must use the newest
conflicting instance over *all* commands in the batch.  A batch is proposed as
one EPaxos instance, so its dependency vector and `Seq` must reflect the
maximum conflicting instance in the whole batch.  This is what `updateConflicts`
records (`epaxos.go:629-655`) and what the recovery/execution logic consumes
when it orders instances.

**Affected code.**  `updateAttributes`, `epaxos.go:657-687`:

```go
for i := 0; i < len(cmds); i++ {
    if dpair, present := (r.conflicts[q])[cmds[i].K]; present {
        d := dpair.lastWrite
        if cmds[i].Op != state.GET { d = dpair.last }
        if d > deps[q] {
            deps[q] = d
            if seq <= r.InstanceSpace[q][d].Seq { seq = ... + 1 }
            changed = true
            break        // later commands in the batch are not examined
        }
    }
}
```

The `break` stops at the first command that increases the dependency for a
replica.  A later command in the same batch may conflict with a newer instance
for that replica; its dependency and `Seq` are never considered.

**Necessary conditions.**  `handlePropose` drains more than one queued proposal
into one instance (`batchSize := len(r.ProposeChan)+1`, `epaxos.go:727-742`),
and the batch contains commands on different keys whose newest conflicting
instances are different.  The default run has 99 client clones multiplexed onto
one server, so a non-empty queue is a normal burst condition; EPaxos's
`batchWait` is hardcoded to 0 in `run.go`, but that does not prevent the
`len(ProposeChan)` drain.

**Observed.**  `TestAuditUpdateAttributesConsidersWholeBatch` sets the newest
conflict on replica 1 to instance 5 (`Seq=1`) for the first key and instance 9
(`Seq=2`) for the second key.  The returned vector keeps only 5:

```
updateAttributes batch => seq=2 deps=[-1 5 -1 -1 -1]
dependency on replica 1 is 5, want 9
seq is 2, want 3
```

`TestAuditBatchedProposalUsesNewestDependency` reproduces the same result
through `handlePropose` with two queued proposals:

```
batched instance: seq=2 deps=[-1 5 -1 -1 -1] cmds=[{1 100 [97]} {1 200 [98]}]
batched proposal has seq=2 deps[1]=5, want seq=3 deps[1]=9
```

Diagnostic validation: `diagnostic_fix6/` removes only the inner-loop
`break`; both tests then observe `seq=3 deps=[-1 9 -1 -1 -1]` and pass.  This
confirms the break as the F3 root cause.

**Impact.**  The batched command may be executed before the newer conflicting
instance it should depend on.  This breaks the EPaxos ordering/linearizability
condition for the second command in the batch.  It is a local defect even if
the resulting execution is not observed to diverge in a particular schedule.

## F4. Acceptors that already hold the command do not record ACCEPTED

**Expected.**  When an acceptor already has the command (normally from the
PreAccept that preceded Accept) and receives Accept, it should advance its
status to `ACCEPTED`.  `handlePrepareReply` has a dedicated sub-case 2 for
`ACCEPTED` (`epaxos.go:1230-1258`), `findPreAcceptConflicts` treats
`Status >= ACCEPTED` specially (`epaxos.go:1365-1370`), and the Paxos
implementation in the same repository sets the status in the corresponding
path (`paxos/paxos.go:452-470`).

**Affected code.**  `handleAccept`, `epaxos.go:992-1000`: the non-committed
branch updates `Deps`, `Seq`, `bal`, and `vbal`, but never sets
`inst.Status = ACCEPTED`.  It makes no distinction between an acceptor that
already has `Cmds` from PreAccept and one that received only Accept.

**Necessary conditions.**  A normal slow-path Accept where the acceptor
previously received the command in PreAccept.  The prepare reply constructed
at `epaxos.go:1192-1200` then reports the old `PREACCEPTED`/`PREACCEPTED_EQ`
status even though `Cmds` is present.

**Observed.**  `TestAuditAcceptWithCommandMarksAccepted` pre-installs the
command with `PREACCEPTED_EQ`, then sends Accept:

```
after Accept with command present: status=2 cmds=[{1 1 [120]}]
status=2, want ACCEPTED (3) for an acceptor that already holds the command
```

The slow-path cluster test logs the same state before the leader crashes:
replica 1 has `status=1` and replica 2 has `status=2`, both with the chosen
PUT in `Cmds`.

**No-command case (still investigation).**  EPaxos's `Accept` has no `Command`
field.  An acceptor outside the original PreAccept quorum has no command;
marking it `ACCEPTED` with `Cmds == nil` could let recovery sub-case 2 install
a nil command.  `TestInvestigationAcceptStatus` exercises that case and
observes `Status=0`/`Cmds=[]`.  The code does not distinguish the two cases;
a correct fix should set `ACCEPTED` only when the command is present, or
otherwise prevent sub-case 2 from installing a nil command.

**Impact.**  For command-holding acceptors, recovery sub-case 2 is not reached
and an accepted value is reported as merely pre-accepted.  The slow-path
F1 cluster test's prepare replies therefore carry `PREACCEPTED` status even
though those replicas accepted the value.  The no-command case remains
unresolved separately.

Calibration: the three-line diagnostic fix (F1/F2/F20) makes the recovery
tests pass without changing `handleAccept`, so I have not shown that the
missing status causes an observable failure.  F4 is therefore recorded as a
protocol-state/semantic deviation, not a demonstrated safety or liveness
defect.

## F5. PreAccept writes the command into the leader's row

**Expected.**  A `PreAccept` for `(Replica, Instance)` must update that
instance: `inst.Cmds = preAccept.Command`, as the ordinary `else` branch does
at `epaxos.go:819`.  The accepted branch is the path taken when the instance is
already accepted/committed but the local acceptor does not have the command
(for example after receiving an Accept before a PreAccept).

**Affected code.**  `handlePreAccept`, `epaxos.go:808-814`:

```go
if inst.Status >= ACCEPTED {
    if inst.Cmds == nil {
        r.InstanceSpace[preAccept.LeaderId][preAccept.Instance].Cmds = preAccept.Command
        ...
```

It writes to `[LeaderId][Instance]`, not `[Replica][Instance]`.

**Necessary conditions.**  A `PreAccept` whose `LeaderId` differs from
`Replica` (a recovery leader or a forwarded proposal) arrives for an instance
that is `ACCEPTED` or later and has no local command.  The state is normally
reached through prepare recovery; see F4 for the separate question of whether
ordinary Accept handling should also set `ACCEPTED`.

**Observed.**  `TestAuditPreAcceptStoresCommandInAddressedInstance` puts an
unrelated command in `[3][0]`, then delivers a PreAccept for `[0][0]` with
`LeaderId=3`:

```
target Cmds is still nil
unrelated [3][0] Cmds=[{1 1 [110 101 119]}]
PreAccept for replica 0 wrote its command into instance [leader=3][0],
overwriting unrelated command ...
```

`TestAuditPreAcceptOutOfPlaceStoreDoesNotPanic` delivers the same message when
`[3][0]` is nil:

```
handlePreAccept panicked because instance [leader=3][0] was nil:
runtime error: invalid memory address or nil pointer dereference
```

**Impact.**  The addressed instance never receives its command.  The leader's
row at the same instance number is overwritten, which can corrupt an unrelated
instance's value, or the replica crashes if that slot is nil.  This is a local
state-corruption defect; a cluster-wide divergence is possible when the
overwritten instance is later executed.

## F6. TryPreAccept success is reported with the wrong value ballot

**Expected.**  A responder that accepts a TryPreAccept at ballot `b` must
record `vbal = b`.  `handleTryPreAcceptReply` counts the reply as a success
only when `tpar.VBallot == lb.lastTriedBallot` (`epaxos.go:1425`).  The
ordinary PreAccept handler does exactly this at `epaxos.go:825`.

**Affected code.**  `handleTryPreAccept`, `epaxos.go:1338-1350`: on a
successful conflict check it sets `Cmds`, `Seq`, `Deps`, and `Status`, but not
`inst.vbal`; the reply at line 1348 uses `inst.vbal`.  For a previously
unseen instance, `newInstanceDefault` sets `vbal = -1`.

**Necessary conditions.**  A recovery reaches sub-case 4 and broadcasts
TryPreAccept to a replica that does not already have the value at that ballot.

**Observed.**  `TestAuditTryPreAcceptRecordsVBallot` drives the handler and
decodes the actual reply:

```
after TryPreAccept: Status=1 bal=7 vbal=-1
TryPreAcceptReply: Ballot=7 VBallot=-1 Status=0
```

Since `-1 != 7`, the leader's `handleTryPreAcceptReply` takes the `else`
branch, increments `nacks`, and marks the acceptor impossible.

**Impact.**  Successful TryPreAccept responses are treated as rejections.
Recovery cannot complete through sub-case 4 and falls back to reelection or
deferral; this is a liveness defect in the recovery path.  It can also make
the leader abandon a recovery that should have succeeded.

## F7. Higher-ballot AcceptReply is silently discarded

**Expected.**  A reply whose ballot is newer than the leader's
`lastTriedBallot` means another round has superseded this one.  It must be
counted as a nack, and once enough nacks arrive the leader must start a new
prepare (the pattern in `handlePreAcceptReply`, `epaxos.go:858-868`, and in
`paxos/paxos.go:631-643`).

**Affected code.**  `handleAcceptReply`, `epaxos.go:1016-1036`:

```go
if lb.status != ACCEPTED { return }
if lb.lastTriedBallot != areply.Ballot { return }   // returns for both < and >
if areply.Ballot > lb.lastTriedBallot {             // unreachable
    lb.nacks++
    ...
```

**Necessary conditions.**  An acceptor has joined a higher ballot while the
leader is in its accept phase (a concurrent recovery or a delayed accept).

**Observed.**  `TestAuditAcceptReplyCountsHigherBallotAsNack` creates an
`ACCEPTED` leader bookkeeping record at ballot 0 and delivers a reply at
ballot 1:

```
after higher-ballot AcceptReply: nacks=0 lastTriedBallot=0
higher-ballot reply was silently discarded: nacks=0, so the leader never re-prepares
```

**Impact.**  The leader cannot learn that its accept phase has been
superseded.  It keeps waiting for an accept quorum that may no longer be
reachable.  The execution timeout can eventually start a separate recovery,
but the accept-phase nack mechanism is non-functional.

## F8. Commit for an unknown own-row instance panics

**Expected.**  `handleCommit` must be able to create a default instance for a
commit it has not seen (`epaxos.go:1077-1082`) and then apply the commit.  The
re-propose special case must only inspect `clientProposals` when leader
bookkeeping exists.

**Affected code.**  `handleCommit`, `epaxos.go:1088-1095`:

```go
if commit.Replica == r.Id {
    if len(commit.Command) == 1 && commit.Command[0].Op == state.NONE &&
        inst.lb.clientProposals != nil {
```

`newInstanceDefault` creates `lb == nil`, so the first access to
`inst.lb.clientProposals` panics.

**Necessary conditions.**  A replica receives a NOOP commit for an instance in
its own row that it did not create: after a restart with an empty state, or
after another replica recovered that instance while this replica was not
participating.

**Observed.**  `TestAuditCommitForUnknownOwnInstanceDoesNotPanic`:

```
handleCommit panicked on an own-row instance with no bookkeeping:
runtime error: invalid memory address or nil pointer dereference
```

**Impact.**  The replica process crashes while handling a legitimate commit.
This turns a recoverable missing-instance condition into a crash loop.

## F9. Durable metadata format is corrupt

**Expected.**  `recordInstanceMetadata` should write `bal`, `vbal`, `Status`,
`Seq`, and `Deps` to distinct offsets and read them back consistently.

**Affected code.**  `recordInstanceMetadata`, `epaxos.go:199-215`:

```go
b := make([]byte, 9+r.N*4)
binary.LittleEndian.PutUint32(b[0:4], uint32(inst.bal))
binary.LittleEndian.PutUint32(b[0:4], uint32(inst.vbal)) // overwrites bal
b[4] = byte(inst.Status)
binary.LittleEndian.PutUint32(b[5:9], uint32(inst.Seq))  // overlaps status
```

**Observed.**  `TestAuditDurableMetadataLayout` writes `bal=7`, `vbal=3`,
`Status=PREACCEPTED`, `Seq=11` and reads the bytes back:

```
metadata bytes (29): 03 00 00 00 01 0b 00 00 00 ff ...
decoded: bal=3 vbal=2817 status=0
```

There is a second durable-path error at `epaxos.go:774`: `startPhase1`
records `r.InstanceSpace[r.Id][instance]` rather than
`r.InstanceSpace[replica][instance]`.  A recovering leader with
`r.Id != replica` therefore serializes its own row (or a nil slot) instead of
the instance it is recovering.

**Caveat.**  `run.go` always passes `durable=false` to `epaxos.New`, so the
shipped command-line configuration does not exercise this path.  It is a real
package-level defect in the durable option, but not a defect in the default
run.  I did not change the default or the captured implementation to test it.

## F10. Recovery defer-cycle guard is dead code

`newLeaderBookkeeping` initializes `possibleQuorum` to all `false`
(`epaxos.go:1521`).  `handleTryPreAcceptReply` only ever assigns `false`
(`1445-1446`); there is no assignment of `true`.  The guard then indexes the
current reply's acceptor for every loop iteration:

```go
notInQuorum := 0
for q := 0; q < r.N; q++ {
    if !lb.possibleQuorum[tpar.AcceptorId] {  // should be [q]
        notInQuorum++
    }
}
if notInQuorum == r.N/2 { ... }               // 0 or N, never N/2
```

The condition can only be 0 or N, and with the current initialization it is N,
so the defer-cycle prevention at `1466-1478` never runs.  This is a liveness
guard rather than a safety rule.

**Executed.** `TestAuditTryPreAcceptBreaksDeferCycle` sets up the guard's
documented precondition directly: a leader-side recovery at ballot 5, a
deferred-by entry for replica 4 (still possible), and one TryPreAccept reply
that nacks acceptor 0 and conflict replica 3, leaving exactly two of five
acceptors no longer possible.  A working guard restarts recovery and
broadcasts two Thrifty PreAccepts; the captured code broadcasts none:

```
audit_handlers_test.go:855: sent 0 restarted PreAccepts, want 2;
    the defer-cycle guard did not fire
```

Captured output: `audit_defer_cycle_output.txt`.

`diagnostic_fix12/` initializes `possibleQuorum` to all-`true` and indexes the
loop variable `q`.  The test then passes and the five cluster controls are
unchanged; the full diagnostic suite is 38 failures / 6 passes.
Outputs: `diagnostic_fix12_output.txt`, `diagnostic_fix12_all_output.txt`.
This validates the guard mechanics; it is still a liveness recovery path, not
a safety violation.

## F11. Reply-handler robustness and retry omissions

At `epaxos.go:1205-1206`, `inst.lb` is read before the `inst == nil` check at
`1212`, so an unexpected prepare reply for an instance not present locally
panics.  `handlePreAcceptReply` (`848-849`) and `handleAcceptReply`
(`1009-1010`) have the same unguarded `inst.lb` access for replies to unknown
instances.  The normal sender only replies for instances it knows, so the
trigger requires a duplicated/stale reply or a restart that resets state; the
panic is nevertheless reachable from the wire and takes down the process.

**Executed.** `TestAuditReplyHandlersUnknownInstanceDoNotPanic` constructs a
five-replica leader and invokes each handler with a reply for
`InstanceSpace[2][0] == nil`.  All three sub-tests panic:

```
PrepareReply panicked on an unknown instance: runtime error:
    invalid memory address or nil pointer dereference
PreAcceptReply panicked on an unknown instance: runtime error:
    invalid memory address or nil pointer dereference
AcceptReply panicked on an unknown instance: runtime error:
    invalid memory address or nil pointer dereference
```

Captured output: `audit_unknown_reply_output.txt`.

`diagnostic_fix11/` moves the `maxRecvBallot` update ahead of the lookup and
returns when `inst == nil` or `inst.lb == nil` in all three handlers.

At `1216-1218`, a prepare reply with a higher ballot increments `lb.nacks` and
returns, but unlike `handlePreAcceptReply` and `paxos.handlePrepareReply`,
there is no `if nacks+1 > N/2 { makeBallot; bcastPrepare }`.  A recovery whose
responders have all moved to a higher ballot can therefore keep waiting
without retrying at a higher ballot.  This is a liveness issue that needs a
majority of responders to have advanced their ballot, which is why the
smaller scenarios above do not hit it.

**Executed.** `TestAuditPrepareReplyHigherBallotRetriesRecovery` seeds a
leader-side recovery at ballot 5 with two nacks and delivers a reply at
ballot 6, which makes the third nack a majority of N=5.  The captured handler
broadcasts no retry:

```
audit_handlers_test.go:804: sent 0 retried Prepares, want 4 (one per live peer)
```

Captured output: `audit_prepare_retry_output.txt`.  `diagnostic_fix11/` adds
the same majority-nack retry used by `handlePreAcceptReply`; the test then
observes four re-broadcast `Prepare` messages at ballot 10, and both F11
tests pass.  The full diagnostic suite is 37 failures / 7 passes (the other
37 finding tests and all five controls are unchanged).
Outputs: `diagnostic_fix11_output.txt`, `diagnostic_fix11_all_output.txt`.

`handleTryPreAcceptReply` has the same shape at `1419-1421`: any ballot
mismatch returns silently, with no nack count or retry.  I treat this as part
of the same source-based liveness concern, not a separate executed finding.

## F12. TryPreAccept conflict replies always report `ConflictStatus=NONE`

**Expected.**  When `findPreAcceptConflicts` finds a conflicting instance, the
reply's `ConflictStatus` must be that instance's status.  The leader uses
`tpar.ConflictStatus >= ACCEPTED` to set `lb.tpaAccepted` and abandon the
TryPreAccept (`epaxos.go:1449-1455`, with the comment `TLA spec. (page 39)`).

**Affected code.**  `handleTryPreAccept`, `epaxos.go:1332-1348`:

```go
confRep := int32(0)
confInst := int32(0)
confStatus := NONE
if inst.Status == NONE {
    if conflict, cr, ci := r.findPreAcceptConflicts(...); conflict {
        confRep = cr
        confInst = ci
        // confStatus is never assigned
    } else { ... }
}
rtpa := &TryPreAcceptReply{..., confRep, confInst, confStatus}
```

The `findPreAcceptConflicts` API only returns `(bool, replica, instance)`, so
the handler can look up the conflicting instance's `Status` but does not.

**Necessary conditions.**  A TryPreAccept is sent to a replica that has a
conflicting instance in `ACCEPTED`, `COMMITTED`, or `EXECUTED` state.

**Observed.**  `TestAuditTryPreAcceptReportsConflictStatus` creates a
`COMMITTED` conflicting instance at 1.5 and decodes the actual reply:

```
TryPreAcceptReply: conflict=1.5 status=0
ConflictStatus=0, want COMMITTED (4) for the conflicting instance
```

Diagnostic validation in `diagnostic_fix7/`: assigning the conflict instance's
status makes the reply carry `conflict=1.5 status=4` (COMMITTED), and the test
passes.

**Impact.**  The recovering leader never sets `tpaAccepted` from a real
accepted/committed conflict.  It can continue the TryPreAccept attempt and
move to Accept with the new value, despite the TLA-specified rule that an
accepted/committed conflicting instance requires abandoning the attempt.  This
is an ordering/safety risk in recovery; it also defeats the liveness
abandonment path.

## F13. The slow accept path is gated on the fast quorum size

**Expected.**  When a fast quorum cannot be formed (for example because `f`
replicas are down), EPaxos must fall back to the slow path: after a majority
of replicas have pre-accepted, the leader sends Accept.  The accept quorum is
`SlowQuorumSize()-1` replies plus the leader, and `bcastAccept` already sends
to `N/2` peers in thrifty mode (`epaxos.go:571-586`).

**Affected code.**  `handlePreAcceptReply`, `epaxos.go:919-971`: the fast
commit and the slow-path entry use the same threshold:

```go
if inst.lb.preAcceptOKs >= (r.Replica.FastQuorumSize()-1) && precondition { ... commit ... }
else if inst.lb.preAcceptOKs >= r.Replica.FastQuorumSize()-1 { ... start Accept ... }
```

The slow-path threshold should be a slow-quorum/majority threshold, not
`FastQuorumSize()-1`.  With `N=7`, `F=3`, `FastQuorumSize=5`, and
`SlowQuorumSize=4`, a healthy majority of 4 replicas can never supply 4
remote PreAccept replies (the leader has only 3 live peers when 3 replicas are
down), so the second branch is unreachable.

**Necessary conditions.**  `N >= 7` and `f` replicas are unavailable, while a
majority (including the leader) remains alive.  Thrifty mode is always on for
EPaxos (`replica.New(..., true, ...)` in `epaxos.New`).

**Observed.**  `TestAuditSlowPathStartsWithMajority` constructs an `N=7`
instance and delivers three PreAccept replies (self + 3 = a slow majority of
4) with equal attributes:

```
N=7 after self+3 replies (majority=4): preAcceptOKs=3 lb.status=2 inst.status=1
accept phase did not start after a slow-quorum majority; status=2
```

`lb.status=2` is `PREACCEPTED_EQ`; no Accept is sent.

`TestAuditClusterN7FailureStalls` reproduces this with the multi-replica
router: three of seven replicas are down, the leader sends to the three live
peers, and the proposal never leaves PreAccept:

```
N=7, three failed replicas: leader instance status=1 preAcceptOKs=3
proposal did not commit with a live slow majority; status=1
```

Diagnostic validation in `diagnostic_fix8/`: changing only the slow-path
threshold to `SlowQuorumSize()-1` makes the N=7 cluster commit
(`status=4`) and the handler test reach ACCEPTED (`lb.status=3`) after the
self+3 slow majority.  Both F13 tests pass.

**Impact.**  With `N=7` and `f=3` failures, a normal proposal cannot commit
through the fast or slow path; it waits for the 10-second execution timeout
to start recovery (which has its own defects F1/F2).  This is a liveness
failure for a supported cluster size.  The same shape applies to larger odd
`N` whenever the number of live peers is below `FastQuorumSize()-1` but at
least a slow majority.

## F14. A higher-VBallot ACCEPTED reply blocks all later PreAccept replies

**Expected.**  When a PreAccept reply carries a value at a higher value
ballot, the leader should adopt that value and make progress: either start
Accept/commit immediately or continue processing the remaining replies until
it can.  The reply's status should not leave the round with no possible
continuation.

**Affected code.**  `handlePreAcceptReply`, `epaxos.go:870-881`:

```go
if lb.status != PREACCEPTED && lb.status != PREACCEPTED_EQ { return }

inst.lb.preAcceptOKs++

if pareply.VBallot > lb.ballot {
    lb.ballot = pareply.VBallot
    lb.seq = pareply.Seq
    lb.deps = pareply.Deps
    lb.status = pareply.Status      // may become ACCEPTED or COMMITTED
}
```

After the first higher-VBallot `ACCEPTED` reply, `lb.status` is `ACCEPTED`
(3).  The next PreAccept reply hits the guard at line 870 and returns before
`preAcceptOKs` is incremented.  The leader is stuck at one counted reply and
cannot reach either the fast-commit or slow-Accept threshold.

**Necessary conditions.**  A PreAccept reply reports `VBallot > lb.ballot` and
`Status == ACCEPTED` (or `COMMITTED`).  This is the path the code explicitly
supports for adopting a value from a preempting/recovering leader.

**Observed.**  `TestAuditHigherVBallotReplyDoesNotBlockFurtherReplies` sends
the same reply twice:

```
after first reply: preAcceptOKs=1 lb.status=3
after second reply: preAcceptOKs=1 lb.status=3 inst.status=1
no progress: second reply was ignored and neither Accept nor Commit started
(preAcceptOKs=1 inst.status=1)
```

`TestAuditClusterRecoveryStalls` reproduces the same condition through the
multi-replica router: the recovering replica adopts the first committed
PreAccept reply (`lb.status=4`, i.e. COMMITTED) but `preAcceptOKs` remains 1;
the second reply is dropped by the guard.  The instance is left
`PREACCEPTED`/NOOP at ballot 9, and recovery never completes.

The separate fast-commit defect F15 shows what happens when the status guard
does not intervene and the commit path is reached.

Diagnostic validation in `diagnostic_fix4/`: relaxing the guard lets the
second reply be counted (`preAcceptOKs=2`, `lb.status=4`, `inst.status=4`) and
the F14 test passes.  The same copy's restart test exposes the F24 divergence,
so this liveness fix must be paired with persistent instance state/epochs.

**Impact.**  A proposal that encounters an already-accepted value can no
longer make progress in its current round; it waits for the execution timeout
to start recovery.  Combined with F1/F2, that recovery may select or re-propose
the wrong value.

## F15. Fast commit records the value ballot in `bal` but not `vbal`

**Expected.**  When the leader adopts a value at `VBallot=5` and fast-commits
it, both `inst.bal` and `inst.vbal` should identify that value ballot.  A
later Prepare reply reports `inst.vbal`, so `vbal` must not remain at the
initial ballot.

**Affected code.**  `handlePreAcceptReply`, `epaxos.go:919-927`:

```go
lb.status = COMMITTED
inst.Status = lb.status
inst.bal = lb.ballot
inst.Cmds = lb.cmds
inst.Deps = lb.deps
inst.Seq = lb.seq
// inst.vbal is not updated
```

The slow Accept path at `epaxos.go:953-961` has the same omission.

**Necessary conditions.**  A PreAccept reply reports `VBallot > lb.ballot`, the
leader adopts it, and the fast-commit or slow-Accept path runs.

**Observed.**  `TestAuditFastCommitRecordsValueBallot` supplies two replies
with `VBallot=5`, `Status=PREACCEPTED_EQ`:

```
after adopting a preaccepted value at vbal=5: status=4 bal=5 vbal=0
inst.vbal=0, want 5 (the adopted value's VBallot)
```

**Impact.**  A committed instance advertises the wrong value ballot to later
Prepare requests.  A recovering leader can treat an older value at a higher
`VBallot` as newer, or fail to recognize this committed value.  The Prepare
codec defect F2 also discards the field on the wire, so the two defects
compound.

## F16. Startup panics when the host has no route to 8.8.8.8

**Expected.**  Constructing a replica or client with no latency file should
not require external network access.  `NewLatencyTable` already returns nil
when its configuration path is empty (`replica/defs/latency.go:151-154`).

**Affected code.**  `replica/defs/latency.go:234-238`:

```go
func IP() string {
    conn, _ := net.Dial("udp", "8.8.8.8:80")
    conn.Close()                         // conn is nil on dial error
    return conn.LocalAddr().(*net.UDPAddr).IP.String()
}
```

The error is discarded.  `replica.New` evaluates `defs.IP()` unconditionally
as the second argument to `NewLatencyTable` (`replica/replica.go:101`), even
when `defs.LatencyConf` is empty.  `client.NewClientLog` does the same
(`client/client.go:102`).  Since Go evaluates arguments before the call, the
nil dereference happens before `NewLatencyTable` can take its empty-path
early return.

**Necessary conditions.**  The host/network namespace has no route for
`net.Dial("udp", "8.8.8.8:80")`.  This workspace's ordinary shell is such an
environment; the run brief says ordinary shell has no network.

**Observed.**  `TestAuditReplicaConstructionDoesNotRequireExternalRoute` calls
the same constructor used by `epaxos.New`:

```
replica.New panicked during startup: runtime error: invalid memory address or nil pointer dereference
```

`TestAuditIPHelperDoesNotPanic` isolates the helper with the same result.

**Impact.**  In this environment every replica and client process panics at
startup, before any protocol code runs.  If the actual execution backend
provides a default route (even one that drops external packets), the dial may
succeed and this defect is latent; the exact condition should be checked in
that backend.  This is why the audit's protocol reproductions construct the
`Replica` struct directly instead of calling `epaxos.New`.

The full master/client deployment has an additional environment prerequisite:
`master.Register` shells out to `ping` for each replica and calls
`master.Fatal` if it fails (`master/master.go:213-224`).  In this no-network
shell a real master/replica client run is not possible; the in-process router
in `epaxos/audit_cluster_test.go` bypasses master and client startup while
still exercising the real EPaxos handlers and codecs.

## F17. Recovery paths install values without updating the conflict table

**Expected.**  When `handleTryPreAccept` installs a `PREACCEPTED` command in a
previously `NONE` instance, the replica's conflict structures must be updated
the same way `handlePreAccept` updates them (`epaxos.go:827-829`).  Later
`startPhase1`/`updateAttributes` calls use `r.conflicts` for fast dependency
calculation, so a missing entry can hide a preaccepted conflicting instance.
The same requirement applies when `handlePrepareReply` installs a recovered
`COMMITTED`/`ACCEPTED` value into `inst.Cmds` (`epaxos.go:1291-1296`).

**Affected code.**  `handleTryPreAccept`, `epaxos.go:1338-1345`:

```go
inst.Cmds = tpa.Command
inst.Seq = tpa.Seq
inst.Deps = tpa.Deps
inst.Status = PREACCEPTED
// no r.updateConflicts(tpa.Command, tpa.Replica, tpa.Instance, tpa.Seq)
```

The normal PreAccept path calls `updateConflicts`; `handleCommit` also does.
`handlePrepareReply` sets `inst.Cmds = lb.cmds` at `1291` but does not call
`updateConflicts` before entering sub-cases 1/2/3.
For sub-case 1 the omission persists: a later Commit for the same instance
returns early at `handleCommit` because `inst.Status >= COMMITTED`, so it
cannot repair the conflict table.

**Necessary conditions.**  A successful TryPreAccept installs a command on a
replica that previously had no value for the instance, and a later proposal on
that replica conflicts with the command's key before the try-preaccepted
instance is committed.

**Observed.**  `TestAuditTryPreAcceptUpdatesConflicts` sends a TryPreAccept
for a PUT on key 55 and inspects the conflict table:

```
conflicts[3][55] = <nil>
TryPreAccept installed a PREACCEPTED command but left the conflict table empty
```

The instance itself is present and `PREACCEPTED`.

`TestAuditPrepareReplyUpdatesConflicts` drives sub-case 1 with two
`COMMITTED` replies and inspects the same table:

```
after PrepareReply sub-case 1: instance status=4 cmds=[{1 66 [...]}] conflicts=<nil>
recovery installed a committed command but left the conflict table empty
```

`TestAuditPrepareReplyConflictMiss` carries the omission into a subsequent
proposal.  After recovering the committed key on replica 2, the leader
proposes another PUT on the same key and inspects the new dependency vector:

```
new proposal deps=[-1 -1 -1 -1 -1] (recovered instance is 2.0)
new proposal deps[2]=-1, want 0; it misses the recovered committed key
```

The new proposal does not depend on the recovered committed instance.

Diagnostic validation in `diagnostic_fix7/`: adding `updateConflicts` in the
TryPreAccept install path and after PrepareReply installs the value makes the
tables non-empty and changes the next proposal's vector to
`deps=[-1 -1 0 -1 -1]`, correctly depending on the recovered 2.0.  All four
F12/F17 tests pass.

**Impact.**  A subsequent proposal can miss a dependency on the
try-preaccepted or recovered instance and use a too-small `Seq`, the same class
of ordering violation as F3.  For TryPreAccept the window lasts until the
instance is committed (or another message updates its conflict entry); for a
recovered `COMMITTED` value the missing entry persists until some unrelated
preaccept/commit touches the same key.

## F18. Commands over 65535 bytes are silently truncated by the wire codec

**Expected.**  The client's `commandSize` is a configurable option
(`config/config.go:97`, `main.go:135`); a command value of the configured size
must survive the wire codec intact, or the configuration must reject sizes
that the codec cannot represent.

**Affected code.**  `state/state.go:230-255`:

```go
func (t *Value) Marshal(w io.Writer) {
    bs := make([]byte, 4)
    ...
    binary.LittleEndian.PutUint16(bs, uint16(len(*t)))   // 16-bit length
    w.Write(bs)
    w.Write(*t)
}

func (t *Value) Unmarshal(r io.Reader) error {
    bs := make([]byte, 4)
    ...
    len := binary.LittleEndian.Uint16(bs)                // reads low 16 bits
    ...
}
```

The 4-byte field carries only a 16-bit length.  Values of 65536 bytes or more
are truncated to `len mod 65536`; the remaining bytes stay in the stream and
are parsed as the next field or message.  There is no upper-bound check in
`config` or `client`.  The client allocates `make([]byte, c.psize)` with
`psize = CommandSize` (`client/buffer.go:98`, `main.go:135`), so a configured
large value reaches this codec.

**Necessary conditions.**  A client is configured with `commandSize >= 65536`
and sends a correspondingly large value.  The default `aws.conf` uses 1000, so
the default run is unaffected.

**Observed.**  `TestAuditLargeCommandRoundTrip` marshals and unmarshals a
70000-byte PUT value:

```
input value length=70000 decoded value length=4464 (stream=70013)
large command value was truncated: got 4464 bytes, want 70000
```

`TestAuditLargeProposeRoundTrip` embeds the same value in a real `Propose`;
the following timestamp is read from the leftover value bytes:

```
timestamp in=123456789 out=6510615555426900570 value length in=70000 out=4464 stream=70029
large Propose desynchronized: timestamp 123456789 -> 6510615555426900570, value length 70000 -> 4464
```

**Impact.**  A supported configuration with large payloads silently corrupts
commands and desynchronizes the RPC stream; the Propose test shows the
following timestamp being read from the leftover payload bytes.  This is a boundary/limit
defect rather than a consensus-logic defect, and the default payload size is
safe.

## F19. Client closest-replica fallback can select a dead replica

**Expected.**  When the client's co-located/proxy replica is unavailable, the
fallback must select the id of the closest *alive* replica.  EPaxos is
leaderless, and `SendProposal` sends to `c.ClosestId` when `Leaderless` is true
(`client/client.go:175-185`).

**Affected code.**  `findClosest`, `client/client.go:371-378`:

```go
if c.ClosestId == -1 {
    min := math.MaxFloat64
    for i, l := range c.Ping {   // i is Ping-slice index, not replica id
        if l < min {
            min = l
            c.ClosestId = i
        }
    }
}
```

`c.Ping` is appended only for replicas that were alive and pinged
(`client/client.go:347-364`), so its index stops matching the replica id as
soon as an earlier replica is skipped.

**Necessary conditions.**  The client's `server` replica is dead (or otherwise
does not match `addr == c.server`), so `ClosestId` remains -1 and the fallback
runs, and at least one earlier replica is dead.

**Observed.**  `TestAuditFindClosestSkipsDeadReplica` uses a fake `ping`
executable and replicas `10.0.0.1..3` with `alive=[false,true,true]`:

```
replicas=[10.0.0.1 10.0.0.2 10.0.0.3] alive=[false true true] ClosestId=0 Ping=[1 1]
ClosestId=0 selects a dead or invalid replica; want one of the alive ids 1 or 2
```

`TestAuditSendProposalToDeadClosestDoesNotPanic` then sends a proposal with
`ClosestId=0` and a nil writer for replica 0:

```
SendProposal panicked for a dead ClosestId: runtime error: invalid memory address or nil pointer dereference
```

**Impact.**  `SendProposal` then indexes `c.writers[0]`; that writer is nil
because the client only connects to alive replicas, so the client panics
(`client/client.go:183`) or sends to a dead replica.  The fake `ping` is a
test harness, not an implementation change.  The default deployment normally
sets `ClosestId` via the co-located proxy, so this is the failover path.

## F20. Recovery Commit is sent at the old value ballot

**Expected.**  A recovery/accept round at ballot `b` must broadcast Commit
with ballot `b`.  Acceptors that accepted at `b` have `inst.bal == b` and
ignore a Commit with a lower ballot (`epaxos.go:1086-1087`).

**Affected code.**  `bcastCommit`, `epaxos.go:595-605`:

```go
ec := new(Commit)
...
ec.Ballot = lb.ballot
```

`lb.ballot` tracks the value's original PreAccept ballot.  After a recovery
Prepare at a higher ballot, the acceptors have `inst.bal` set to that higher
ballot, but `lb.ballot` may still be the old value ballot.

**Necessary conditions.**  Recovery reaches sub-case 2/3 or TryPreAccept at a
ballot higher than the value's original `vbal`, commits, and broadcasts the
Commit.

**Observed.**  `TestAuditRecoveryCommitUsesCurrentBallot` constructs a leader
with current ballot 9 and value ballot 0:

```
Commit.Ballot=0 (current lastTriedBallot=9, value ballot=0)
Commit.Ballot=0, want the current/lastTried ballot 9; acceptors at that ballot ignore the Commit
```

The diagnostic fix in `work/diagnostic_fix` (not the captured implementation)
changes only the local PrepareReply's `VBallot` to `lb.ballot`.  With that
fix, `TestAuditClusterRecoveryStalls` passes, confirming F1's root, but the
chosen-value tests still fail: the recoverer becomes COMMITTED with the value,
while replicas 1/2 remain PREACCEPTED and 3 remains NONE because they reject
the lower-ballot Commit.  A second diagnostic copy (`work/diagnostic_fix2`)
also sets `ec.Ballot = lb.lastTriedBallot`; with both one-line fixes,
`TestAuditClusterRecoveryStalls`,
`TestAuditClusterChosenValueSurvivesLeaderCrash`, and
`TestAuditClusterSlowPathChosenValueSurvivesLeaderCrash` pass with the chosen
value committed on all five replicas.  This validates F1 and F20 as the two
root causes for those scenarios.  The cluster recoverer matrix still failed
there: recoverers 1/2 produced empty commands because remote `NONE` replies
decoded `VBallot=0` (F2).  Adding the `PrepareReply` codec fix in
`diagnostic_fix3/` makes all four recoverer-matrix paths pass.  The
partitioned test still aborts at its bug-specific “live replicas recovered to
NOOP” precondition; I do not claim those diagnostic-copy results as
captured-code findings.

Running the whole audit suite in the two-line diagnostic copy gives 11 passes
(the four controls plus the handler recovery matrix, committed-recovery,
chosen-value, and slow-path cases) and 25 failures corresponding to the
unrelated findings.
The three-line copy (adding the F2 codec fix) gives 14 passes / 22 failures;
the additional passes are the codec round-trip, PrepareReply ordering, and
cluster recoverer matrix, exactly the F1/F2/F20-dependent cases.
This confirms the fixes are targeted to the recovery root causes rather than
masking the rest of the audit.

**Impact.**  A recovered value can be committed on the recoverer but never
committed/executed on the acceptors that hold it.  This is an independent
agreement-completion defect exposed once F1 is bypassed; the diagnostic copy
is separate from the captured source.

## F21. PrepareReply sub-case 1 does not propagate the recovered commit

**Expected.**  When a recovery leader's Prepare replies show that a value is
already `COMMITTED`, it should propagate a Commit to the other replicas (or at
least to those that reported `PREACCEPTED`/`NONE`) so they can commit and
execute the value.

**Affected code.**  `handlePrepareReply`, `epaxos.go:1298-1299`:

```go
if subCase == 1 {
    // nothing to do
}
```

The recoverer installs `inst.Cmds`/`inst.Status=COMMITTED` at `1291-1296` but
sends no message.

**Necessary conditions.**  The recovery's Prepare replies include a
`COMMITTED` value (sub-case 1) and at least one other replica holds
`PREACCEPTED` or no value.

**Observed.**  `TestAuditPrepareReplySubcase1PropagatesCommit` supplies a
local NONE reply, a `PREACCEPTED_EQ` reply, and then a `COMMITTED` reply:

```
sub-case 1 installed key=88; messages sent to 0 peers
sub-case 1 did not broadcast a Commit; PREACCEPTED/NONE replicas remain stuck
```

The recoverer has the committed value; no peer received a Commit.

The no-op is harmless if the original Commit reached every replica.  The test
constructs the complementary state, where one replica is still
`PREACCEPTED`.

The minimal majority scenario provides the end-to-end consequence:
`TestAuditClusterCommittedMajorityRecoveryDiverges` with the F1/F2/F20 fixes
in `diagnostic_fix3/` leaves replicas 0-3 with the chosen value COMMITTED and
replica 4 with no instance.  Adding the sub-case-1 Commit broadcast in
`diagnostic_fix5/` makes all five replicas COMMITTED with the chosen value.
This validates F21 as the missing propagation step in that recovery.

**Impact.**  The value is safe on the recoverer but the preaccepted/none
replicas remain stuck until an unrelated recovery or timeout.  This is a
liveness/agreement-completion defect, distinct from F20 (Commit ballot) and
F17 (conflict-table update).

## F22. Nil `dlog.Logger` fallback panics

**Expected.**  `dlog.Logger` has explicit nil-receiver branches
(`if l == nil { log.Println(...) }`), which look intended to fall back to the
standard logger.  They should return without dereferencing `l`.

**Affected code.**  `dlog/dlog.go:32-54`, e.g.:

```go
func (l *Logger) Println(v ...any) {
    if l == nil { log.Println(v...) }
    if l.verbose { l.logger.Println(v...) }
}
```

**Necessary conditions.**  A caller passes a nil `*dlog.Logger` to a component
that logs.  `replica.New`/`epaxos.New` accept a logger; the production
`runReplica` passes `dlog.New(...)`, so this is a library/API robustness path,
not the default deployment.

**Observed.**  `TestAuditNilLoggerDoesNotPanic` calls `Println` on a nil
`*Logger`:

```
2026/10/18 01:09:57 audit nil logger
nil *Logger panicked instead of using the fallback logger: runtime error: invalid memory address or nil pointer dereference
```

The fallback log line is emitted, then `l.verbose` panics.

**Impact.**  The intended nil-logger fallback crashes instead of logging;
severity is low because the shipped callers pass a non-nil logger.

## F23. Nil ProxyInfo panics for configs without a Proxy section

**Expected.**  `config.Read` permits a configuration without a
`-- Proxy --` section and leaves `c.Proxy` nil.  The proxy methods used by the
run path should either return the no-proxy defaults or `Read` should
initialize a default `ProxyInfo`.  Some methods (`Servers`, `ServerClients`,
`Clients`) already nil-check, so the nil-safety intent is inconsistent.

**Affected code.**  `config/proxy.go:53-78` (`IsProxy`, `IsLocal`, `ProxyOf`),
`main.go:132` (`c.Proxy.ProxyOf(...)`), and
`replica/replica.go` `clientListener` (`r.Config.Proxy.IsProxy(...)`).

**Necessary conditions.**  A deployment config has no Proxy section, so
`Config.Proxy` is nil, and a client starts or connects.

**Observed.**  `TestAuditNilProxyDoesNotPanic` calls the methods on a nil
`*ProxyInfo`:

```
nil *ProxyInfo panicked instead of returning the no-proxy default: runtime error: invalid memory address or nil pointer dereference
```

**Impact.**  A config accepted by `Read` can panic the client at startup or
the replica on the first client connection.  The default `aws.conf` includes a
Proxy section, so the shipped configuration is unaffected; the defect is in
config robustness.

## F24. Restarted owner reuses a committed instance number

**Expected.**  A replica that restarts with empty state must not begin
proposing new commands at instance numbers that other replicas already have
committed for that replica.  It should recover/persist its instance counter
and committed instances, or use a fresh epoch, before accepting new proposals.
This is the standard crash-restart expectation for a crash-fault-tolerant
consensus system.

**Affected code.**  `handlePropose` increments
`r.crtInstance[r.Id]` from its fresh value `-1`
(`epaxos.go:724-745`); `runReplica` builds a fresh `Replica` with empty
`InstanceSpace` and counters.  The shipped `run.go` passes `durable=false`,
and the source comment says checkpoints were removed.  There is no
recovery/epoch mechanism that prevents instance-number reuse after restart.

**Necessary conditions.**  A replica (the instance owner) crashes and
restarts with empty state, retaining its identity; a client sends a new
proposal to it before the old committed instances are recovered; other
replicas still hold the old committed instance.

**Observed.**  `TestAuditClusterRestartReusesCommittedInstance` commits
"old" at instance 0.0 on all replicas, replaces replica 0 with a fresh
empty replica, and proposes "new" on replica 0:

```
replica 0: status=1 cmds=[{1 7 [110 101 119]}]   // "new", PREACCEPTED
replica 1: status=4 cmds=[{1 7 [111 108 100]}]   // "old", COMMITTED
replica 2: status=4 cmds=[{1 7 [111 108 100]}]   // "old", COMMITTED
replica 3: status=4 cmds=[{1 7 [111 108 100]}]   // "old", COMMITTED
replica 4: status=4 cmds=[{1 7 [111 108 100]}]   // "old", COMMITTED
```

The restarted owner has a conflicting PREACCEPTED value for the same
logical instance that the other replicas already committed.  In the
captured code, the higher-VBallot status guard (F14) prevents the
restarted owner from counting enough replies to commit "new"; the round
stalls.  Diagnostic validation in `diagnostic_fix4/` (F1/F2/F20 fixes plus a
relaxed F14 guard) turns that stall into an all-alive divergence: replica 0
reaches COMMITTED "new" while replicas 1-4 remain COMMITTED "old".  Thus F14's
liveness fix alone is unsafe without persistent instance state/epochs.

Positive control: `TestInvestigationRestartWithRestoredCounter` restores
instance 0.0 and `crtInstance[0]=0` on the fresh replica.  The new proposal
then uses instance 0.1; all five replicas retain committed 0.0 "old" and
commit 0.1 "new".  This validates the persistence/epoch direction of the F24
remediation.  The same positive control also passes in `diagnostic_fix4/`
(F1/F2/F20 + relaxed F14 + restored state), showing the F14 liveness fix and
persistence together avoid both the stall and the divergence.

**Impact.**  The system cannot safely support replica restart with the
shipped `durable=false` configuration: instance numbers are reused and the
restarted owner can conflict with an already committed instance.  This is a
crash-recovery design gap, distinct from F9's metadata-layout defect.

## Conclusion

The normal all-alive path and ordinary message reordering work in the
in-process cluster controls.  The failures are concentrated in crash
recovery and boundary handling:

- A value fast-chosen or slow-Accept-chosen before the proposing leader's
  Commit broadcast can be replaced by NOOP on the recovering replicas.
- With a partitioned (not crashed) leader, healing leaves all five replicas
  alive but divergent: the old leader executes the chosen PUT while the others
  execute NOOP.
- The recovery Prepare path has independent VBallot, Commit-ballot,
  conflict-table, acceptor-status, and missing-Commit defects.
- Additional defects affect batched dependency calculation, the N=7 slow path,
  post-accept status, and wire/client boundaries.
- A replica restarting with empty state reuses instance numbers and conflicts
  with already committed values (F24); the shipped run has no durable state.

These are implementation correctness defects, not merely a lack of durability
or test-environment issues.

No further high-value captured-code targets were identified in the remaining
reviewed areas.  The full process path requires the `isolated_exec` backend,
and the remaining F4 no-command question requires the corrected EPaxos
TLA/upstream reference rather than further local experimentation.

## Coverage and limits

Reviewed: `epaxos.go`, `defs.go`, `exec.go`; `state`; `client`; `replica`
(including the quorum/connection paths used by EPaxos); `config`; `dlog`;
`master`/`run.go` startup paths; and the relevant deployment configuration.

Executed: synchronous handler tests for every recovery branch; wire-codec
round trips; five-replica fast/slow/partitioned cluster scenarios; a
seven-replica failure scenario; fixed-seed shuffled delivery; client failover
with a fake `ping`; and two separate diagnostic copies for root-cause
validation.

Not exercised end to end: the full master/replica/client process startup
(blocked by F16 and the master's `ping` dependency in this shell); durable mode
(`run.go` passes `durable=false`; F9 is package-level only); pipeline mode
(`aws.conf` has `pipeline: false`); and non-EPaxos protocols, which are outside
this run's variant.

The ordinary-shell sandbox also denies loopback TCP
(`listen tcp 127.0.0.1:0: socket: operation not permitted`), so a real-process
cluster requires the `isolated_exec` backend rather than this shell.  See
`audit_loopback_output.txt`.

`go vet ./...` reports only unkeyed struct literals in `replica`/`paxos`/
`epaxos` (field orders checked), plus unreachable/capture warnings in
`curp`/`swift`, which are outside this variant.  It found no new EPaxos logic
warning; see `go_vet_output.txt`.  `staticcheck` and `golangci-lint` are not
installed in the offline toolchain, so `go vet` is the available static
analysis.

The audit includes a 50-iteration randomized normal-path campaign, deterministic
recovery/recoverer matrices, and a 100-seed randomized initial-drop campaign.
The fault campaign produced 41 passes, 58 cases where a proposed value was
replaced by NOOP on all committed replicas, and 1 mixed-value divergence:
seed 57 left replicas 0-2 COMMITTED with the chosen PUT and replicas 3-4
COMMITTED with NOOP, all alive.  The mixed case is a concrete all-alive
counterexample; the all-NOOP losses are classified coarsely and do not
independently prove each lost value was fast-chosen.  The deterministic
chosen-value tests establish that.  The campaign found no new root cause.

## Unresolved / not claimed

- F4's **no-command variant** (`handleAccept` leaving `Status` as `NONE` when
  `Cmds` is empty) remains an investigation; the command-holding case is
  confirmed.  See F4 for the no-command alternative explanation.
- The two-line diagnostic copy's empty-`Cmds` path was resolved by adding the
  `PrepareReply` codec fix in `diagnostic_fix3/`; it is an F2 consequence, not
  a separate captured-code finding.
- `exec.go:166-168` orders same-seq, same-replica instances in an SCC by
  `proposeTime`, which is stamped locally in `newInstance` and is not carried
  in any RPC.  `TestInvestigationExecOrderUsesReplicatedIdentity` constructs
  two replicas with the same committed instances but reversed local
  `proposeTime` values, and observes opposite execution orders and final values
  ("a" vs "b").  I did **not** count this as a defect: the constructed SCC uses
  two conflicting same-key commands with the same `Seq` from one replica, which
  the normal `updateAttributes` path prevents by bumping `Seq`.  The ordering
  concern is real for the execution function, but I have not shown a reachable
  same-row/same-seq SCC containing conflicting commands.  It remains an
  investigation, not a confirmed finding.  Observed output:
  `audit_exec_order_output.txt`.
- The duplicated sub-case 3/4 condition at `epaxos.go:1269-1272` makes
  sub-case 4 unreachable.  For the supported odd replica counts (3, 5, 7) the
  two thresholds happen to be equal, so I could not show a behavioral
  difference; I did not count it as a confirmed defect.
- `findPreAcceptConflicts` breaks the scan at `i == instance` for the target's
  row, so it returns "no conflict" when the target itself holds a different
  `PREACCEPTED` value (`TestInvestigationSelfConflictSkip` observes
  this).  I did **not** count it as a defect: the initial status check in
  `handleTryPreAccept` only overwrites a `NONE` instance, so a different
  pre-accepted target is normally reported back as an old `VBallot` and
  treated as a nack.  The self-skip may therefore be deliberate; a full
  schedule would be needed to show otherwise.
- `exec.go:60-68` contains an empty `transconf` conflict loop, but `run.go`
  passes `transconf=false`; it is not reachable in the shipped configuration.
- A 100-seed randomized initial-drop campaign was run (41 pass, 58 NOOP-on-all
  losses, 1 mixed divergence).  Seed 57 is an all-alive counterexample:
  replicas 0-2 COMMITTED the chosen PUT, 3-4 COMMITTED NOOP.  A full
  crash/drop scheduler and a real network run were not built.
