# Unresolved investigations

These are source observations or possible follow-ups, not additional confirmed findings.

- Recovery finding 1 now includes original fast-path commits and the automatic timeout of a hole exposed by a later commit. A live TCP deployment remains untested. Missing unseen dependencies are separately confirmed as finding 6.
- `startPhase1` initializes leader-bookkeeping sequence to -1; finding 7 now demonstrates its contribution to equal-sequence same-row writes. Other consequences remain unexamined.
- `handlePreAccept` fills missing commands through `InstanceSpace[LeaderId]` instead of `[Replica]`. On recovery these IDs differ; establish a supported trace reaching this branch with missing commands.
- `handleCommit` dereferences `inst.lb.clientProposals` for an own-row NOOP although a newly created instance has nil bookkeeping. Establish a recovery-generated no-op commit at the live owner of an unallocated hole.
- Durability: metadata writes bal and vbal at the same offset; startPhase1 records the local row even for another row's recovery. Default runner passes durable=false and stable-store setup/restart support need checking before reporting supported-mode defects.
- Recovery subcases 3 and 4 have identical predicates, making 4 unreachable. Quorum formulas and count semantics need careful review for N=5 and N=7, without assuming a different F convention.
- SCC timestamp tie-break is now confirmed as finding 7 by a full normal-path five-replica handler schedule. The -1 leader-bookkeeping sequence and incoming-sequence conflict-index update enable the equal sequence values in that reproduction.
- Thread synchronization and global executor stack: source concerns, not race-tested. Production normally runs one replica per process, so avoid relying on multi-replica-in-process behavior as a production defect.
- Value length overflow is now confirmed and reported as finding 5, including an executed scan reply from two individually encodable 32 KiB values.
