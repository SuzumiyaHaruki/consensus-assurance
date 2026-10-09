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
- Follower-to-leader LRU overflow is now Finding 6: full valid u8 cache, leader change, one distinct append panics in checked build. Unchanged-leader control passes. Investigate unchecked/release behavior and encoder/decoder disagreement next; do not extrapolate the checked panic to production release.
- LFU cloning reconstructs entries without carrying frequency counters or stable tie ordering. Investigate eviction consistency after AcceptSync. Not yet executed or a finding.
