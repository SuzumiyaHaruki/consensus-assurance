//! Audit probe #5 (added by the auditor, NOT part of the captured source).
//!
//! `PersistentStorage` (RocksDB) is what the crash-recovery tests and any durable deployment
//! rely on, but the captured suite only exercises it *through* the core's flows. This probe
//! checks the position handling the core's sync path depends on, directly:
//!
//! 1. append / read / suffix round-trip;
//! 2. `append_on_prefix` overwriting part of the log (the `AcceptSync` path);
//! 3. `trim` + `set_compacted_idx` followed by reads above the compacted index;
//! 4. `append_on_prefix` *after* compaction (the sync-after-snapshot path);
//! 5. everything above surviving a reopen of the same directory (the recovery path).
//!
//! Only invariants the core actually relies on are asserted; out-of-range input behaviour is
//! reported, not asserted, because the `Storage` contract does not define it.

// Prepared, but NOT executed in this audit: building this crate's own feature graph pulls in
// `persistent_storage`, which makes cargo rebuild RocksDB from source (~8-10 min on this host),
// so it was left out of the report's evidence and listed under unresolved work. The gate keeps
// it inert for every other feature combination (e.g. `cargo test --workspace`).
#![cfg(feature = "persistent_storage")]

use std::path::PathBuf;

use omnipaxos::storage::{Entry, Snapshot};
use omnipaxos_storage::persistent_storage::{PersistentStorage, PersistentStorageConfig};

#[derive(Clone, Debug, Default, PartialEq, serde::Serialize, serde::Deserialize)]
struct TestEntry(u64);

#[derive(Clone, Debug, Default, PartialEq, serde::Serialize, serde::Deserialize)]
struct NoSnapshot;

impl Snapshot<TestEntry> for NoSnapshot {
    fn create(_entries: &[TestEntry]) -> Self {
        NoSnapshot
    }
    fn merge(&mut self, _delta: Self) {}
    fn use_snapshots() -> bool {
        false
    }
}

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

type Store = PersistentStorage<TestEntry>;

fn open(dir: &PathBuf) -> Store {
    Store::open(PersistentStorageConfig::with_path(
        dir.to_string_lossy().to_string(),
    ))
}

fn values(v: Vec<TestEntry>) -> Vec<u64> {
    v.into_iter().map(|e| e.0).collect()
}

#[test]
fn persistent_storage_positions_round_trip_across_prefix_and_compaction() {
    let dir = std::env::temp_dir().join(format!("audit-pstore-{}", std::process::id()));
    let mut store = open(&dir);

    // 1. plain append / read / suffix
    store
        .append_entries(vec![TestEntry(1), TestEntry(2), TestEntry(3)])
        .expect("append");
    assert_eq!(store.get_log_len().unwrap(), 3);
    assert_eq!(values(store.get_entries(0, 3).unwrap()), vec![1, 2, 3]);
    assert_eq!(values(store.get_suffix(1).unwrap()), vec![2, 3]);

    // 2. overwrite the tail from index 1 (what AcceptSync does)
    store
        .append_on_prefix(1, vec![TestEntry(20), TestEntry(30)])
        .expect("append_on_prefix");
    assert_eq!(store.get_log_len().unwrap(), 3);
    assert_eq!(values(store.get_entries(0, 3).unwrap()), vec![1, 20, 30]);
    assert_eq!(values(store.get_suffix(1).unwrap()), vec![20, 30]);

    // 3. trim to 2 and read above the compacted index
    store.trim(2).expect("trim");
    store.set_compacted_idx(2).expect("set_compacted_idx");
    assert_eq!(store.get_compacted_idx().unwrap(), 2);
    assert_eq!(store.get_log_len().unwrap(), 1);
    assert_eq!(values(store.get_entries(2, 3).unwrap()), vec![30]);
    assert_eq!(values(store.get_suffix(2).unwrap()), vec![30]);

    // 4. replace the tail again, now on top of a compacted prefix
    store
        .append_on_prefix(2, vec![TestEntry(40)])
        .expect("append_on_prefix after trim");
    assert_eq!(store.get_log_len().unwrap(), 1);
    assert_eq!(values(store.get_entries(2, 3).unwrap()), vec![40]);
    assert_eq!(values(store.get_suffix(0).unwrap()), vec![40]);

    // 5. state survives a reopen (recovery path)
    store.set_decided_idx(3).expect("decided");
    store.set_promise(Default::default()).expect("promise");
    drop(store);
    let reopened = open(&dir);
    assert_eq!(reopened.get_compacted_idx().unwrap(), 2);
    assert_eq!(reopened.get_decided_idx().unwrap(), 3);
    assert_eq!(reopened.get_log_len().unwrap(), 1);
    assert_eq!(values(reopened.get_entries(2, 3).unwrap()), vec![40]);
    assert_eq!(values(reopened.get_suffix(2).unwrap()), vec![40]);

    // 6. reported, not asserted: an out-of-range `append_on_prefix` (from_idx below the
    // compacted index) writes below the prefix, after which `get_log_len`'s
    // `next_log_key - compacted_idx` is a usize underflow (panic in debug builds).
    let mut s2 = open(&dir_with_suffix(&dir, "-oob"));
    s2.append_entries(vec![TestEntry(1)]).expect("append");
    s2.append_on_prefix(1, vec![]).expect("append_on_prefix");
    s2.trim(2).expect("trim");
    s2.set_compacted_idx(2).expect("set_compacted_idx");
    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| s2.get_log_len()));
    eprintln!(
        "[audit-pstore] get_log_len() with next_log_key=1 < compacted=2 -> {:?} (catch_unwind: \
         {} )",
        outcome,
        if outcome.is_ok() { "returned" } else { "panicked" }
    );
}

fn dir_with_suffix(dir: &PathBuf, suffix: &str) -> PathBuf {
    PathBuf::from(format!("{}{suffix}", dir.to_string_lossy()))
}
