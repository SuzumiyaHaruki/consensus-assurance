#![cfg(feature = "logging")]
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
fn empty_logger_path_does_not_panic_during_build() {
    let mut cfg = OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id: 1,
            nodes: vec![1, 2, 3],
            flexible_quorum: None,
        },
        server_config: ServerConfig {
            pid: 1,
            ..Default::default()
        },
    };
    cfg.server_config.logger_file_path = Some(String::new());
    assert!(
        cfg.validate().is_ok(),
        "test precondition: empty path currently passes validation"
    );

    let result =
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            cfg.build(MemoryStorage::<TestEntry>::default())
        }));
    assert!(result.is_ok(), "build panicked on an empty logger path");
}
