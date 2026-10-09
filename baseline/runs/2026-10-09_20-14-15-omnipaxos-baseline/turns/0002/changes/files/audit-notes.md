# Continuing audit notes

Confirmed findings and controls are in report.md and audit-repro/src/lib.rs. The harness depends on captured read-only source, not the writable implementation copy. No modifications to implementation.

Unresolved targets (not findings):
- Message coalescing across repeated Promise/AcceptSync sessions: confirmed as Finding 3. Control draining buffered messages before retry passes. Consider other paths that change sessions without resetting cache, but avoid reporting the same cause twice.
- Trimming uses accepted acknowledgments although docs require all decided; inspect recovery from a lost Decide after leader trims. Need actual corruption/liveness consequence before reporting.
- Configuration-ID isolation: confirmed as Finding 4 with legitimately delayed original AcceptDecide. Report explicitly qualifies the transport condition. Cross-configuration Prepare/Compaction/ProposalForward paths remain untested and may share the same isolation cause.
- Persistent storage was source-reviewed briefly; execution of its atomicity/recovery paths remains outstanding. Serialization-error handling appears to leave next_log_key and pending batches mutated on Err (source suspicion only; not tested). The harness currently uses MemoryStorage, which is sufficient for the confirmed no-crash defects.
- Existing sync tests use a latest-value snapshot, which may hide loss of earlier independent keys or duplication. They were read but not executed in this phase.

Tool notes: rg is absent; use find/grep. Offline cargo build of independent harness succeeds. Target artifacts reside under .runtime/cargo-target and are disposable. Tests/logs/lockfile are outside .runtime. The run script records actual Cargo exit status even though expected-bug assertions fail.

## Optional-feature follow-up targets

- LRU serde empty-sequence panic is confirmed as Finding 5, with LFU passing control. Separate audit-unicache crate avoids unifying unicache into the main Value Entry harness.
- LRU and LFU Clone implementations transform encoder state into a decoder and empty the encoder. A second clone therefore appears to lose decoder contents. Check ordinary Message clone behavior separately, accounting for the documented special cache-clone semantics.
- Finding 6 now has a stronger capacity-3 reproduction: after promotion append D,E,F,G,G; followers panic decoding missing encoding 7 in debug AND release. Overflow remains a separate checked-build symptom of same root cause. Release reproduction command/output retained.
- LFU frequency-loss synchronization is confirmed as Finding 7, with deterministic counterexample (ten A, B, resync node3, B,C,C) and no-resync passing control. Does not depend on randomized hash iteration.
- UniCache sync while leader has unflushed batch confirmed as Finding 8, LRU capacity3 batch2 sequence A,resync3,A,B,B; follower decides A,A,B,A. No-resync control passes.

## Reconfiguration follow-up

- Finding 9 confirms double-counting an already accepted StopSign in same-leader resync. Both pending and already-decided StopSigns reproduce. Leader ends accepted2/decided3, is_reconfigured None, decided reads None. No extra append or proposed StopSign. These are two failing core-harness cases; see the current totals below.
- Optional harness now has 10 tests: 5 controls pass and 5 reproductions fail. Same core source capture; release reproduces the small-cache decoder panic separately.

## Same-ballot stale synchronization

- Finding 10: hold initial AcceptSync to node2, let timer retry produce newer sync, decide value10 everywhere, reconnect node2 and deliver new Prepare, then deliver held old AcceptSync. Node2 erases accepted/decided index1 to0 and ignores current session3 sync. Packet-filtering control passes. Core harness now 13 tests: 5 controls pass, 8 reproductions fail.
- Potential extension, not executed: cause this rollback on both followers, isolate old leader, and inspect whether a new quorum chooses a replacement at the old decided position. Existing local decided-data loss already suffices; only pursue if useful to distinguish scope.

## Coverage checked without finding a failure

- `audit-repro/src/bin/ble_topologies.rs`: all 998 undirected N=5 static graphs with a quorum-connected node progressed within 200 ticks, with periodic retry proposals. `audit-artifacts/ble-topologies-output.txt` records command result (exit 0). Static graph exploration only, not exhaustive schedules or crash recovery.
