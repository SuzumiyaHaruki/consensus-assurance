# Working notes (not a submission)

## Layout
- Captured snapshot (read-only): ../agent-source  (this is /home/nitro/Desktop/omnipaxos @ 827f304846ab0c5aa40910b6f6cdce1d4ddf8e12)
- Local offline workspace copy for construction feedback: draft/tmp/ws (features: async_runtime,serde,logging,macros)
  - Run: `cd draft/tmp/ws && CARGO_TARGET_DIR=$PWD/../target cargo test --offline --locked -p omnipaxos --features async_runtime,serde,logging,macros --test <file> -- --nocapture --test-threads=1`
  - First build of dev-deps (incl. rocksdb, kompact) took ~11 min; later test edits are seconds.
- Reference for diffing: published omnipaxos-0.2.2 extracted at draft/tmp/ref (older lineage: pre-LogSync, u64 indices, batch_accept feature). Useful for spotting suspicious local edits, noisy for version drift.
- Formal harness target: omnipaxos/tests/assurance_generated.rs (package ./omnipaxos, features async_runtime+serde+logging+macros).

## Observations so far (local, not retained receipts)
- probe1.rs: 3 in-process nodes, batch_size=1: leader elected, 10 entries decided identically on all nodes; StopSign reconfiguration decided on all three (is_reconfigured() == Some); crashed follower recovered from persisted storage and caught up to the same decided log; leader crash + re-election + recovery of the old leader kept agreement.
- Batching probe (batch_size=3, appends from leader and follower) had a wrong expectation in my probe (18 entries, 9 unique) - fix the expectation before drawing conclusions.

## Candidate defect areas still open
1. Follower batched append -> reply_accepted / decided_idx cap (follower.rs 88-158, internal_storage.rs 257-360).
2. Leader decision by length semantics (leader.rs 316-345, util.rs 252-259).
3. Recovery/resync adoption (follower.rs handle_prepare 13-51, leader.rs send_accsync 150-191, mod.rs create_log_sync 390-418).
4. Actor-layer FIFO claim for unconfirmed_local / track_batch_growth (actor.rs 438-586) - not executable from the omnipaxos package; source-only unless a core-visible consequence is found.
5. Stale doc reference in actor.rs:77 (`track_untracked_batch_growth` does not exist; function is `track_batch_growth`) - weak hint that this function was edited.
