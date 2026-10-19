#![cfg(feature = "tokio_runtime")]
#![cfg(not(feature = "unicache"))]

use std::{panic::catch_unwind, panic::AssertUnwindSafe, time::Duration};

use omnipaxos::{
    storage::{Entry, NoSnapshot},
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_runtime::{spawn_actor, RuntimeConfig, TokioRuntime};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
struct TestEntry;

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

fn build_op() -> omnipaxos::OmniPaxos<TestEntry, MemoryStorage<TestEntry>> {
    OmniPaxosConfig {
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
    .build(MemoryStorage::default())
    .unwrap()
}

async fn produces_outgoing(capacity: usize) -> bool {
    let op = build_op();
    let cfg = RuntimeConfig {
        outgoing_capacity: capacity,
        tick_period: Duration::from_millis(2),
        egress_period: Duration::from_millis(1),
        ..Default::default()
    };
    let Ok(handle) = catch_unwind(AssertUnwindSafe(|| {
        spawn_actor::<TestEntry, MemoryStorage<TestEntry>, TokioRuntime>(op, cfg)
    })) else {
        return false;
    };
    let receiver = handle.outgoing_messages();
    tokio::time::timeout(Duration::from_millis(100), receiver.recv())
        .await
        .is_ok()
}

#[tokio::test]
async fn zero_outgoing_capacity_does_not_panic() {
    assert!(produces_outgoing(8).await, "nonzero-capacity control produced no egress");
    assert!(
        produces_outgoing(0).await,
        "RuntimeConfig accepted outgoing_capacity = 0, but spawn_actor panicked"
    );
}
