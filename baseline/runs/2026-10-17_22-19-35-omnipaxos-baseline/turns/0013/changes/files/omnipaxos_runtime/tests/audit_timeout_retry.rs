#![cfg(feature = "tokio_runtime")]
#![cfg(not(feature = "unicache"))]

use std::{collections::HashMap, sync::Arc, time::Duration};

use omnipaxos::{
    messages::{
        async_runtime::AsyncRuntimeMsg,
        Message,
    },
    storage::{Entry, NoSnapshot},
    util::{LogEntry, NodeId},
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_runtime::{spawn_actor, AppendError, OmniPaxosHandle, RuntimeConfig, TokioRuntime};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
struct TestEntry(u64);

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

fn build_op(pid: NodeId, nodes: &[NodeId]) -> omnipaxos::OmniPaxos<TestEntry, MemoryStorage<TestEntry>> {
    OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id: 1,
            nodes: nodes.to_vec(),
            flexible_quorum: None,
        },
        server_config: ServerConfig {
            pid,
            election_tick_timeout: 3,
            resend_message_tick_timeout: 5,
            flush_batch_tick_timeout: 10,
            ..Default::default()
        },
    }
    .build(MemoryStorage::default())
    .unwrap()
}

async fn spawn_cluster() -> HashMap<NodeId, OmniPaxosHandle<TestEntry>> {
    let nodes: Vec<NodeId> = vec![1, 2, 3];
    let cfg = RuntimeConfig {
        tick_period: Duration::from_millis(2),
        egress_period: Duration::from_millis(1),
        append_notify_timeout: Duration::from_secs(2),
        ..Default::default()
    };
    let mut handles = HashMap::new();
    for &pid in &nodes {
        let h = spawn_actor::<TestEntry, MemoryStorage<TestEntry>, TokioRuntime>(
            build_op(pid, &nodes),
            cfg.clone(),
        );
        handles.insert(pid, h);
    }

    let shared = Arc::new(handles.clone());
    for &pid in &nodes {
        let outgoing = shared[&pid].outgoing_messages();
        let peers = shared.clone();
        tokio::spawn(async move {
            while let Ok(msg) = outgoing.recv().await {
                // The leader accepts the proposal, but the origin never learns
                // its assigned index and therefore reports Timeout.
                if matches!(
                    &msg,
                    Message::AsyncRuntime(omnipaxos::messages::AsyncRuntimeMessage {
                        msg: AsyncRuntimeMsg::Assigned { .. },
                        ..
                    })
                ) {
                    continue;
                }
                if let Some(peer) = peers.get(&msg.get_receiver()) {
                    peer.handle_incoming(msg).await;
                }
            }
        });
    }
    handles
}

async fn wait_for_leader(handles: &HashMap<NodeId, OmniPaxosHandle<TestEntry>>) -> NodeId {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
    loop {
        for h in handles.values() {
            if let Some((pid, true)) = h.current_leader().await {
                return pid;
            }
        }
        assert!(tokio::time::Instant::now() < deadline, "no stable leader");
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}

#[tokio::test]
async fn timeout_is_not_safe_to_retry_when_proposal_was_accepted() {
    let handles = spawn_cluster().await;
    let leader = wait_for_leader(&handles).await;
    let follower = *handles.keys().find(|&&pid| pid != leader).unwrap();
    let follower_h = handles[&follower].clone();

    let first = tokio::time::timeout(
        Duration::from_secs(2),
        follower_h.append_notify_with_timeout(TestEntry(7), Duration::from_millis(300)),
    )
    .await
    .expect("first append_notify hung");
    assert!(matches!(first, Err(AppendError::Timeout)));

    // Following the documented retry-safe behavior.
    let second = tokio::time::timeout(
        Duration::from_secs(2),
        follower_h.append_notify_with_timeout(TestEntry(7), Duration::from_millis(300)),
    )
    .await
    .expect("second append_notify hung");
    assert!(matches!(second, Err(AppendError::Timeout)));

    let leader_h = handles[&leader].clone();
    tokio::time::sleep(Duration::from_millis(100)).await;
    let entries = leader_h
        .read_decided_suffix(0)
        .await
        .expect("leader has no decided entries");
    let duplicates = entries
        .iter()
        .filter(|entry| matches!(entry, LogEntry::Decided(TestEntry(7))))
        .count();
    assert!(
        duplicates <= 1,
        "Timeout is documented as retry-safe, but the timed-out proposal was \
         already decided and retrying appended it {duplicates} times"
    );
}
