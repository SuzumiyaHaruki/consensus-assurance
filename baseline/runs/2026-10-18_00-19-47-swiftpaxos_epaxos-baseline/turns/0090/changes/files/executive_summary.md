# EPaxos audit — executive summary

Source: `../source`, identity `35c69365f1c7737a08e237bfbaf828ee68897080`.
The captured implementation in `work/` is byte-identical and was not modified.

## Critical result

The implementation is not correct under crash recovery.  A value can be
chosen by a fast PreAccept quorum or by a slow Accept quorum and then be
replaced by NOOP on the recovering/live replicas.

The strongest reproduction is `TestAuditClusterPartitionedLeaderKeepsChosenValue`:

```
replica 0: status=4 cmds=[{1 7 [99 104 111 115 101 110]}]   // "chosen"
replica 1: status=4 cmds=[{0 0 []}]                          // NOOP
replica 2: status=4 cmds=[{0 0 []}]                          // NOOP
replica 3: status=4 cmds=[{0 0 []}]                          // NOOP
replica 4: status=4 cmds=[{0 0 []}]                          // NOOP
replica 0 state: key7=[99 104 111 115 101 110] present=true
replicas 1-4 state: key7=<nil> present=false
```

This is an all-alive state-machine divergence after a partitioned (not
crashed) leader reconnects.

The minimal deterministic form is
`TestAuditClusterCommittedMajorityRecoveryDiverges`: 0-2 are already
COMMITTED with "chosen", 3-4 have no instance, and recovery by 3 commits NOOP
on 3-4—no random drops required.

## Validated recovery roots

Four independent defects are validated in separate diagnostic copies:

1. **F1** — `startRecoveryForInstance` overwrites the local value ballot with
   the new prepare ballot, so the synthetic local `PrepareReply` masks real
   remote values.
2. **F2** — `PrepareReply.Marshal`/`Unmarshal` omit `VBallot`, so remote
   value ordering is lost.
3. **F20** — recovery Commit is broadcast with `lb.ballot` instead of the
   current/lastTried ballot, so acceptors at the higher ballot ignore it.
4. **F21** — PrepareReply sub-case 1 installs the committed value but does
   not broadcast a Commit, so replicas that missed it remain without it.

`diagnostic_fix/`, `diagnostic_fix2/`, `diagnostic_fix3/`,
`diagnostic_fix5/` apply these fixes one at a time.  With F1/F2/F20, the
recovery-stall, fast-chosen, slow-chosen, and all four cluster-recoverer
tests pass; the minimal majority test then improves to replicas 0-3 chosen
and 4 missing.  Adding F21 in `diagnostic_fix5/` makes all five replicas
COMMITTED on the chosen value.  The three-line suite is 14 passes / 22
unrelated failures, so the fixes do not mask the rest of the audit.

## Other high-impact findings

- F3: batched proposals miss the newest conflicting dependency; removing the
  inner-loop `break` in `diagnostic_fix6/` makes both F3 tests pass.
- F5: PreAccept writes the command into `[LeaderId]` instead of the addressed
  `[Replica]` row, corrupting another instance or panicking.  The combined
  `diagnostic_fix9/` copy also validates the minimal fixes for F4
  (command-holding), F5, F6, F7, F8, and F15.
- F12/F17: TryPreAccept reports no conflict status and recovery paths leave
  the conflict table empty; a later proposal was observed with
  `deps=[-1 -1 -1 -1 -1]` after recovering a conflicting committed key.
  `diagnostic_fix7/` validates the conflict-status/table fixes (`deps` becomes
  `[-1 -1 0 -1 -1]`).
- F13: N=7 with three failures never leaves PreAccept; the slow path requires
  a fast-quorum number of replies.  `diagnostic_fix8/` validates the
  `SlowQuorumSize()-1` threshold fix.
- F14: a higher-VBallot ACCEPTED reply blocks all later PreAccept replies;
  `diagnostic_fix4/` validates the guard, with the F24 persistence pairing.
- F21: PrepareReply sub-case 1 installs a committed value but broadcasts no
  Commit.
- F25: the sub-case 5/6 recovery fallback checks `cmds != nil`; a decoded
  zero-length command list is non-nil, so phase 1 proposes and commits an
  empty command instead of NOOP.  Latent behind F1 in the captured build, it
  appears in 94/500 seeds once F1 is fixed; `diagnostic_fix13/` adds
  `len(cmds) > 0` and reduces the sweep to 0 divergence.
- F26: `startPhase1` stores `-1` in leader bookkeeping while the leader's
  instance has the computed seq; PreAccept therefore broadcasts `seq=-1` and
  followers commit a different sequence from the proposer.
- F27: recovery sub-case 4 (TryPreAccept) is unreachable because its guard is
  identical to sub-case 3.  A naive `f/2` guard makes the branch reachable but
  leaves 85/500 recoveries stalled in PREACCEPTED, so the correct guard needs
  the TLA/upstream reference.
- F28: an acceptor with no command still advances `vbal` on Accept, so its
  PrepareReply advertises an empty value at a real ballot and can mask a
  preaccepted value.  `diagnostic_fix18/` validates the guarded assignment.
- F24: a restarted owner reuses an already committed instance number; the
  cluster ends with a conflicting PREACCEPTED value on the restarted replica
  and the old COMMITTED value elsewhere.  The shipped run has no durable
  instance state.  `diagnostic_fix4/` shows that relaxing the F14 guard makes
  this an all-alive divergence (replica 0 commits "new", replicas 1-4 keep
  "old"), so F14's liveness fix alone is unsafe.

## Boundary / environment findings

- F4: command-holding acceptors stay `PREACCEPTED`; semantic deviation, not
  shown to cause failure (Medium).
- F18: command values over 65535 bytes are silently truncated; the following
  Propose timestamp is misread.
- F19: client `ClosestId` fallback can select a dead replica and panic in
  `SendProposal`.
- F22/F23: nil `dlog.Logger` and nil `Config.Proxy` fallbacks panic.
- F11: all three reply handlers panic on a reply for an unknown instance, and
  a recovery leader that collects a majority of higher-ballot Prepare replies
  never re-broadcasts at a new ballot.  `diagnostic_fix11/` validates both
  fixes.
- F10: the defer-cycle guard can never fire because `possibleQuorum` is
  initialized all-false and the count loop indexes the reply's acceptor
  instead of `q`.  `diagnostic_fix12/` validates the corrected guard.
- F16: `defs.IP()` panics with no external route; startup is blocked in this
  shell.  The master also requires `ping`; loopback TCP is denied
  (`socket: operation not permitted`).

`diagnostic_fix10/` validates the F9, F16, F18, F19, F22, and F23 minimal
fixes; all eight related tests pass.

`diagnostic_fix11/` validates the F11 nil guards and prepare retry;
`diagnostic_fix12/` validates the F10 defer-cycle guard; `diagnostic_fix13/`
validates the F25 NOOP fallback on top of the F1/F2/F20/F21 fixes;
`diagnostic_fix14/` adds the F26 sequence fix and keeps 0 divergence;
`diagnostic_fix15/` is the negative F27 experiment (85/500 recoveries stalled).

## Status

- 28 findings documented; details in `report.md`.
- 43 epaxos finding tests fail as intended; five cluster controls pass.
- Client, dlog, and config tests fail separately.
- Random initial-drop campaign: at 100 seeds, 41 pass / 58 NOOP-on-all losses
  / 1 mixed divergence; extended to 500 seeds, 208 pass / 285 NOOP-on-all /
  7 mixed.  Seed 57 splits 3 PUT / 2 NOOP; seed 266 splits 1 PUT / 4 NOOP even
  though the PUT was already COMMITTED on replica 0.  `diagnostic_fix5/`
  commits the PUT everywhere for seed 266; adding F25's guard in
  `diagnostic_fix13/` yields 406 pass / 94 legitimate NOOP losses / 0
  divergence over the same 500 seeds, and 0 divergence over 1,000 seeds
  (818 pass / 182 legitimate NOOP losses); at 5,000 seeds the fixed stack is
  4,035 pass / 965 NOOP losses / 0 divergence.  Seed 706 adds a 2 PUT / 3 NOOP
  shape; the fixed stack commits the PUT on all five.
- Loss classification over 1,000 seeds finds no fast-path-chosen value among
  the all-NOOP outcomes: captured holder counts are `{1:36, 2:324, 3:222}`,
  fixed `{1:36, 2:146}`; every three-holder case has differing `seq` values,
  so the divergence count remains the safety signal.
- `go build ./...` passes; captured source unchanged.

Reproduce with `./run_audit.sh`; per-finding tests and outputs are in
`validation_matrix.md`; proposed fixes are in `remediation.md`.
