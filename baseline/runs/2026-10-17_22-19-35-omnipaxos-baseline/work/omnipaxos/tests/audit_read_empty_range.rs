#![cfg(not(feature = "unicache"))]

pub mod utils;

use omnipaxos::{
    storage::Storage,
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;
use utils::Value;

#[test]
fn empty_range_read_is_not_replaced_by_snapshot_after_compaction() {
    let mut storage = MemoryStorage::<Value>::default();
    storage
        .append_entries((1..=4).map(Value::with_id).collect())
        .unwrap();
    storage.set_decided_idx(4).unwrap();
    let mut op = OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id: 1,
            nodes: vec![1, 2, 3],
            flexible_quorum: None,
        },
        server_config: ServerConfig {
            pid: 1,
            ..Default::default()
        },
    }
    .build(storage)
    .unwrap();

    assert!(op.read_entries(1..1).unwrap().is_empty());
    op.snapshot(Some(2), true).unwrap();
    assert!(
        op.read_entries(1..1).unwrap().is_empty(),
        "an empty range returned a snapshot from another index"
    );
}
