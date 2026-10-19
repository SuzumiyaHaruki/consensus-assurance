#![cfg(not(feature = "unicache"))]

use omnipaxos::{
    storage::{Entry, NoSnapshot},
    ClusterConfig, OmniPaxosConfig, ProposeErr, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug)]
struct TestEntry;

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

fn cluster_config(id: u32) -> ClusterConfig {
    ClusterConfig {
        configuration_id: id,
        nodes: vec![1, 2, 3],
        flexible_quorum: None,
    }
}

#[test]
fn second_reconfigure_is_rejected_while_first_request_is_buffered() {
    let mut op = OmniPaxosConfig {
        cluster_config: cluster_config(1),
        server_config: ServerConfig {
            pid: 3,
            ..Default::default()
        },
    }
    .build(MemoryStorage::<TestEntry>::default())
    .unwrap();

    // No leader is known, so the first request is buffered.
    op.reconfigure(cluster_config(2), None)
        .expect("first valid reconfiguration should be accepted");

    let second = op.reconfigure(cluster_config(3), None);
    assert!(
        matches!(second, Err(ProposeErr::PendingReconfigConfig(..))),
        "a second reconfiguration was accepted while the first was still pending: {second:?}"
    );
}
