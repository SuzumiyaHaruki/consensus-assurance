#![cfg(feature = "tokio_runtime")]
#![cfg(not(feature = "unicache"))]

use std::time::Duration;

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

#[tokio::test]
async fn dropping_a_decided_subscriber_frees_its_capacity_while_idle() {
    let cfg = OmniPaxosConfig {
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
    let op = cfg.build(MemoryStorage::<TestEntry>::default()).unwrap();
    let handle = spawn_actor::<TestEntry, MemoryStorage<TestEntry>, TokioRuntime>(
        op,
        RuntimeConfig {
            max_decided_subscribers: 1,
            tick_period: Duration::from_millis(2),
            ..Default::default()
        },
    );

    let first = handle.subscribe_decided(0).await;
    drop(first);
    tokio::time::sleep(Duration::from_millis(50)).await;

    let second = handle.subscribe_decided(0).await;
    match tokio::time::timeout(Duration::from_millis(100), second.recv()).await {
        Err(_) => {}
        Ok(Err(_)) => panic!(
            "dropping a subscriber did not free its slot while the decided index stayed unchanged"
        ),
        Ok(Ok(entry)) => panic!("unexpected decided entry on an idle log: {entry:?}"),
    }
}
