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

## Validated recovery roots

Three independent defects are validated in separate diagnostic copies:

1. **F1** — `startRecoveryForInstance` overwrites the local value ballot with
   the new prepare ballot, so the synthetic local `PrepareReply` masks real
   remote values.
2. **F2** — `PrepareReply.Marshal`/`Unmarshal` omit `VBallot`, so remote
   value ordering is lost.
3. **F20** — recovery Commit is broadcast with `lb.ballot` instead of the
   current/lastTried ballot, so acceptors at the higher ballot ignore it.

`diagnostic_fix/`, `diagnostic_fix2/`, `diagnostic_fix3/` apply these fixes
one at a time.  With all three, the recovery-stall, fast-chosen, slow-chosen,
and all four cluster-recoverer tests pass.  The three-line suite is 14 passes /
22 unrelated failures, so the fixes do not mask the rest of the audit.

## Other high-impact findings

- F3: batched proposals miss the newest conflicting dependency.
- F5: PreAccept writes the command into `[LeaderId]` instead of the addressed
  `[Replica]` row, corrupting another instance or panicking.
- F12/F17: TryPreAccept reports no conflict status and recovery paths leave
  the conflict table empty; a later proposal was observed with
  `deps=[-1 -1 -1 -1 -1]` after recovering a conflicting committed key.
- F13: N=7 with three failures never leaves PreAccept; the slow path requires
  a fast-quorum number of replies.
- F14: a higher-VBallot ACCEPTED reply blocks all later PreAccept replies.
- F21: PrepareReply sub-case 1 installs a committed value but broadcasts no
  Commit.
- F24: a restarted owner reuses an already committed instance number; the
  cluster ends with a conflicting PREACCEPTED value on the restarted replica
  and the old COMMITTED value elsewhere.  The shipped run has no durable
  instance state.

## Boundary / environment findings

- F4: command-holding acceptors stay `PREACCEPTED`; semantic deviation, not
  shown to cause failure (Medium).
- F18: command values over 65535 bytes are silently truncated; the following
  Propose timestamp is misread.
- F19: client `ClosestId` fallback can select a dead replica and panic in
  `SendProposal`.
- F22/F23: nil `dlog.Logger` and nil `Config.Proxy` fallbacks panic.
- F16: `defs.IP()` panics with no external route; startup is blocked in this
  shell.  The master also requires `ping`; loopback TCP is denied
  (`socket: operation not permitted`).

## Status

- 24 findings documented; details in `report.md`.
- 35 epaxos finding tests fail as intended; five cluster controls pass.
- Client, dlog, and config tests fail separately.
- Random 20-seed initial-drop campaign: 11 pass / 9 NOOP losses /
  0 mixed-value divergences (corroborates F1 but does not independently
  establish chosen-value loss).
- `go build ./...` passes; captured source unchanged.

Reproduce with `./run_audit.sh`; per-finding tests and outputs are in
`validation_matrix.md`; proposed fixes are in `remediation.md`.
