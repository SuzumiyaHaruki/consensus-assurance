use std::time::Duration;

use omnipaxos::{
    storage::{Entry, Snapshot, Storage},
    util::LogEntry,
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_runtime::{spawn_actor, RuntimeConfig, TokioRuntime};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
struct TestEntry(u64);

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
struct TestSnapshot(Vec<TestEntry>);

impl Snapshot<TestEntry> for TestSnapshot {
    fn create(entries: &[TestEntry]) -> Self {
        Self(entries.to_vec())
    }

    fn merge(&mut self, delta: Self) {
        self.0.extend(delta.0);
    }

    fn use_snapshots() -> bool {
        true
    }
}

impl Entry for TestEntry {
    type Snapshot = TestSnapshot;
}

#[tokio::main]
async fn main() {
    let mut storage = MemoryStorage::<TestEntry>::default();
    let entries: Vec<_> = (1..=6).map(TestEntry).collect();
    storage.append_entries(entries).unwrap();
    storage.set_decided_idx(6).unwrap();

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
    let mut op = cfg.build(storage).unwrap();
    op.snapshot(Some(3), true).unwrap();
    assert_eq!((op.get_compacted_idx(), op.get_decided_idx()), (3, 6));

    let handle = spawn_actor::<TestEntry, MemoryStorage<TestEntry>, TokioRuntime>(
        op,
        RuntimeConfig {
            tick_period: Duration::from_millis(2),
            egress_period: Duration::from_millis(2),
            ..Default::default()
        },
    );
    let rx = handle.subscribe_decided(0).await;
    let mut received = Vec::new();
    while let Ok(item) = tokio::time::timeout(Duration::from_millis(100), rx.recv()).await {
        received.push(item.expect("stream closed"));
    }

    assert_eq!(
        received.len(),
        4,
        "expected one compacted placeholder plus the three-entry suffix, got {received:?}"
    );
    assert!(matches!(received[0], LogEntry::Snapshotted(_)));
    assert_eq!(
        &received[1..],
        &[
            LogEntry::Decided(TestEntry(4)),
            LogEntry::Decided(TestEntry(5)),
            LogEntry::Decided(TestEntry(6)),
        ]
    );
}
