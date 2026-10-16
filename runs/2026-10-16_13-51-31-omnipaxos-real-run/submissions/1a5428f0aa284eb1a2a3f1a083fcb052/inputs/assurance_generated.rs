//! Sourced probe: does an event stream that the application does not consume park
//! the single omnipaxos_runtime actor task, and with it the node's whole consensus
//! participation (ticks, incoming messages, Command replies)?
//!
//! The actor publishes every observed transition with `event_tx.send(..).await`
//! (actor.rs `detect_and_emit_events`), awaited inside the tick arm of the only
//! `run` select loop, on the channel `spawn_actor` builds as
//! `async_channel::bounded(RuntimeConfig::event_capacity)`. The receiver always
//! exists: the handle owns one even if the application never calls
//! `subscribe_events()`. The other two egress paths of the same actor use
//! `try_send` instead.
//!
//! Case 1 leaves that receiver unread while the cluster is kept busy, so the bound
//! `event_capacity` is reached. Case 2 is the paired control: same cluster, same
//! capacity, same activity, only difference is a task that drains the events.

use std::{
    collections::HashMap,
    future::Future,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};

use omnipaxos::{
    storage::{Entry, Snapshot},
    util::NodeId,
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_runtime::{
    spawn_actor, AsyncRuntime, OmniPaxosEvent, OmniPaxosHandle, RuntimeConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;

/// Small but non-degenerate bound: the probe only needs the bound to be reached
/// inside a bounded window. The mechanism is the same for any finite capacity
/// (default 1024); only the number of unconsumed transitions changes.
const EVENT_CAPACITY: usize = 64;
/// Paced so that consecutive decided-index changes are observed in separate ticks,
/// i.e. each decision produces one event instead of one amalgamated event.
const PROPOSAL_PACE_MS: u64 = 4;

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

/// Minimal executor: tokio (a dev-dependency of this crate) drives the actor task.
struct TestRuntime;

impl AsyncRuntime for TestRuntime {
    type JoinHandle = ();
    fn spawn<F>(future: F)
    where
        F: Future<Output = ()> + Send + 'static,
    {
        let _ = tokio::spawn(future);
    }
    fn sleep(duration: Duration) -> impl Future<Output = ()> + Send + 'static {
        tokio::time::sleep(duration)
    }
}

fn build_op(
    pid: NodeId,
    nodes: Vec<NodeId>,
) -> omnipaxos::OmniPaxos<TestEntry, MemoryStorage<TestEntry>> {
    #[allow(clippy::needless_update)]
    let server_config = ServerConfig {
        pid,
        election_tick_timeout: 3,
        resend_message_tick_timeout: 5,
        buffer_size: 100,
        batch_size: 1,
        flush_batch_tick_timeout: 100,
        leader_priority: 0,
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

struct Cluster {
    handles: HashMap<NodeId, OmniPaxosHandle<TestEntry>>,
    /// Inspection handles on each node's event stream (clones of the same
    /// per-node receiver), used to read the channel state without consuming it.
    event_rx: HashMap<NodeId, async_channel::Receiver<OmniPaxosEvent>>,
}

/// 3-node in-process cluster: real OmniPaxos instances, real actors, in-memory
/// transport that forwards every outgoing message to its receiver's actor.
///
/// `consumer` decides what the application does with each node's event stream:
/// nothing (the handle's own receiver is simply never read) or drain it in a task.
async fn spawn_cluster(drain_events: bool) -> Cluster {
    let nodes: Vec<NodeId> = vec![1, 2, 3];
    let cfg = RuntimeConfig {
        tick_period: Duration::from_millis(2),
        egress_period: Duration::from_millis(1),
        event_capacity: EVENT_CAPACITY,
        append_notify_timeout: Duration::from_millis(1500),
        ..Default::default()
    };
    let mut handles: HashMap<NodeId, OmniPaxosHandle<TestEntry>> = HashMap::new();
    let mut event_rx = HashMap::new();
    for pid in nodes.clone() {
        let op = build_op(pid, nodes.clone());
        let h = spawn_actor::<TestEntry, MemoryStorage<TestEntry>, TestRuntime>(op, cfg.clone());
        let rx = h.subscribe_events();
        if drain_events {
            tokio::spawn(async move { while rx.recv().await.is_ok() {} });
        }
        event_rx.insert(pid, h.subscribe_events());
        handles.insert(pid, h);
    }
    let arc = Arc::new(handles.clone());
    for pid in nodes {
        let out = arc[&pid].outgoing_messages();
        let peers = arc.clone();
        tokio::spawn(async move {
            while let Ok(msg) = out.recv().await {
                if let Some(peer) = peers.get(&msg.get_receiver()) {
                    peer.handle_incoming(msg).await;
                }
            }
        });
    }
    Cluster { handles, event_rx }
}

/// Emitted on stdout as a CA_EVENT JSON line so the receipt carries the observed
/// operands, not just the test verdict.
fn emit(line: &str) {
    println!("CA_EVENT {line}");
}

/// A command round-trip completes: the actor task is running its select loop.
async fn responds(h: &OmniPaxosHandle<TestEntry>, budget: Duration) -> bool {
    tokio::time::timeout(budget, h.decided_idx()).await.is_ok()
}

async fn wait_for_stable_leader(c: &Cluster) -> Option<NodeId> {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(10);
    while tokio::time::Instant::now() < deadline {
        for h in c.handles.values() {
            if let Ok(Some((leader, true))) =
                tokio::time::timeout(Duration::from_millis(200), h.current_leader()).await
            {
                return Some(leader);
            }
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    None
}

/// Keep proposing ordinary writes on one origin, spaced out so that each decided
/// index change is observed by the actors in a separate tick.
fn keep_proposing(c: &Cluster, origin: NodeId, from: u64, count: u64) {
    let h = c.handles[&origin].clone();
    tokio::spawn(async move {
        for v in from..from + count {
            let origin_handle = h.clone();
            tokio::spawn(async move {
                let _ = origin_handle.append(TestEntry(v)).await;
            });
            tokio::time::sleep(Duration::from_millis(PROPOSAL_PACE_MS)).await;
        }
    });
}

fn channel_state(c: &Cluster) -> String {
    let mut s = String::new();
    for pid in [1u64, 2, 3] {
        let rx = &c.event_rx[&pid];
        s.push_str(&format!(
            " pid{pid}[len={} capacity={:?} full={} closed={}]",
            rx.len(),
            rx.capacity(),
            rx.is_full(),
            rx.is_closed()
        ));
    }
    s
}

async fn responsive_nodes(c: &Cluster, budget: Duration) -> usize {
    let mut n = 0;
    for h in c.handles.values() {
        if responds(h, budget).await {
            n += 1;
        }
    }
    n
}

/// Case 1: nothing consumes the event stream; the cluster is kept busy until the
/// bound is reached.
#[tokio::test]
async fn unconsumed_event_stream_stops_actor_loop() {
    let c = spawn_cluster(false).await;

    // The application never reads events. Get a leader going first, then keep the
    // cluster observing transitions until the event bound is reached.
    let leader = wait_for_stable_leader(&c).await;
    assert!(
        leader.is_some(),
        "setup: no stable leader while the event channel still had room{}",
        channel_state(&c)
    );
    keep_proposing(&c, leader.unwrap(), 0, EVENT_CAPACITY as u64 * 3);

    // Witness 1: every node reached the bound, so the actor can no longer publish
    // the next transition it observes.
    let deadline = tokio::time::Instant::now() + Duration::from_secs(8);
    let mut nodes_full = 0;
    loop {
        nodes_full = [1u64, 2, 3]
            .iter()
            .filter(|pid| c.event_rx[pid].is_full() && !c.event_rx[pid].is_closed())
            .count();
        if nodes_full == 3 {
            break;
        }
        assert!(
            tokio::time::Instant::now() < deadline,
            "the unconsumed event channels did not reach their bound:{}",
            channel_state(&c)
        );
        tokio::time::sleep(Duration::from_millis(100)).await;
    }

    // Witness 2: at least one node's actor loop is parked, and it stays parked
    // (samples over ~2s never show it serving a command again).
    let mut parked_pid: Option<NodeId> = None;
    let mut permanently_parked = true;
    for _ in 0..10 {
        let mut this_sample: Vec<NodeId> = Vec::new();
        for (pid, h) in c.handles.iter() {
            if !responds(h, Duration::from_millis(200)).await {
                this_sample.push(*pid);
            }
        }
        if this_sample.is_empty() {
            permanently_parked = false;
            break;
        }
        parked_pid = Some(parked_pid.map_or(this_sample[0], |p| p));
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    emit(&format!(
        "{{\"event\":\"unconsumed_event_bound_reached\",\"nodes_full\":{nodes_full},\"nodes\":3,\"event_capacity\":{EVENT_CAPACITY}}}"
    ));
    let parked_pid = parked_pid.expect("no node stopped answering commands");
    assert!(
        permanently_parked,
        "the parked actor recovered by itself; observed channel state:{}",
        channel_state(&c)
    );
    assert!(
        !responds(&c.handles[&parked_pid], Duration::from_millis(500)).await,
        "node {parked_pid} answered again; channel state:{}",
        channel_state(&c)
    );

    emit(&format!(
        "{{\"event\":\"actor_parked\",\"node\":{parked_pid},\"samples_without_reply\":10,\"reply_budget_ms\":200,\"permanently_parked\":{permanently_parked}}}"
    ));

    // Witness 3: on that parked node the proposal endpoint is gone too - its
    // append_notify_timeout is 1500ms, so a running actor would have answered
    // (Timeout at the latest) well before the outer 4s.
    let h = c.handles[&parked_pid].clone();
    let resolved = tokio::time::timeout(
        Duration::from_secs(4),
        h.append_notify_with_timeout(TestEntry(999), Duration::from_millis(300)),
    )
    .await;
    emit(&format!(
        "{{\"event\":\"append_notify_endpoint_withheld\",\"node\":{parked_pid},\"per_call_deadline_ms\":300,\"actor_timeout_ms\":1500,\"outer_wait_ms\":4000,\"resolved\":{}}}",
        resolved.is_ok()
    ));
    assert!(
        resolved.is_err(),
        "append_notify on parked node {parked_pid} resolved: {resolved:?}"
    );
}

/// Case 2 (control): same cluster, same capacity, same activity; the only
/// difference is that each node's event stream is drained.
#[tokio::test]
async fn drained_event_stream_keeps_actor_loop_running() {
    let c = spawn_cluster(true).await;
    let leader = wait_for_stable_leader(&c).await;
    assert!(leader.is_some(), "control: no stable leader{}", channel_state(&c));
    let leader = leader.unwrap();
    keep_proposing(&c, leader, 0, EVENT_CAPACITY as u64 * 3);

    let mut alive = 0;
    let deadline = tokio::time::Instant::now() + Duration::from_secs(8);
    while tokio::time::Instant::now() < deadline {
        alive = responsive_nodes(&c, Duration::from_millis(200)).await;
        if alive == c.handles.len() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    emit(&format!(
        "{{\"event\":\"control_actors_responsive\",\"nodes_answering\":{alive},\"nodes\":3,\"event_capacity\":{EVENT_CAPACITY}}}"
    ));
    assert_eq!(
        alive,
        c.handles.len(),
        "control: some actor loop stopped with a drained event stream{}",
        channel_state(&c)
    );

    let follower = *c.handles.keys().find(|&&p| p != leader).unwrap();
    let idx = match tokio::time::timeout(
        Duration::from_secs(5),
        c.handles[&follower].append_notify(TestEntry(7)),
    )
    .await
    {
        Ok(Ok(idx)) => idx,
        other => panic!("control append_notify: expected Ok(idx), got {other:?}"),
    };
    emit(&format!(
        "{{\"event\":\"control_append_notify\",\"origin\":{follower},\"succeeded\":{},\"idx\":{idx}}}",
        idx >= 1
    ));
    assert!(idx >= 1, "control append_notify returned idx {idx}");
}
