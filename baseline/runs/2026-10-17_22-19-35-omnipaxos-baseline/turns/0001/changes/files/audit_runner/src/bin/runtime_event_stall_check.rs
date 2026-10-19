use std::{collections::HashMap, sync::Arc, time::Duration};

use omnipaxos::{
    storage::{Entry, NoSnapshot},
    util::NodeId,
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_runtime::{spawn_actor, OmniPaxosHandle, RuntimeConfig, TokioRuntime};
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
            election_tick_timeout: 2,
            resend_message_tick_timeout: 4,
            ..Default::default()
        },
    }
    .build(MemoryStorage::default())
    .unwrap()
}

async fn spawn_cluster(
    event_capacity: usize,
) -> (
    HashMap<NodeId, OmniPaxosHandle<TestEntry>>,
    Vec<tokio::task::JoinHandle<()>>,
) {
    let nodes: Vec<NodeId> = vec![1, 2, 3];
    let cfg = RuntimeConfig {
        tick_period: Duration::from_millis(2),
        egress_period: Duration::from_millis(1),
        event_capacity,
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
    let mut tasks = Vec::new();
    for &pid in &nodes {
        let outgoing = shared[&pid].outgoing_messages();
        let peers = shared.clone();
        tasks.push(tokio::spawn(async move {
            while let Ok(msg) = outgoing.recv().await {
                if let Some(peer) = peers.get(&msg.get_receiver()) {
                    peer.handle_incoming(msg).await;
                }
            }
        }));
    }
    (handles, tasks)
}

async fn reaches_stable_leader(event_capacity: usize) -> Result<(), &'static str> {
    let (handles, tasks) = spawn_cluster(event_capacity).await;
    let stable_leader = tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            for h in handles.values() {
                if let Some((pid, true)) = h.current_leader().await {
                    return pid;
                }
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await;
    if stable_leader.is_err() {
        for task in tasks {
            task.abort();
        }
        return Err("cluster did not reach an accepted leader within two seconds");
    }

    // Confirm command-plane responsiveness once stable leadership has been observed.
    let probe = handles.values().next().unwrap();
    let responsive =
        tokio::time::timeout(Duration::from_millis(500), probe.decided_idx()).await;
    for task in tasks {
        task.abort();
    }
    responsive
        .map(|_| ())
        .map_err(|_| "actor loop stopped processing commands")
}

#[tokio::main]
async fn main() {
    reaches_stable_leader(1024)
        .await
        .expect("default-capacity control failed, so the result is not attributable to event pressure");
    let stalled = reaches_stable_leader(1).await;
    assert!(
        stalled.is_ok(),
        "a node stalled before the cluster reached an accepted leader solely because \
         nobody was draining the size-1 bounded event stream: {stalled:?}"
    );
}
