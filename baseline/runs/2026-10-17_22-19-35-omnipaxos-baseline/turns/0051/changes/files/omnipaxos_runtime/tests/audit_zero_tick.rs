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

fn op() -> omnipaxos::OmniPaxos<TestEntry, MemoryStorage<TestEntry>> {
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

async fn responds_with_periods(tick_period: Duration, egress_period: Duration) -> bool {
    let handle = spawn_actor::<TestEntry, MemoryStorage<TestEntry>, TokioRuntime>(
        op(),
        RuntimeConfig {
            tick_period,
            egress_period,
            ..Default::default()
        },
    );
    tokio::time::timeout(Duration::from_millis(100), handle.decided_idx())
        .await
        .is_ok()
}

#[tokio::test]
async fn zero_tick_period_does_not_starve_the_command_channel() {
    assert!(
        responds_with_periods(Duration::from_millis(2), Duration::from_millis(1)).await
    );
    assert!(
        responds_with_periods(Duration::ZERO, Duration::from_millis(1)).await,
        "tick_period = 0 starved the actor command channel"
    );
    assert!(
        responds_with_periods(Duration::from_millis(2), Duration::ZERO).await,
        "egress_period = 0 starved the actor command channel"
    );
}
