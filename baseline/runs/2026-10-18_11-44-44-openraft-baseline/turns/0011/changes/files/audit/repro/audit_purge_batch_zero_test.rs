//! Audit-only reproduction: `calc_purge_upto()` subtracts one from
//! `purge_end` without handling `purge_end == 0`.  A zero purge batch is
//! accepted by `Config::validate()`, and a snapshot at index 0 with
//! `max_in_snapshot_log_to_keep > 0` makes `purge_end` zero.

use std::panic::AssertUnwindSafe;

use crate::engine::testing::UTConfig;
use crate::engine::Engine;
use crate::engine::LogIdList;
use crate::CommittedLeaderId;
use crate::Config;
use crate::LogId;

fn log_id(term: u64, index: u64) -> LogId<u64> {
    LogId::<u64> {
        leader_id: CommittedLeaderId::new(term, 0),
        index,
    }
}

#[test]
fn audit_calc_purge_upto_zero_batch() {
    let mut eng = Engine::<UTConfig>::default();
    eng.state.enable_validation(false);
    eng.state.log_ids = LogIdList::new(vec![log_id(0, 0), log_id(1, 1)]);

    // A snapshot covers index 0; keeping two logs means purge_end == 0.
    eng.state.snapshot_meta.last_log_id = Some(log_id(0, 0));
    eng.config.max_in_snapshot_log_to_keep = 2;
    eng.config.purge_batch_size = 0;

    let res = std::panic::catch_unwind(AssertUnwindSafe(|| eng.log_handler().calc_purge_upto()));
    assert!(
        res.is_err(),
        "expected the unguarded purge_end - 1 to underflow, got {:?}",
        res.ok()
    );
}

#[test]
fn audit_config_accepts_zero_limits() -> anyhow::Result<()> {
    let config = Config::build(&[
        "foo",
        "--purge-batch-size=0",
        "--snapshot-max-chunk-size=0",
        "--heartbeat-interval=0",
        "--install-snapshot-timeout=0",
    ])?;
    assert_eq!(0, config.purge_batch_size);
    assert_eq!(0, config.snapshot_max_chunk_size);
    assert_eq!(0, config.heartbeat_interval);
    assert_eq!(0, config.install_snapshot_timeout);
    Ok(())
}
