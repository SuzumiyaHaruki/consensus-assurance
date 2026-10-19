# EPaxos audit report

Source under audit: `../source` (identity `35c69365f1c7737a08e237bfbaf828ee68897080`).
The `work/` tree is a byte-identical copy of that source; the only added files are
the `epaxos/audit_*_test.go` tests, captured output files, and this report.

Method: source review of the EPaxos state machine and wire codecs, followed by
synchronous handler tests that construct a replica without starting its network
loop.  Outbound RPCs are routed to a `bufio.Writer` over `bytes.Buffer` when the
reply itself is part of the observable behavior.  A second harness
(`epaxos/audit_cluster_test.go`) routes real marshaled RPCs between five
or seven in-process replicas, so the normal path, conflicting proposals, a
partitioned-replica recovery, and an N=7 failure case are exercised as
multi-replica event sequences.  The tests do not patch or otherwise alter the
implementation.

Four cluster controls pass and show the harness itself is not failing
everything: `TestAuditClusterHappyPath` (one proposal commits and executes on
all five replicas), `TestAuditClusterConflictPath` (two concurrent proposals on
the same key commit and produce the same final value), and
`TestAuditClusterShuffledNormalPath` / `TestAuditClusterShuffledSeeds` (fixed
seeds 1-20 with randomly reordered message delivery converge on the same
committed instances and state).

Reproduction:

```
cd work
go test ./epaxos -run TestAudit -v
```

Cluster controls (all pass):

```
go test ./epaxos -run 'TestAuditClusterHappyPath|TestAuditClusterConflictPath|TestAuditClusterShuffledNormalPath|TestAuditClusterShuffledSeeds' -v
```

Cluster failure reproductions (both fail):

```
go test ./epaxos -run 'TestAuditClusterRecoveryStalls|TestAuditClusterN7FailureStalls|TestAuditClusterChosenValueSurvivesLeaderCrash|TestAuditClusterSlowPathChosenValueSurvivesLeaderCrash' -v
```

Current result: the four cluster controls pass; 26 finding tests fail, each
with an assertion that states the expected protocol behavior.  The tests are
supposed to fail against the captured implementation.

Captured output: `audit_all_output.txt`.  Individual captures:
`audit_cluster_happy_output.txt`, `audit_cluster_recovery_output.txt`,
`audit_cluster_n7_output.txt`, `audit_cluster_conflict_output.txt`,
`audit_cluster_chosen_output.txt`,
`audit_cluster_slow_chosen_output.txt`,
`audit_cluster_shuffled_output.txt`, `audit_cluster_shuffled_seeds_output.txt`,
`audit_codec_recovery_output.txt`, `audit_recovery_safety_output.txt`,
`audit_recovery_local_value_output.txt`,
`audit_exec_order_output.txt`,
`audit_batch_flow_output.txt`, `audit_batch_output.txt`,
`audit_slowpath_output.txt`, `audit_higher_vbal_output.txt`,
`audit_fast_vbal_output.txt`, `audit_tpa_status_output.txt`,
`audit_tpa_conflicts_output.txt`,
`audit_prepare_conflicts_output.txt`,
`audit_conflict_output.txt`, `audit_extra_output.txt`,
`audit_startup_output.txt`, `audit_ip_output.txt`,
`audit_accept_status_output.txt`, `audit_accept_command_output.txt`.

The unclaimed investigation `TestInvestigationSelfConflictSkip` can be run
separately; it is intentionally excluded from the `TestAudit` pattern:

```
go test ./epaxos -run TestInvestigationSelfConflictSkip -v
go test ./epaxos -run TestInvestigationExecOrderUsesReplicatedIdentity -v
go test ./epaxos -run TestInvestigationAcceptStatus -v
```

## Summary

| ID | Severity | Kind | Location | Evidence |
|----|----------|------|----------|----------|
| F1 | Critical | Safety: recovery replaces a chosen value with NOOP on all live replicas (fast- and slow-path cluster reproductions) | `epaxos/epaxos.go:1153-1159` | executed (handler + 5-replica clusters) |
| F2 | Critical | Safety: `PrepareReply.VBallot` is dropped by the codec; recovery selects a stale value | `epaxos/defs.go:153-253` | executed |
| F3 | High | Safety/linearizability: batched proposals miss the newest conflicting dependency and use a too-small seq | `epaxos/epaxos.go:668-680` | executed |
| F4 | High | Recovery semantics: an acceptor that already holds the command does not record `ACCEPTED` | `epaxos/epaxos.go:992-1000` | executed (handler + slow-path cluster); no-command case investigated separately |
| F5 | High | State corruption / panic: PreAccept stores the command in the leader's row | `epaxos/epaxos.go:810` | executed |
| F6 | Medium | Liveness: successful TryPreAccept is reported with the wrong `VBallot` and counted as a nack | `epaxos/epaxos.go:1345-1349`, `1425` | executed |
| F7 | Medium | Liveness: higher-ballot AcceptReply branch is unreachable | `epaxos/epaxos.go:1024-1036` | executed |
| F8 | Medium | Crash: Commit for an unknown instance in the replica's own row dereferences nil bookkeeping | `epaxos/epaxos.go:1088-1095` | executed (conditional) |
| F9 | Low | Durability: metadata layout overwrites `bal` and overlaps `Status`/`Seq` | `epaxos/epaxos.go:199-215` | executed; durable mode is not selected by `run.go` |
| F10 | Medium | Liveness: recovery defer-cycle guard is dead code | `epaxos/epaxos.go:1459-1464`, `1521` | source-based |
| F11 | Low | Robustness: prepare-reply handler dereferences `inst` before its nil check; higher-ballot prepare replies never trigger a retry | `epaxos/epaxos.go:1205-1218` | source-based |
| F12 | High | TryPreAccept conflict replies always report `ConflictStatus=NONE` | `epaxos/epaxos.go:1332-1348` | executed |
| F13 | High | Liveness: the slow accept path requires a fast-quorum number of PreAccept replies; N=7 with f failures stalls | `epaxos/epaxos.go:919-971` | executed |
| F14 | High | Liveness: a higher-VBallot ACCEPTED reply blocks all later PreAccept replies | `epaxos/epaxos.go:870-881` | executed |
| F15 | Medium | Fast commit sets `bal` to the adopted value ballot but leaves `vbal` at the old ballot | `epaxos/epaxos.go:919-927` | executed |
| F16 | High (startup) | Panic when the host has no route to 8.8.8.8, even with no latency file | `replica/defs/latency.go:234-238`, `replica/replica.go:101`, `client/client.go:102` | executed |
| F17 | High | Recovery/ordering: TryPreAccept and PrepareReply sub-case 1 install values without updating the conflict table | `epaxos/epaxos.go:1291-1296`, `1338-1345` | executed |

Most consequential for the recovery claim: F1 and F2 (the prepare phase can
discard a chosen/committed value or select a stale one), with F1 now reproduced
end to end: both a fast-chosen and a slow-Accept-chosen value are replaced by
NOOP on all live replicas after the proposing leader crashes.  F14 (a higher-value-ballot reply stalls the
round), F13 (N=7 loses liveness under f failures), and F3 (batched proposals
miss dependencies) are also high-impact.  F12 and F17 add recovery-ordering
errors (missing conflict status and missing conflict-table updates).  F16 is a
deployment blocker in this no-network environment rather than a consensus-logic
defect.  F4 is a confirmed acceptor-state defect when the command is already
present; its no-command variant remains an investigation.

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

**Impact.**  The prepare-phase decision is wrong: a replica that has no value
concludes that no value exists even when a slow quorum of replies reports a
preaccepted or committed one, and starts phase 1 with NOOP.  The cluster test
shows that the rest of recovery does not necessarily re-learn the value; it
can commit NOOP on every live replica while the crashed leader holds the
chosen value.  This is independent of the codec defect in F2.

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

## F10. Recovery defer-cycle guard is dead code (source-based)

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
guard rather than a safety rule; I did not build a defer-cycle schedule to
demonstrate it end to end.

## F11. Prepare-reply robustness and retry omissions (source-based)

At `epaxos.go:1205-1206`, `inst.lb` is read before the `inst == nil` check at
`1212`, so an unexpected prepare reply for an instance not present locally
panics.  The normal sender only prepares instances it knows, so this is a
robustness issue unless messages are duplicated or state is reset.
`handlePreAcceptReply` (`848-849`) and `handleAcceptReply` (`1009-1010`) have
the same unguarded `inst.lb` access for replies to unknown instances.

At `1216-1218`, a prepare reply with a higher ballot increments `lb.nacks` and
returns, but unlike `handlePreAcceptReply` and `paxos.handlePrepareReply`,
there is no `if nacks+1 > N/2 { makeBallot; bcastPrepare }`.  A recovery whose
responders have all moved to a higher ballot can therefore keep waiting
without retrying at a higher ballot.  This is a liveness issue; I did not
produce a scheduler that shows the stall end to end.

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

**Impact.**  A subsequent proposal can miss a dependency on the
try-preaccepted or recovered instance and use a too-small `Seq`, the same class
of ordering violation as F3.  For TryPreAccept the window lasts until the
instance is committed (or another message updates its conflict entry); for a
recovered `COMMITTED` value the missing entry persists until some unrelated
preaccept/commit touches the same key.

## Unresolved / not claimed

- F4's **no-command variant** (`handleAccept` leaving `Status` as `NONE` when
  `Cmds` is empty) remains an investigation; the command-holding case is
  confirmed.  See F4 for the no-command alternative explanation.
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
- No randomized fault-injection scheduler was built.  The in-process router
  drives real RPCs between five/seven replicas for the happy path, conflict
  path, partitioned recovery, and N=7 failure cases, but it is a controlled
  event sequence rather than a randomized scheduler or a real network run.
