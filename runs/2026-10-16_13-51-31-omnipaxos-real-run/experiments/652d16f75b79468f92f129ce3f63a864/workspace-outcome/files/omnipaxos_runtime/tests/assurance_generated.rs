//! Sourced probe of the runtime's completion endpoint: does `append_notify` resolve
//! `Ok(idx)` for an entry that was never decided at `idx`?
//!
//! Scenario: node A is the leader and accepts its own entry at index 1 (assigned to
//! its pending call). A's outgoing traffic is then cut, so that entry never reaches
//! anyone; nodes B and C elect B, whose log is empty, and B decides index 1 with its
//! own entry. A is then allowed back in: it promises B, B syncs it (truncating A's
//! log to B's) and A's decided index becomes 1, while A's entry is gone. The pending
//! call's index is now "decided" although the entry at that index is a different one.

use std::{
    collections::VecDeque,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};

use omnipaxos::{
    storage::{Entry, Snapshot},
    util::{LogEntry, NodeId},
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;
use omnipaxos_runtime::{
    spawn_actor, AppendError, AsyncRuntime, OmniPaxosHandle, RuntimeConfig,
};

#[derive(Clone, Debug, Default, PartialEq, serde::Serialize, serde::Deserialize)]
struct TestEntry(u64);

#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize)]
struct NoSnapshot;

impl Snapshot<TestEntry> for NoSnapshot {
    fn create(_entries: &[TestEntry]) -> Self {
        NoSnapshot
    }
    fn merge(&mut self, _delta: Self) {}
    fn use_snapshots() -> bool {
        false
    }
}

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

struct TestRuntime;

impl AsyncRuntime for TestRuntime {
    type JoinHandle = ();
    fn spawn<F>(future: F)
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        let _ = tokio::spawn(future);
    }
    fn sleep(duration: Duration) -> impl std::future::Future<Output = ()> + Send + 'static {
        tokio::time::sleep(duration)
    }
}

fn build_op(pid: NodeId, nodes: Vec<NodeId>) -> omnipaxos::OmniPaxos<TestEntry, MemoryStorage<TestEntry>> {
    #[allow(clippy::needless_update)]
    let server_config = ServerConfig {
        pid,
        election_tick_timeout: 3,
        resend_message_tick_timeout: 5,
        buffer_size: 100,
        batch_size: 1,
        flush_batch_tick_timeout: 100,
        leader_priority: if pid == 1 { 10 } else { 0 },
        ..Default::default()
    };
    OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id: 1,
            nodes,
            flexible_quorum: None,
        },
        server_config,
    }
    .build(MemoryStorage::default())
    .expect("config build")
}

/// Messages pulled off the actors' outgoing channels by a pump task; the test decides
/// what is delivered and what is dropped (messages from `blocked` are discarded).
struct Wire {
    queue: Mutex<VecDeque<omnipaxos::messages::Message<TestEntry>>>,
    blocked: AtomicU64,
    blocked_in: AtomicU64,
}

impl Wire {
    fn new() -> Arc<Self> {
        Arc::new(Wire {
            queue: Mutex::new(VecDeque::new()),
            blocked: AtomicU64::new(0),
            blocked_in: AtomicU64::new(0),
        })
    }
    fn push(&self, m: omnipaxos::messages::Message<TestEntry>) {
        self.queue.lock().unwrap().push_back(m);
    }
}

fn emit(line: &str) {
    println!("CA_EVENT {line}");
}

async fn deliver_all(
    wire: &Arc<Wire>,
    handles: &std::collections::HashMap<NodeId, OmniPaxosHandle<TestEntry>>,
) -> usize {
    let mut delivered = 0;
    loop {
        let msg = wire.queue.lock().unwrap().pop_front();
        let Some(msg) = msg else { break };
        if msg.get_sender() == wire.blocked.load(Ordering::SeqCst)
            || msg.get_receiver() == wire.blocked_in.load(Ordering::SeqCst)
        {
            continue;
        }
        let to = msg.get_receiver();
        if let Some(h) = handles.get(&to) {
            h.handle_incoming(msg).await;
            delivered += 1;
        }
    }
    delivered
}

/// Delivery runs in its own task so that messages keep flowing while the test awaits
/// a handle call (a handle call cannot pump the transport itself).
async fn settle(rounds: usize) {
    tokio::time::sleep(Duration::from_millis(5 * rounds as u64)).await;
}

#[tokio::test]
async fn append_notify_ok_for_entry_overwritten_at_that_index() {
    let nodes: Vec<NodeId> = vec![1, 2, 3];
    let cfg = RuntimeConfig {
        tick_period: Duration::from_millis(2000),
        egress_period: Duration::from_millis(1),
        append_notify_timeout: Duration::from_secs(5),
        ..Default::default()
    };
    let wire = Wire::new();
    let mut handles = std::collections::HashMap::new();
    for pid in nodes.clone() {
        let op = build_op(pid, nodes.clone());
        let h = spawn_actor::<TestEntry, MemoryStorage<TestEntry>, TestRuntime>(op, cfg.clone());
        let out = h.outgoing_messages();
        let w = wire.clone();
        tokio::spawn(async move {
            while let Ok(m) = out.recv().await {
                w.push(m);
            }
        });
        handles.insert(pid, h);
    }
    {
        let w = wire.clone();
        let hs = handles.clone();
        tokio::spawn(async move {
            loop {
                let _ = deliver_all(&w, &hs).await;
                tokio::time::sleep(Duration::from_millis(1)).await;
            }
        });
    }

    // Node 1 (priority 10) becomes leader once the heartbeats have been exchanged.
    tokio::time::sleep(Duration::from_millis(50)).await;
    handles[&1].try_become_leader().await;
    settle(40).await;
    let leader = handles[&1].current_leader().await;
    assert_eq!(
        leader,
        Some((1, true)),
        "setup: node 1 is not the stable leader"
    );

    // A is cut off in both directions first: its own entry is accepted locally at
    // index 1 and never leaves A, and A also learns nothing while B takes over.
    wire.blocked.store(1, Ordering::SeqCst);
    wire.blocked_in.store(1, Ordering::SeqCst);
    let pending = {
        let h = handles[&1].clone();
        tokio::spawn(async move { h.append_notify(TestEntry(42)).await })
    };
    tokio::time::sleep(Duration::from_millis(200)).await;
    let a_hold = {
        let entries = handles[&1].read_decided_suffix(0).await;
        format!("{entries:?}")
    };
    let a_holds_own_entry = a_hold.contains("Undecided");

    // B takes over with an empty log and decides its own entry at index 1.
    handles[&2].try_become_leader().await;
    settle(60).await;
    emit(&format!(
        "{{\"event\":\"after_b_takeover\",\"b_leader\":{:?},\"c_leader\":{:?},\"a_leader\":{:?},\"b_decided\":{},\"c_decided\":{}}}",
        handles[&2].current_leader().await,
        handles[&3].current_leader().await,
        handles[&1].current_leader().await,
        handles[&2].decided_idx().await,
        handles[&3].decided_idx().await
    ));
    let b_idx = handles[&2]
        .append_notify(TestEntry(99))
        .await
        .expect("B's append_notify should succeed while C is available");
    settle(40).await;
    let b_decided = handles[&2].decided_idx().await;
    assert!(b_decided >= 1, "setup: B did not decide its own entry");

    // Let A back in: it re-syncs with B, which truncates A's log to B's.
    wire.blocked.store(0, Ordering::SeqCst);
    wire.blocked_in.store(0, Ordering::SeqCst);
    handles[&1].reconnected(2).await;
    settle(120).await;
    let a_decided = handles[&1].decided_idx().await;

    // A's entry at index 1 is gone; what resolves the pending call?
    let a_log = handles[&1].read_decided_suffix(0).await.unwrap_or_default();
    let a_entry_at_1 = a_log.first().cloned();
    let resolved = tokio::time::timeout(Duration::from_secs(8), pending)
        .await
        .expect("append_notify never resolved after A re-synced");
    emit(&format!(
        "{{\"event\":\"overwritten_index_resolution\",\"a_decided_idx\":{a_decided},\"a_entry_at_index_1_is_own\":{},\"b_decided_idx\":{b_decided},\"b_idx\":{b_idx},\"resolution\":\"{}\"}}",
        matches!(a_entry_at_1, Some(LogEntry::Decided(TestEntry(42)))),
        match &resolved {
            Ok(Ok(idx)) => format!("Ok({idx})"),
            Ok(Err(AppendError::Superseded { log_entry_idx })) => format!("Superseded({log_entry_idx})"),
            Ok(Err(AppendError::Timeout)) => "Timeout".to_string(),
            Ok(Err(AppendError::Shutdown)) => "Shutdown".to_string(),
            Ok(Err(AppendError::TooManyOutstanding)) => "TooManyOutstanding".to_string(),
            Ok(Err(AppendError::Propose(_))) => "Propose".to_string(),
            Err(_) => "join-error".to_string(),
        }
    ));
    let _ = a_holds_own_entry;
    // The decisive comparison: if the call reported Ok(idx), the entry at that index
    // on A must be the one that call submitted. Node 1's own entry is not there.
    if let Ok(Ok(idx)) = resolved {
        let at_idx = a_log.get(idx.saturating_sub(1)).cloned();
        assert!(
            !matches!(at_idx, Some(LogEntry::Decided(TestEntry(42)))),
            "index {idx} unexpectedly still holds node 1's own entry"
        );
    }
}
