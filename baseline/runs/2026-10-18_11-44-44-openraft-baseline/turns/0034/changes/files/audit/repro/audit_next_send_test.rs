//! Audit-only randomized simulation for replication liveness.
//!
//! `ProgressEntry::next_send()` must make progress until the follower reaches
//! the leader's last log id.  This model feeds back successful and conflicting
//! responses and checks that `Inflight::None` is returned only when the
//! follower is caught up.

use crate::progress::entry::ProgressEntry;
use crate::progress::Inflight;
use crate::raft_state::LogStateReader;
use crate::CommittedLeaderId;
use crate::LogId;

struct Lcg(u64);

impl Lcg {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        self.0 >> 33
    }

    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
}

fn log_id(index: u64) -> LogId<u64> {
    LogId {
        leader_id: CommittedLeaderId::new(1, 1),
        index,
    }
}

struct LogState {
    last: LogId<u64>,
    snapshot: LogId<u64>,
    purge_upto: LogId<u64>,
    purged: Option<LogId<u64>>,
}

impl LogState {
    fn new(last_index: u64, purge_upto: u64, snapshot: u64) -> Self {
        Self {
            last: log_id(last_index),
            snapshot: log_id(snapshot),
            purge_upto: log_id(purge_upto),
            purged: if purge_upto == 0 { None } else { Some(log_id(purge_upto - 1)) },
        }
    }
}

impl LogStateReader<u64> for LogState {
    fn get_log_id(&self, index: u64) -> Option<LogId<u64>> {
        if let Some(p) = self.purged {
            if index <= p.index {
                return None;
            }
        }
        if index <= self.last.index {
            Some(log_id(index))
        } else {
            None
        }
    }

    fn last_log_id(&self) -> Option<&LogId<u64>> {
        Some(&self.last)
    }

    fn committed(&self) -> Option<&LogId<u64>> {
        Some(&self.last)
    }

    fn io_applied(&self) -> Option<&LogId<u64>> {
        Some(&self.last)
    }

    fn io_snapshot_last_log_id(&self) -> Option<&LogId<u64>> {
        Some(&self.snapshot)
    }

    fn io_purged(&self) -> Option<&LogId<u64>> {
        self.purged.as_ref()
    }

    fn snapshot_last_log_id(&self) -> Option<&LogId<u64>> {
        Some(&self.snapshot)
    }

    fn purge_upto(&self) -> Option<&LogId<u64>> {
        Some(&self.purge_upto)
    }

    fn last_purged_log_id(&self) -> Option<&LogId<u64>> {
        self.purged.as_ref()
    }
}

#[test]
fn audit_next_send_makes_progress() {
    for seed in 0..300 {
        let mut rng = Lcg(seed);
        let last_index = rng.below(30);
        let purge_upto = if last_index == 0 { 0 } else { rng.below(last_index + 1) };
        let snapshot = purge_upto + rng.below(last_index - purge_upto + 1);
        let max_entries = 1 + rng.below(8);
        let state = LogState::new(last_index, purge_upto, snapshot);

        let mut pe = ProgressEntry::empty(last_index + 1);
        let mut caught_up = false;

        for step in 0..300 {
            let action = match pe.next_send(&state, max_entries) {
                Ok(x) => Ok(x.clone()),
                Err(x) => Err(x.clone()),
            };

            match action {
                Ok(Inflight::Logs { id, log_id_range }) => {
                    assert!(log_id_range.prev < log_id_range.last, "empty logs inflight");

                    // A conflict is possible only when the probed prev is ahead
                    // of the already-known matching point; otherwise it would
                    // be a follower-log reversion, which is not a supported
                    // response here.
                    let can_conflict = log_id_range.prev > pe.matching;
                    if can_conflict && rng.below(2) == 0 {
                        let prev = log_id_range.prev.clone().unwrap();
                        pe.update_conflicting(Some(id), prev.index).unwrap();
                    } else {
                        pe.update_matching(id, log_id_range.last.clone()).unwrap();
                    }
                }
                Ok(Inflight::Snapshot { id, last_log_id }) => {
                    let snap = last_log_id.expect("the model always has a snapshot");
                    pe.update_matching(id, Some(snap)).unwrap();
                }
                Ok(Inflight::None) | Err(Inflight::None) => {
                    if pe.matching == state.last_log_id().cloned() {
                        caught_up = true;
                        break;
                    }
                    panic!(
                        "seed {seed} step {step}: next_send made no progress while follower is behind; \
                         matching: {:?}, searching_end: {}, last: {:?}, purge_upto: {:?}, snapshot: {:?}",
                        pe.matching,
                        pe.searching_end,
                        state.last_log_id(),
                        state.purge_upto(),
                        state.snapshot_last_log_id()
                    );
                }
                Err(other) => panic!("seed {seed} step {step}: unexpected existing inflight: {other:?}"),
            }
        }

        assert!(
            caught_up || pe.matching == state.last_log_id().cloned(),
            "seed {seed}: follower did not converge, matching: {:?}, last: {:?}",
            pe.matching,
            state.last_log_id()
        );
    }
}

/// `Config::validate()` only rejects `max_payload_entries == 0`, so
/// `u64::MAX` reaches `ProgressEntry::next_send()` unchanged. The range end
/// is computed as `start + max_entries` without a checked/saturating add.
#[test]
fn audit_next_send_max_entries_overflow() {
    let config = crate::Config {
        max_payload_entries: u64::MAX,
        ..Default::default()
    };
    assert!(
        config.validate().is_ok(),
        "Config::validate must be shown to accept u64::MAX"
    );

    let state = LogState::new(10, 0, 0);
    let mut pe = ProgressEntry::empty(11);

    if cfg!(debug_assertions) {
        // Debug builds detect the overflow and panic the replication task.
        let res = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _ = pe.next_send(&state, u64::MAX);
        }));
        let payload = res.expect_err("debug builds must detect the overflowing range end");
        let msg = payload
            .downcast_ref::<String>()
            .cloned()
            .or_else(|| payload.downcast_ref::<&str>().map(|s| s.to_string()))
            .unwrap_or_default();
        assert!(msg.contains("overflow"), "unexpected panic message: {msg}");
    } else {
        // Release builds wrap; `end < start`, `Inflight::logs()` degrades to
        // `None`, and the leader reports no work although the follower is
        // still 10 entries behind.
        let res = pe.next_send(&state, u64::MAX);
        assert!(
            matches!(res, Ok(Inflight::None)),
            "release build must be shown to stop replicating, got {res:?}"
        );
    }
}
