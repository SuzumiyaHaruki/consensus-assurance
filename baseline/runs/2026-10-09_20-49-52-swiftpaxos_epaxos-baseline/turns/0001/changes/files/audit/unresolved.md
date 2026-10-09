# Unresolved investigations

These are source observations or possible follow-ups, not additional confirmed findings.

- Strengthen recovery finding with an end-to-end reachable message schedule including automatic detection of a missing slot. The deterministic handler trace now generates the original commit through the initial leader fast path, but explicitly calls recovery.
- `startPhase1` constructs an Instance with computed sequence but initializes leader bookkeeping sequence to -1; broadcast uses bookkeeping. Check effects beyond the known dependency omissions.
- `handlePreAccept` fills missing commands through `InstanceSpace[LeaderId]` instead of `[Replica]`. On recovery these IDs differ; establish a supported trace reaching this branch with missing commands.
- `handleCommit` dereferences `inst.lb.clientProposals` for an own-row NOOP although a newly created instance has nil bookkeeping. Establish a recovery-generated no-op commit at the live owner of an unallocated hole.
- Durability: metadata writes bal and vbal at the same offset; startPhase1 records the local row even for another row's recovery. Default runner passes durable=false and stable-store setup/restart support need checking before reporting supported-mode defects.
- Recovery subcases 3 and 4 have identical predicates, making 4 unreachable. Quorum formulas and count semantics need careful review for N=5 and N=7, without assuming a different F convention.
- SCC tie-breaking uses local proposeTime after sequence and replica rather than instance ID. Need establish reachability of equal-sequence same-row members of one SCC with different arrival orders.
- Thread synchronization and global executor stack: source concerns, not race-tested. Production normally runs one replica per process, so avoid relying on multi-replica-in-process behavior as a production defect.
- State Value marshaling writes a uint16 length despite arbitrary byte slices and a four-byte header. Need determine intended supported maximum client payload before classifying overflow.
