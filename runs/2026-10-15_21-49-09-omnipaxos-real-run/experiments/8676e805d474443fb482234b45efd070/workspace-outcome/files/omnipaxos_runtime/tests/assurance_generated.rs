//! Focused probe for the async actor layer's `append_notify` completion signal.
//!
//! Question: when a leader accepts an entry locally (which is what assigns it a log
//! index) and that entry never reaches a write quorum before a leadership change, what
//! resolution does the originating `append_notify` receive once the origin's local
//! decided index reaches the assigned index, and does the log at that index hold the
//! caller's entry?
//!
//! Every case runs a real in-process cluster of three OmniPaxos actors with an in-memory
//! transport, node 1 forced into the leader role, and (in the partition cases) both
//! directions of node 1's links cut. The only difference between the two partition cases
//! is the actor tick period, which controls whether a `drain_notifiers` pass can
//! interleave between the origin's promise change and its decided-index advance.

use std::{
    collections::{HashMap, HashSet},
    sync::{Arc, Mutex},
    time::Duration,
};

use omnipaxos::{
    storage::{Entry, Snapshot},
    util::{LogEntry, NodeId},
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_runtime::{spawn_actor, AppendError, AsyncRuntime, OmniPaxosHandle, RuntimeConfig};
use omnipaxos_storage::memory_storage::MemoryStorage;

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

#[cfg(feature = "unicache")]
#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize)]
struct NoUniCache;

#[cfg(feature = "unicache")]
impl omnipaxos::unicache::UniCache for NoUniCache {
    type T = TestEntry;
    fn new() -> Self {
        NoUniCache
    }
    fn try_encode(&mut self, entry: &Self::T) -> <Self::T as Entry>::EncodeResult {
        entry.clone()
    }
    fn decode(&mut self, processed: <Self::T as Entry>::EncodeResult) -> Self::T {
        processed
    }
}

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;

    #[cfg(feature = "unicache")]
    type Encoded = ();
    #[cfg(feature = "unicache")]
    type Encodable = TestEntry;
    #[cfg(feature = "unicache")]
    type NotEncodable = ();
    #[cfg(feature = "unicache")]
    type EncodeResult = TestEntry;
    #[cfg(feature = "unicache")]
    type UniCache = NoUniCache;
}

/// Minimal executor adapter over tokio (the crate's own `TokioRuntime` sits behind the
/// `tokio_runtime` feature; the test target only needs the two required primitives).
struct TestRt;

impl AsyncRuntime for TestRt {
    type JoinHandle = tokio::task::JoinHandle<()>;

    fn spawn<F>(future: F) -> Self::JoinHandle
    where
        F: std::future::Future<Output = ()> + Send + 'static,
    {
        tokio::spawn(future)
    }

    fn sleep(duration: Duration) -> impl std::future::Future<Output = ()> + Send + 'static {
        tokio::time::sleep(duration)
    }
}

/// Per-direction link state shared by all transport tasks. Dropping a message here is a
/// message loss / partition fault; the draining side always consumes, so a drop adds no
/// backpressure to the sender.
#[derive(Default)]
struct Net {
    blocked: Mutex<HashSet<(NodeId, NodeId)>>,
}

impl Net {
    fn set_blocked(&self, a: NodeId, b: NodeId, blocked: bool) {
        let mut guard = self.blocked.lock().unwrap();
        for (from, to) in [(a, b), (b, a)] {
            if blocked {
                guard.insert((from, to));
            } else {
                guard.remove(&(from, to));
            }
        }
    }

    fn allows(&self, from: NodeId, to: NodeId) -> bool {
        !self.blocked.lock().unwrap().contains(&(from, to))
    }
}

struct ClusterParams {
    tick_period: Duration,
    election_tick_timeout: u64,
    resend_message_tick_timeout: u64,
    append_notify_timeout: Duration,
}

fn build_node(
    pid: NodeId,
    nodes: Vec<NodeId>,
    leader_priority: u32,
    election_tick_timeout: u64,
    resend_message_tick_timeout: u64,
) -> omnipaxos::OmniPaxos<TestEntry, MemoryStorage<TestEntry>> {
    let cluster_config = ClusterConfig {
        configuration_id: 1,
        nodes,
        flexible_quorum: None,
    };
    #[allow(clippy::needless_update)]
    let server_config = ServerConfig {
        pid,
        election_tick_timeout,
        resend_message_tick_timeout,
        buffer_size: 1024,
        // Batching is what creates deferred `unconfirmed_local` placeholders.
        batch_size: 3,
        flush_batch_tick_timeout: 100,
        leader_priority,
        ..Default::default()
    };
    OmniPaxosConfig {
        cluster_config,
        server_config,
    }
    .build(MemoryStorage::default())
    .unwrap()
}

fn spawn_cluster(
    n: NodeId,
    params: &ClusterParams,
) -> (HashMap<NodeId, OmniPaxosHandle<TestEntry>>, Arc<Net>) {
    let nodes: Vec<NodeId> = (1..=n).collect();
    let cfg = RuntimeConfig {
        tick_period: params.tick_period,
        egress_period: Duration::from_millis(1),
        append_notify_timeout: params.append_notify_timeout,
        ..Default::default()
    };
    let net = Arc::new(Net::default());
    let mut handles: HashMap<NodeId, OmniPaxosHandle<TestEntry>> = HashMap::new();
    for pid in nodes.clone() {
        let op = build_node(
            pid,
            nodes.clone(),
            // Node 1 is preferred as leader so the pre-partition "stable leader" premise is
            // deterministic; a higher priority only breaks ties at equal ballot number.
            if pid == 1 { 1 } else { 0 },
            params.election_tick_timeout,
            params.resend_message_tick_timeout,
        );
        let h = spawn_actor::<TestEntry, MemoryStorage<TestEntry>, TestRt>(op, cfg.clone());
        handles.insert(pid, h);
    }
    let handles_arc = Arc::new(handles.clone());
    for pid in nodes {
        let out = handles_arc[&pid].outgoing_messages();
        let peers = handles_arc.clone();
        let net = net.clone();
        tokio::spawn(async move {
            while let Ok(msg) = out.recv().await {
                let (from, to) = (msg.get_sender(), msg.get_receiver());
                if !net.allows(from, to) {
                    continue;
                }
                if let Some(peer) = peers.get(&to) {
                    peer.handle_incoming(msg).await;
                }
            }
        });
    }
    (handles, net)
}

fn emit(event: &str, fields: &[(&str, String)]) {
    let mut line = format!("{{\"event\":\"{}\"", event);
    for (k, v) in fields {
        line.push_str(&format!(",\"{}\":{}", k, v));
    }
    line.push('}');
    println!("CA_EVENT {}", line);
}

fn q(v: &str) -> String {
    format!("\"{}\"", v)
}

fn b(v: bool) -> String {
    if v {
        "true".to_string()
    } else {
        "false".to_string()
    }
}

fn n(v: usize) -> String {
    v.to_string()
}

async fn leader_of(h: &OmniPaxosHandle<TestEntry>) -> Option<(NodeId, bool)> {
    h.current_leader().await
}

async fn wait_for_leader(
    handles: &HashMap<NodeId, OmniPaxosHandle<TestEntry>>,
    nodes: &[NodeId],
    want: Option<NodeId>,
    deadline: Duration,
) -> bool {
    let start = std::time::Instant::now();
    while start.elapsed() < deadline {
        let mut all = true;
        for pid in nodes {
            match (want, leader_of(&handles[pid]).await) {
                (Some(w), Some((p, true))) if p == w => {}
                (None, Some((p, true))) if p != 1 => {}
                _ => all = false,
            }
        }
        if all {
            return true;
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
    false
}

async fn force_leader_of_1(
    handles: &HashMap<NodeId, OmniPaxosHandle<TestEntry>>,
    election_timeout: Duration,
) -> bool {
    for _ in 0..10 {
        if wait_for_leader(handles, &[1, 2, 3], Some(1), Duration::from_millis(300)).await {
            // Require the leadership to survive several election timeouts before treating it
            // as the stable premise of a case.
            tokio::time::sleep(election_timeout * 4).await;
            if wait_for_leader(handles, &[1, 2, 3], Some(1), Duration::from_millis(50)).await {
                return true;
            }
        }
        handles[&1].try_become_leader().await;
    }
    false
}

fn election_timeout_of(params: &ClusterParams) -> Duration {
    params.tick_period * params.election_tick_timeout as u32 + params.tick_period
}

/// Describes what the decided log holds at the 0-based position `pos`.
fn value_at(log: &Option<Vec<LogEntry<TestEntry>>>, pos: usize) -> (String, bool) {
    match log {
        Some(entries) => match entries.get(pos) {
            Some(LogEntry::Decided(TestEntry(v))) => (format!("decided:{}", v), true),
            Some(other) => (format!("other:{:?}", other), true),
            None => ("not_decided".to_string(), false),
        },
        None => ("no_decided_entries".to_string(), false),
    }
}

fn all_decided_values(log: &Option<Vec<LogEntry<TestEntry>>>) -> String {
    match log {
        Some(entries) => entries
            .iter()
            .map(|e| match e {
                LogEntry::Decided(TestEntry(v)) => v.to_string(),
                _ => "?".to_string(),
            })
            .collect::<Vec<_>>()
            .join(","),
        None => String::new(),
    }
}

fn resolution_text(res: &Result<usize, AppendError<TestEntry>>) -> (String, Option<usize>) {
    match res {
        Ok(idx) => ("ok".to_string(), Some(*idx)),
        Err(AppendError::Superseded { log_entry_idx }) => {
            ("superseded".to_string(), Some(*log_entry_idx))
        }
        Err(AppendError::Timeout) => ("timeout".to_string(), None),
        Err(AppendError::TooManyOutstanding) => ("too_many_outstanding".to_string(), None),
        Err(AppendError::Shutdown) => ("shutdown".to_string(), None),
        Err(AppendError::Propose(_)) => ("propose_err".to_string(), None),
    }
}

/// Reports, for the resolved index, whether the decided log at that index holds the
/// caller's entry. `entry_equals_submitted` is emitted only when the index was actually
/// observed in the decided log; an unobserved position stays unknown, not false.
fn report_resolution(
    mode: &str,
    submitted: u64,
    resolved: &str,
    assigned_idx: Option<usize>,
    decided: Option<Vec<LogEntry<TestEntry>>>,
    extra: &[(&str, String)],
) {
    let mut fields: Vec<(&str, String)> = vec![
        ("mode", q(mode)),
        ("origin", n(1)),
        ("submitted_value", submitted.to_string()),
        ("resolved", q(resolved)),
    ];
    fields.extend(extra.iter().cloned());
    if let Some(idx) = assigned_idx {
        fields.push(("assigned_idx", n(idx)));
        if idx >= 1 {
            let pos = idx - 1;
            let (text, observed) = value_at(&decided, pos);
            fields.push(("entry_at_assigned_idx", q(&text)));
            if observed {
                fields.push((
                    "entry_equals_submitted",
                    b(text == format!("decided:{}", submitted)),
                ));
            }
        }
    }
    fields.push(("origin_decided_values", q(&all_decided_values(&decided))));
    // One result event name per mode so each comparison selects exactly one event and can
    // be evaluated complete on its own admission (a shared name made the other modes'
    // events unreachable for that admission).
    emit(&format!("notify_resolution_{}", mode.to_lowercase()), &fields);
}

/// Control case: no partition, so the entry is replicated and decided normally by the
/// same leader that assigned it.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn case_a_control_no_partition() {
    let params = ClusterParams {
        tick_period: Duration::from_millis(2),
        election_tick_timeout: 3,
        resend_message_tick_timeout: 5,
        append_notify_timeout: Duration::from_secs(20),
    };
    let (handles, _net) = spawn_cluster(3, &params);
    let forced = force_leader_of_1(&handles, election_timeout_of(&params)).await;
    emit(
        "admission",
        &[
            ("mode", q("A")),
            ("setup", q("cluster=3,leader=1,no_partition")),
            ("origin", n(1)),
            ("submitted_value", n(11)),
            ("forced_leader_1", b(forced)),
            ("tick_ms", n(params.tick_period.as_millis() as usize)),
        ],
    );
    let res = tokio::time::timeout(
        Duration::from_secs(15),
        handles[&1].append_notify(TestEntry(11)),
    )
    .await;
    let (resolved, assigned_idx, extra) = match res {
        Ok(r) => {
            let (t, i) = resolution_text(&r);
            (t, i, vec![("await_expired", b(false))])
        }
        Err(_) => (
            "await_expired".to_string(),
            None,
            vec![("await_expired", b(true))],
        ),
    };
    let decided = handles[&1].read_decided_suffix(0).await;
    let decided_idx = handles[&1].decided_idx().await;
    let mut all = extra;
    all.push(("origin_decided_idx", n(decided_idx)));
    report_resolution("A", 11, &resolved, assigned_idx, decided, &all);
}

/// Partition case, short tick: a `drain_notifiers` pass repeatedly interleaves between the
/// origin's promise change and its decided-index advance.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn case_b_partition_short_tick() {
    partition_case(
        "B",
        Duration::from_millis(2),
        3,
        5,
        Duration::from_secs(20),
    )
    .await;
}

/// Partition case, long tick: the promise change and the decided-index advance both land
/// inside one tick period, so the same lost-entry state is examined in a single pass.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn case_c_partition_long_tick() {
    partition_case(
        "C",
        Duration::from_millis(80),
        3,
        4,
        Duration::from_secs(60),
    )
    .await;
}

async fn partition_case(
    mode: &str,
    tick_period: Duration,
    election_tick_timeout: u64,
    resend_message_tick_timeout: u64,
    append_notify_timeout: Duration,
) {
    let params = ClusterParams {
        tick_period,
        election_tick_timeout,
        resend_message_tick_timeout,
        append_notify_timeout,
    };
    let (handles, net) = spawn_cluster(3, &params);
    let forced = force_leader_of_1(&handles, election_timeout_of(&params)).await;
    emit(
        "admission",
        &[
            ("mode", q(mode)),
            ("setup", q("cluster=3,leader=1,partition=1<->{2,3}")),
            ("origin", n(1)),
            ("submitted_value", n(11)),
            ("forced_leader_1", b(forced)),
            ("tick_ms", n(params.tick_period.as_millis() as usize)),
        ],
    );

    // Cut node 1 off from both followers, then immediately let node 1 - still the leader in
    // the accept phase - take the caller's entry. It can only be accepted locally.
    net.set_blocked(1, 2, true);
    net.set_blocked(1, 3, true);
    let origin_handle = handles[&1].clone();
    let origin_task =
        tokio::spawn(async move { origin_handle.append_notify(TestEntry(11)).await });
    tokio::time::sleep(tick_period.max(Duration::from_millis(20))).await;
    let origin_decided_while_partitioned = handles[&1].decided_idx().await;

    let elected = wait_for_leader(&handles, &[2, 3], None, Duration::from_secs(8)).await;
    let new_leader = if elected {
        leader_of(&handles[&2])
            .await
            .filter(|(p, _)| *p != 1)
            .map(|(p, _)| p)
    } else {
        None
    };
    let new_leader = match new_leader {
        Some(p) => p,
        None => {
            let decided = handles[&1].read_decided_suffix(0).await;
            let extra = vec![
                ("new_leader", q("none_elected")),
                (
                    "origin_decided_while_partitioned",
                    n(origin_decided_while_partitioned),
                ),
            ];
            report_resolution(mode, 11, "no_new_leader", None, decided, &extra);
            return;
        }
    };
    emit(
        "new_leader_elected",
        &[
            ("mode", q(mode)),
            ("new_leader", n(new_leader as usize)),
            (
                "origin_decided_while_partitioned",
                n(origin_decided_while_partitioned),
            ),
        ],
    );

    // A different entry, appended through the new leader, decided at the same first index.
    let newer = tokio::time::timeout(
        Duration::from_secs(25),
        handles[&new_leader].append_notify(TestEntry(22)),
    )
    .await;
    let (newer_outcome, newer_idx) = match newer {
        Ok(Ok(idx)) => ("ok".to_string(), Some(idx)),
        Ok(Err(_)) => ("err".to_string(), None),
        Err(_) => ("await_expired".to_string(), None),
    };
    emit(
        "new_leader_append",
        &[
            ("mode", q(mode)),
            ("new_leader", n(new_leader as usize)),
            ("submitted_value", n(22)),
            ("outcome", q(&newer_outcome)),
            ("assigned_idx", newer_idx.map(n).unwrap_or_else(|| q("null"))),
            (
                "new_leader_decided_idx",
                n(handles[&new_leader].decided_idx().await),
            ),
            (
                "new_leader_decided_values",
                q(&all_decided_values(
                    &handles[&new_leader].read_decided_suffix(0).await,
                )),
            ),
        ],
    );

    // Reconnect the origin so the new leader re-synchronizes it.
    net.set_blocked(1, 2, false);
    net.set_blocked(1, 3, false);
    let res = tokio::time::timeout(Duration::from_secs(35), origin_task).await;
    let await_expired = res.is_err();
    let (resolved, assigned_idx) = match res {
        Ok(Ok(r)) => resolution_text(&r),
        Ok(Err(_)) => ("join_err".to_string(), None),
        Err(_) => ("await_expired".to_string(), None),
    };
    let decided = handles[&1].read_decided_suffix(0).await;
    let origin_decided_idx = handles[&1].decided_idx().await;
    let origin_leader = leader_of(&handles[&1]).await;
    let extra = vec![
        ("await_expired", b(await_expired)),
        ("origin_decided_idx", n(origin_decided_idx)),
        (
            "origin_leader_pid",
            origin_leader
                .map(|(p, _)| p as usize)
                .map(n)
                .unwrap_or_else(|| q("none")),
        ),
        (
            "origin_decided_while_partitioned",
            n(origin_decided_while_partitioned),
        ),
    ];
    report_resolution(mode, 11, &resolved, assigned_idx, decided, &extra);
}

/// Case H: does a truncation that discards entries whose placeholders are still queued
/// shift the index later reported to a caller?
///
/// Node 1 buffers two entries in its batch (size 3), is cut off so the followers take over
/// and decide entry 22 at index 1, then reconnects: the `Prepare` flushes the two buffered
/// entries and the following `AcceptSync` truncates the log back to the new leader's single
/// entry, inside one tick period. Node 1 then becomes leader again and a fresh
/// `append_notify` fills the batch. If the placeholders for the discarded entries are still
/// queued, they consume index advances ahead of the fresh placeholder and the caller is told
/// an index that does not hold its entry.
/// Parameterised variant of the case above, used to sweep the tick period: everything but
/// the tick period and the emitted mode label is identical across cases.
async fn run_shift_case(mode: &str, tick_ms: u64) {
    let params = ClusterParams {
        // A tick period far above the flush-to-truncation gap, so a `drain_notifiers` pass
        // is very unlikely to fall between the two messages.
        tick_period: Duration::from_millis(tick_ms),
        election_tick_timeout: 2,
        resend_message_tick_timeout: 2,
        append_notify_timeout: Duration::from_secs(150),
    };
    let (handles, net) = spawn_cluster(3, &params);
    let forced = force_leader_of_1(&handles, election_timeout_of(&params)).await;
    emit(
        "admission",
        &[
            ("mode", q(mode)),
            ("origin", n(1)),
            ("submitted_value", n(33)),
            ("forced_leader_1", b(forced)),
            ("tick_ms", n(params.tick_period.as_millis() as usize)),
        ],
    );

    // Phase 1: two entries buffered in node 1's batch (batch size 3, so nothing flushes).
    let buffered_handle = handles[&1].clone();
    let _buffered_a =
        tokio::spawn(async move { buffered_handle.append_notify(TestEntry(11)).await });
    tokio::time::sleep(Duration::from_millis(120 + tick_ms)).await;
    let buffered_handle_b = handles[&1].clone();
    let _buffered_b =
        tokio::spawn(async move { buffered_handle_b.append_notify(TestEntry(12)).await });
    tokio::time::sleep(Duration::from_millis(120 + tick_ms)).await;
    let decided_after_buffering = handles[&1].decided_idx().await;

    // Phase 2: cut node 1 off; the followers take over and decide entry 22 at index 1.
    net.set_blocked(1, 2, true);
    net.set_blocked(1, 3, true);
    let elected = wait_for_leader(&handles, &[2, 3], None, Duration::from_secs(8)).await;
    let new_leader = leader_of(&handles[&2])
        .await
        .filter(|(p, _)| *p != 1)
        .map(|(p, _)| p)
        .unwrap_or(0);
    let new_leader_decided = if elected && new_leader != 0 {
        matches!(
            tokio::time::timeout(
                Duration::from_secs(30),
                handles[&new_leader].append_notify(TestEntry(22))
            )
            .await,
            Ok(Ok(1))
        )
    } else {
        false
    };

    // Phase 3: heal; node 1 flushes its batch and is truncated back in the same tick.
    net.set_blocked(1, 2, false);
    net.set_blocked(1, 3, false);
    // The new leader re-prepares the reconnected node on its resend tick, and the flush and
    // the following truncation must both happen inside one tick period.
    tokio::time::sleep(Duration::from_millis((8 * tick_ms).max(2000))).await;
    let decided_after_resync = handles[&1].decided_idx().await;

    // Phase 4: node 1 leads again and buffers a fresh entry, filling the batch with two more.
    let mut re_elected = false;
    for _ in 0..20 {
        handles[&1].try_become_leader().await;
        tokio::time::sleep(Duration::from_millis((3 * tick_ms / 2).max(300))).await;
        if let Some((pid, true)) = leader_of(&handles[&1]).await {
            if pid == 1 {
                re_elected = true;
                break;
            }
        }
    }
    let fresh_handle = handles[&1].clone();
    let fresh = tokio::spawn(async move { fresh_handle.append_notify(TestEntry(33)).await });
    tokio::time::sleep(Duration::from_millis((3 * tick_ms / 2).max(300))).await;
    let _ = handles[&1].append(TestEntry(34)).await;
    let _ = handles[&1].append(TestEntry(35)).await;
    // The batch flushes immediately (it is full); the placeholder reconciliation and the
    // resolution both need a tick, so allow several.
    tokio::time::sleep(Duration::from_millis((4 * tick_ms).max(1200))).await;

    let res = tokio::time::timeout(Duration::from_secs(40), fresh).await;
    let (resolved, assigned_idx) = match res {
        Ok(Ok(r)) => resolution_text(&r),
        Ok(Err(_)) => ("join_err".to_string(), None),
        Err(_) => ("await_expired".to_string(), None),
    };
    let log = handles[&1].read_decided_suffix(0).await;
    let mut true_index = 0usize;
    if let Some(entries) = &log {
        for (pos, entry) in entries.iter().enumerate() {
            if let LogEntry::Decided(TestEntry(v)) = entry {
                if *v == 33 {
                    true_index = pos + 1;
                    break;
                }
            }
        }
    }
    let mut entry_at = "unmeasured".to_string();
    if let Some(idx) = assigned_idx {
        if idx >= 1 {
            let (text, _observed) = value_at(&log, idx - 1);
            entry_at = text;
        }
    }
    emit(
        &format!("shift_outcome_{}", mode.to_lowercase()),
        &[
            ("mode", q(mode)),
            ("origin", n(1)),
            ("forced_leader_1", b(forced)),
            ("buffer_size_entries", n(2)),
            ("decided_after_buffering", n(decided_after_buffering)),
            ("new_leader", n(new_leader as usize)),
            ("new_leader_decided_entry_22_at_1", b(new_leader_decided)),
            ("decided_after_resync", n(decided_after_resync)),
            ("origin_re_elected", b(re_elected)),
            ("submitted_value", n(33)),
            ("resolved", q(&resolved)),
            (
                "assigned_idx",
                assigned_idx.map(n).unwrap_or_else(|| q("null")),
            ),
            ("submitted_entry_true_index", n(true_index)),
            (
                "assigned_idx_matches_true_index",
                b(assigned_idx == Some(true_index) && true_index != 0),
            ),
            ("entry_at_assigned_idx", q(&entry_at)),
            ("origin_decided_values", q(&all_decided_values(&log))),
        ],
    );
}

/// Reference case: the tick period used by the retained finding.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn case_h_placeholder_shift_after_truncation() {
    run_shift_case("H", 1000).await;
}

/// Sweep points: is the shift still delivered when the tick period comes closer to the
/// flush-to-truncation gap?
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn case_i_shift_tick_100ms() {
    run_shift_case("I", 100).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn case_j_shift_tick_250ms() {
    run_shift_case("J", 250).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn case_k_shift_tick_500ms() {
    run_shift_case("K", 500).await;
}
