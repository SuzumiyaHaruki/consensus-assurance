#![cfg(not(feature = "unicache"))]

use omnipaxos::{
    storage::{Entry, NoSnapshot},
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug)]
struct TestEntry;

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

#[test]
fn read_at_max_usize_returns_none_instead_of_panicking() {
    let op = OmniPaxosConfig {
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
    .build(MemoryStorage::<TestEntry>::default())
    .unwrap();

    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| op.read(usize::MAX)));
    assert!(result.is_ok(), "out-of-bounds read panicked");
    assert!(result.unwrap().is_none());
}
