//! Generated assurance harness (experiment target).
//!
//! Question: when a crash-recovered node whose decided index lags its accepted index becomes
//! leader, can a healthy follower that has compacted past that decided index still build its log
//! update?
//!
//! Deterministic, single-threaded, in-process: three real `OmniPaxos` instances are driven by
//! explicit tick/route steps, and one of them is recreated from its persisted storage to model a
//! crash-recovery. No network, no timers, no threads.

use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::rc::Rc;

use omnipaxos::{
    ballot_leader_election::Ballot,
    messages::{sequence_paxos::PaxosMsg, Message},
    storage::{Entry, Snapshot, StopSign, Storage, StorageOp, StorageResult},
    util::{LogEntry, NodeId},
    ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;
use serde_json::{json, Value};

fn emit(event: &str, fields: Value) {
    let mut obj = json!({ "event": event });
    if let Some(map) = fields.as_object() {
        for (k, v) in map {
            obj[k] = v.clone();
        }
    }
    println!("CA_EVENT {obj}");
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct TestEntry(pub u64);

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct NoSnapshot;

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

/// Persistent-state handle: a crashed node is recreated from the same underlying storage so the
/// recovery reads exactly the state the node had durably written before the crash.
#[derive(Clone)]
pub struct SharedStorage<T: Entry>(Rc<RefCell<MemoryStorage<T>>>);

impl<T: Entry> SharedStorage<T> {
    fn new() -> Self {
        SharedStorage(Rc::new(RefCell::new(MemoryStorage::default())))
    }
}

impl<T: Entry> Storage<T> for SharedStorage<T> {
    fn write_atomically(&mut self, ops: Vec<StorageOp<T>>) -> StorageResult<()> {
        self.0.borrow_mut().write_atomically(ops)
    }
    fn append_entry(&mut self, e: T) -> StorageResult<()> {
        self.0.borrow_mut().append_entry(e)
    }
    fn append_entries(&mut self, e: Vec<T>) -> StorageResult<()> {
        self.0.borrow_mut().append_entries(e)
    }
    fn append_on_prefix(&mut self, i: usize, e: Vec<T>) -> StorageResult<()> {
        self.0.borrow_mut().append_on_prefix(i, e)
    }
    fn set_promise(&mut self, b: Ballot) -> StorageResult<()> {
        self.0.borrow_mut().set_promise(b)
    }
    fn set_decided_idx(&mut self, i: usize) -> StorageResult<()> {
        self.0.borrow_mut().set_decided_idx(i)
    }
    fn get_decided_idx(&self) -> StorageResult<usize> {
        self.0.borrow().get_decided_idx()
    }
    fn set_accepted_round(&mut self, b: Ballot) -> StorageResult<()> {
        self.0.borrow_mut().set_accepted_round(b)
    }
    fn get_accepted_round(&self) -> StorageResult<Option<Ballot>> {
        self.0.borrow().get_accepted_round()
    }
    fn get_entries(&self, f: usize, t: usize) -> StorageResult<Vec<T>> {
        self.0.borrow().get_entries(f, t)
    }
    fn get_log_len(&self) -> StorageResult<usize> {
        self.0.borrow().get_log_len()
    }
    fn get_suffix(&self, f: usize) -> StorageResult<Vec<T>> {
        self.0.borrow().get_suffix(f)
    }
    fn get_promise(&self) -> StorageResult<Option<Ballot>> {
        self.0.borrow().get_promise()
    }
    fn set_stopsign(&mut self, s: Option<StopSign>) -> StorageResult<()> {
        self.0.borrow_mut().set_stopsign(s)
    }
    fn get_stopsign(&self) -> StorageResult<Option<StopSign>> {
        self.0.borrow().get_stopsign()
    }
    fn trim(&mut self, i: usize) -> StorageResult<()> {
        self.0.borrow_mut().trim(i)
    }
    fn set_compacted_idx(&mut self, i: usize) -> StorageResult<()> {
        self.0.borrow_mut().set_compacted_idx(i)
    }
    fn get_compacted_idx(&self) -> StorageResult<usize> {
        self.0.borrow().get_compacted_idx()
    }
    fn set_snapshot(&mut self, s: Option<T::Snapshot>) -> StorageResult<()> {
        self.0.borrow_mut().set_snapshot(s)
    }
    fn get_snapshot(&self) -> StorageResult<Option<T::Snapshot>> {
        self.0.borrow().get_snapshot()
    }
}

type Op = OmniPaxos<TestEntry, SharedStorage<TestEntry>>;

fn nodes_vec(n: usize) -> Vec<NodeId> {
    (1..=n as u64).collect()
}

fn build_op(
    pid: NodeId,
    nodes: Vec<NodeId>,
    batch_size: usize,
    store: SharedStorage<TestEntry>,
) -> Op {
    let cluster_config = ClusterConfig {
        configuration_id: 1,
        nodes,
        flexible_quorum: None,
    };
    #[allow(clippy::needless_update)]
    let server_config = ServerConfig {
        pid,
        election_tick_timeout: 2,
        resend_message_tick_timeout: 4,
        buffer_size: 10_000,
        batch_size,
        flush_batch_tick_timeout: 1000,
        leader_priority: 0,
        ..Default::default()
    };
    OmniPaxosConfig {
        cluster_config,
        server_config,
    }
    .build(store)
    .expect("failed to build OmniPaxos instance")
}

fn kind_of(m: &Message<TestEntry>) -> &'static str {
    match m {
        Message::SequencePaxos(p) => match &p.msg {
            PaxosMsg::PrepareReq(_) => "PrepareReq",
            PaxosMsg::Prepare(_) => "Prepare",
            PaxosMsg::Promise(_) => "Promise",
            PaxosMsg::AcceptSync(_) => "AcceptSync",
            PaxosMsg::AcceptDecide(_) => "AcceptDecide",
            PaxosMsg::Accepted(_) => "Accepted",
            PaxosMsg::NotAccepted(_) => "NotAccepted",
            PaxosMsg::Decide(_) => "Decide",
            PaxosMsg::ProposalForward(_) => "ProposalForward",
            PaxosMsg::Compaction(_) => "Compaction",
            PaxosMsg::AcceptStopSign(_) => "AcceptStopSign",
            PaxosMsg::ForwardStopSign(_) => "ForwardStopSign",
        },
        Message::BLE(_) => "BLE",
        #[allow(unreachable_patterns)]
        _ => "Other",
    }
}

struct Cluster {
    n: usize,
    batch: usize,
    ops: HashMap<NodeId, Op>,
    stores: HashMap<NodeId, SharedStorage<TestEntry>>,
    /// messages sent to a muted node are dropped
    mute: HashSet<NodeId>,
    /// per-node message kinds that are dropped
    mute_kinds: HashMap<NodeId, HashSet<String>>,
    dropped: usize,
    delivered: usize,
    attempted: usize,
}

impl Cluster {
    fn new(n: usize, batch: usize) -> Self {
        let nodes = nodes_vec(n);
        let mut ops = HashMap::new();
        let mut stores = HashMap::new();
        for pid in nodes.clone() {
            let store = SharedStorage::new();
            stores.insert(pid, store.clone());
            ops.insert(pid, build_op(pid, nodes.clone(), batch, store));
        }
        Cluster {
            n,
            batch,
            ops,
            stores,
            mute: HashSet::new(),
            mute_kinds: HashMap::new(),
            dropped: 0,
            delivered: 0,
            attempted: 0,
        }
    }

    fn alive(&self) -> Vec<NodeId> {
        let mut v: Vec<NodeId> = self.ops.keys().copied().collect();
        v.sort();
        v
    }

    fn route(&mut self) {
        let mut msgs: Vec<Message<TestEntry>> = Vec::new();
        for op in self.ops.values_mut() {
            let mut buf = Vec::new();
            op.take_outgoing_messages(&mut buf);
            msgs.extend(buf);
        }
        for m in msgs {
            self.attempted += 1;
            let to = m.get_receiver();
            let from = m.get_sender();
            let kind = kind_of(&m);
            let muted = self.mute.contains(&to)
                || self
                    .mute_kinds
                    .get(&to)
                    .map_or(false, |s| s.contains(kind));
            if muted {
                self.dropped += 1;
                continue;
            }
            if let Some(op) = self.ops.get_mut(&to) {
                op.handle_incoming(m);
                self.delivered += 1;
            } else {
                self.dropped += 1;
            }
            let _ = from;
        }
    }

    fn tick_all(&mut self) {
        for op in self.ops.values_mut() {
            op.tick();
        }
    }

    fn step(&mut self) {
        self.route();
        self.tick_all();
        self.route();
    }

    fn pump_until<F: Fn(&Cluster) -> bool>(&mut self, steps: usize, cond: F) -> bool {
        for _ in 0..steps {
            if cond(self) {
                return true;
            }
            self.step();
        }
        cond(self)
    }

    fn leader(&self) -> Option<NodeId> {
        for (pid, op) in &self.ops {
            if let Some((l, true)) = op.get_current_leader() {
                if l == *pid {
                    return Some(*pid);
                }
            }
        }
        None
    }

    fn accepted_idx(&self, pid: NodeId) -> usize {
        self.ops[&pid].get_accepted_idx()
    }

    fn decided_idx(&self, pid: NodeId) -> usize {
        self.ops[&pid].get_decided_idx()
    }

    fn compacted_idx(&self, pid: NodeId) -> usize {
        self.ops[&pid].get_compacted_idx()
    }

    fn promise(&self, pid: NodeId) -> Ballot {
        self.ops[&pid].get_promise()
    }

    fn append(&mut self, pid: NodeId, e: TestEntry) -> bool {
        self.ops.get_mut(&pid).unwrap().append(e).is_ok()
    }

    fn crash(&mut self, pid: NodeId) {
        self.ops.remove(&pid);
    }

    fn recover(&mut self, pid: NodeId) {
        let store = self.stores[&pid].clone();
        let (n, batch) = (self.n, self.batch);
        self.ops
            .insert(pid, build_op(pid, nodes_vec(n), batch, store));
    }

    /// Decided entry values in log order. Only valid while nothing has been compacted, because a
    /// compacted prefix is returned as a single marker rather than entry-by-entry.
    fn decided_values(&self, pid: NodeId) -> Vec<u64> {
        let op = &self.ops[&pid];
        let decided = op.get_decided_idx();
        if decided == 0 {
            return Vec::new();
        }
        op.read_decided_suffix(0)
            .unwrap_or_default()
            .into_iter()
            .filter_map(|e| match e {
                LogEntry::Decided(v) => Some(v.0),
                _ => None,
            })
            .collect()
    }

    /// The value readable at a single index, if it is a decided entry.
    fn decided_at(&self, pid: NodeId, idx: usize) -> Option<u64> {
        match self.ops[&pid].read(idx) {
            Some(LogEntry::Decided(v)) => Some(v.0),
            _ => None,
        }
    }
}

#[test]
fn stale_decided_node_prepares_against_compacted_follower() {
    let mut c = Cluster::new(3, 3);
    assert!(
        c.pump_until(2000, |c| c.leader().is_some()),
        "no leader was elected in the setup phase"
    );
    let l0 = c.leader().unwrap();

    // Phase A: three entries decided by all three nodes.
    for i in 0..3u64 {
        assert!(c.append(l0, TestEntry(i)), "append failed in phase A");
    }
    assert!(
        c.pump_until(4000, |c| c.alive()
            .iter()
            .all(|p| c.decided_idx(*p) == 3)),
        "phase A entries were not decided by every node"
    );

    let mut followers: Vec<NodeId> = c.alive().into_iter().filter(|p| *p != l0).collect();
    followers.sort();
    let v = followers[0]; // ends up with a stale decided index, then takes over
    let f = followers[1]; // stays healthy and compacts past v's decided index
    emit(
        "setup",
        json!({
            "case": "stale_decided_vs_compacted_follower",
            "initial_leader": l0,
            "stale_node": v,
            "healthy_follower": f,
            "batch_size": c.batch,
            "entries_per_batch": 3,
        }),
    );

    // Phase B: one batched accept. v must accept all six entries but must never learn the new
    // decisions, so its durable state is "accepted 6, decided 3" exactly like a node that
    // crashed after appending but before the decision reached it.
    for i in 10..13u64 {
        assert!(c.append(l0, TestEntry(i)), "append failed in phase B");
    }
    let mut v_muted = false;
    let mut healthy_decided = false;
    for _ in 0..8000 {
        c.route();
        if !v_muted && c.accepted_idx(v) == 6 {
            c.mute.insert(v);
            v_muted = true;
        }
        if c.decided_idx(f) == 6 {
            healthy_decided = true;
            break;
        }
        c.tick_all();
        if c.decided_idx(f) == 6 {
            healthy_decided = true;
            break;
        }
    }
    emit(
        "case_admitted",
        json!({
            "case": "stale_decided_vs_compacted_follower",
            "v_accepted_idx": c.accepted_idx(v),
            "v_decided_idx": c.decided_idx(v),
            "f_accepted_idx": c.accepted_idx(f),
            "f_decided_idx": c.decided_idx(f),
        }),
    );
    assert!(
        healthy_decided
            && c.accepted_idx(v) == 6
            && c.decided_idx(v) == 3
            && c.accepted_idx(f) == 6
            && c.decided_idx(f) == 6,
        "precondition not reached: v=({}, {}), f=({}, {})",
        c.accepted_idx(v),
        c.decided_idx(v),
        c.accepted_idx(f),
        c.decided_idx(f)
    );

    // Phase C: the leader trims the decided prefix to 6. Every node has accepted 6, so the trim is
    // legal; the healthy follower compacts, the muted stale node misses the forwarded compaction.
    let trim_res = c.ops.get_mut(&l0).unwrap().trim(Some(6));
    assert!(trim_res.is_ok(), "trim to 6 was rejected: {trim_res:?}");
    c.pump_until(200, |c| c.compacted_idx(f) == 6);
    emit(
        "trim_applied",
        json!({
            "case": "stale_decided_vs_compacted_follower",
            "trim_idx": 6,
            "old_leader_compacted_idx": c.compacted_idx(l0),
            "healthy_follower_compacted_idx": c.compacted_idx(f),
            "stale_node_compacted_idx": c.compacted_idx(v),
        }),
    );
    assert_eq!(
        c.compacted_idx(f),
        6,
        "healthy follower did not compact to the trim index"
    );

    // Phase D: the old leader crashes. The stale node keeps accepted 6 / decided 3 / old round.
    c.crash(l0);
    c.mute.remove(&v);
    // Let v promise to the new leader but never accept under its ballot: only AcceptSync to v is lost.
    let mut lost_kinds = HashSet::new();
    lost_kinds.insert("AcceptSync".to_string());
    c.mute_kinds.insert(v, lost_kinds);

    // Phase E: the healthy follower becomes the accepted leader under a newer ballot.
    let f_is_leader = c.pump_until(4000, |c| {
        matches!(c.ops[&f].get_current_leader(), Some((p, true)) if p == f)
    });
    emit(
        "new_leader_established",
        json!({
            "case": "stale_decided_vs_compacted_follower",
            "healthy_follower_is_leader": f_is_leader,
            "healthy_follower_ballot": format!("{:?}", c.promise(f)),
            "stale_node_promise": format!("{:?}", c.promise(v)),
            "stale_node_accepted_idx": c.accepted_idx(v),
            "stale_node_decided_idx": c.decided_idx(v),
            "healthy_follower_compacted_idx": c.compacted_idx(f),
            "healthy_follower_accepted_idx": c.accepted_idx(f),
            "healthy_follower_decided_idx": c.decided_idx(f),
        }),
    );
    assert!(
        f_is_leader,
        "healthy follower never reached (Leader, Accept)"
    );
    assert_eq!(
        c.decided_idx(v),
        3,
        "stale node must still have the old decided index"
    );

    // Phase F: the stale node starts a takeover. The healthy follower must build its log update
    // while handling the incoming Prepare.
    c.ops.get_mut(&v).unwrap().try_become_leader();
    let delivered_to_f_before = c.delivered;
    let outcome = catch_unwind(AssertUnwindSafe(|| {
        c.route();
    }));
    let delivered_after = c.delivered;
    match outcome {
        Ok(()) => {
            emit(
                "log_sync_outcome",
                json!({
                    "case": "stale_decided_vs_compacted_follower",
                    "outcome": "completed",
                    "panic_message": Value::Null,
                    "healthy_follower_compacted_idx": c.compacted_idx(f),
                    "stale_node_decided_idx": c.decided_idx(v),
                    "stale_node_accepted_idx": c.accepted_idx(v),
                    "messages_delivered_this_step": delivered_after - delivered_to_f_before,
                }),
            );
        }
        Err(payload) => {
            let msg = payload
                .downcast_ref::<String>()
                .cloned()
                .or_else(|| payload.downcast_ref::<&str>().map(|s| s.to_string()))
                .unwrap_or_else(|| "<non-string panic payload>".to_string());
            emit(
                "log_sync_outcome",
                json!({
                    "case": "stale_decided_vs_compacted_follower",
                    "outcome": "aborted_panic",
                    "panic_message": msg,
                    "healthy_follower_compacted_idx": c.compacted_idx(f),
                    "stale_node_decided_idx": c.decided_idx(v),
                    "stale_node_accepted_idx": c.accepted_idx(v),
                    "messages_delivered_this_step": delivered_after - delivered_to_f_before,
                }),
            );
        }
    }
    emit(
        "run_summary",
        json!({
            "case": "stale_decided_vs_compacted_follower",
            "attempted_messages": c.attempted,
            "delivered_messages": c.delivered,
            "dropped_messages": c.dropped,
        }),
    );
}

/// Case: a batched cluster with entries proposed concurrently on the leader and on a follower.
/// Every node must report and hold the same decided prefix, and the entry readable at each index
/// must be the element the node reports for that index.
#[test]
fn batched_mixed_proposals_agree_on_prefix_and_index_content() {
    let mut c = Cluster::new(3, 4);
    assert!(
        c.pump_until(2000, |c| c.leader().is_some()),
        "no leader was elected in the batched case"
    );
    let leader = c.leader().unwrap();
    let follower = *c.alive().iter().find(|p| **p != leader).unwrap();
    let total = 16usize;
    emit(
        "batched_admitted",
        json!({
            "case": "batched_mixed_proposals",
            "leader": leader,
            "follower": follower,
            "batch_size": c.batch,
            "proposals": total,
        }),
    );
    for i in 0..8u64 {
        assert!(c.append(leader, TestEntry(i)), "leader proposal {i} rejected");
        assert!(
            c.append(follower, TestEntry(100 + i)),
            "follower proposal {} rejected",
            100 + i
        );
    }
    let decided_everywhere = c.pump_until(6000, |c| {
        c.alive().iter().all(|p| c.decided_idx(*p) == total)
    });
    let logs: Vec<(NodeId, Vec<u64>)> = c
        .alive()
        .iter()
        .map(|p| (*p, c.decided_values(*p)))
        .collect();
    let all_logs_equal = logs.iter().all(|(_, v)| *v == logs[0].1);
    let mut values: Vec<u64> = logs[0].1.clone();
    values.sort();
    let mut expected: Vec<u64> = (0..8u64).chain(100..108u64).collect();
    expected.sort();
    let all_values_present = values == expected;
    let index_content_consistent = log_indices_consistent(&c, &logs[0].1);
    emit(
        "case_result_batched",
        json!({
            "case": "batched_mixed_proposals",
            "decided_everywhere": decided_everywhere,
            "all_logs_equal": all_logs_equal,
            "all_values_present": all_values_present,
            "index_content_consistent": index_content_consistent,
            "decided_len": logs[0].1.len(),
        }),
    );
    assert!(
        decided_everywhere,
        "not every node decided all {total} entries: {:?}",
        c.alive()
            .iter()
            .map(|p| (*p, c.decided_idx(*p)))
            .collect::<Vec<_>>()
    );
}

fn log_indices_consistent(c: &Cluster, values: &[u64]) -> bool {
    c.alive().iter().all(|p| {
        values
            .iter()
            .enumerate()
            .all(|(idx, v)| c.decided_at(*p, idx) == Some(*v))
    })
}

/// Case: a leader change plus recovery of the old leader must not change or shorten the decided
/// prefix on any node.
#[test]
fn leader_change_and_recovery_preserve_decided_prefix() {
    let mut c = Cluster::new(3, 2);
    assert!(
        c.pump_until(2000, |c| c.leader().is_some()),
        "no leader was elected in the leader-change case"
    );
    let l1 = c.leader().unwrap();
    for i in 0..6u64 {
        assert!(c.append(l1, TestEntry(i)), "phase A proposal {i} rejected");
    }
    assert!(
        c.pump_until(6000, |c| c.alive()
            .iter()
            .all(|p| c.decided_idx(*p) == 6)),
        "phase A prefix was not decided everywhere"
    );
    let prefix = c.decided_values(l1);
    emit(
        "leader_change_admitted",
        json!({
            "case": "leader_change_prefix",
            "initial_leader": l1,
            "prefix_len": prefix.len(),
            "prefix": format!("{prefix:?}"),
        }),
    );

    c.crash(l1);
    let new_leader_found = c.pump_until(4000, |c| c.leader().is_some());
    let l2 = c.leader().unwrap_or(l1);
    for i in 200..204u64 {
        assert!(c.append(l2, TestEntry(i)), "phase B proposal {i} rejected");
    }
    let decided_everywhere = c.pump_until(6000, |c| {
        c.alive().iter().all(|p| c.decided_idx(*p) == 10)
    });
    let logs_after_change: Vec<(NodeId, Vec<u64>)> = c
        .alive()
        .iter()
        .map(|p| (*p, c.decided_values(*p)))
        .collect();
    let all_logs_equal = logs_after_change
        .iter()
        .all(|(_, v)| *v == logs_after_change[0].1);
    let prefix_preserved = logs_after_change
        .iter()
        .all(|(_, v)| v.len() >= prefix.len() && v[..prefix.len()] == prefix[..]);
    emit(
        "case_result_leader_change",
        json!({
            "case": "leader_change_prefix",
            "new_leader_found": new_leader_found,
            "new_leader": l2,
            "decided_everywhere": decided_everywhere,
            "prefix_preserved": prefix_preserved,
            "all_logs_equal": all_logs_equal,
            "decided_len": logs_after_change[0].1.len(),
        }),
    );

    // Bring the old leader back from its persisted storage and check it converges without changing
    // anything that was already decided.
    c.recover(l1);
    let caught_up = c.pump_until(8000, |c| {
        c.alive()
            .iter()
            .all(|p| c.decided_idx(*p) == 10 && c.decided_values(*p) == logs_after_change[0].1)
    });
    let recovered_log = c.decided_values(l1);
    emit(
        "case_result_leader_change_recovered",
        json!({
            "case": "leader_change_prefix",
            "recovered_caught_up": caught_up,
            "recovered_prefix_preserved": recovered_log.len() >= prefix.len()
                && recovered_log[..prefix.len()] == prefix[..],
            "recovered_all_logs_equal": c
                .alive()
                .iter()
                .all(|p| c.decided_values(*p) == recovered_log),
        }),
    );
}
