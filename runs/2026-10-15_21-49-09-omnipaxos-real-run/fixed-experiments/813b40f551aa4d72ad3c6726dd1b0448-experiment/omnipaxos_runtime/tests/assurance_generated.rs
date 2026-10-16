//! Focused probe for the core crate's recovery path under out-of-order delivery.
//!
//! This file lives in the `omnipaxos_runtime` test target because that dependency graph
//! builds offline here; it drives three real `OmniPaxos` instances directly through the
//! public API and never touches the actor layer.
//!
//! Question: when one follower misses an `AcceptDecide` and then receives a *later*
//! `AcceptDecide` first (a sequence break, which triggers the Recover path), and the
//! held-back older message is delivered afterwards, does that follower end up with the
//! same decided values as the leader and keep making progress?

use std::collections::BTreeMap;

use omnipaxos::{
    messages::{sequence_paxos::PaxosMsg, Message},
    storage::{Entry, Snapshot},
    util::LogEntry,
    ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig,
};
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

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

type Op = OmniPaxos<TestEntry, MemoryStorage<TestEntry>>;

fn build(pid: u64, nodes: Vec<u64>) -> Op {
    let cluster_config = ClusterConfig {
        configuration_id: 1,
        nodes,
        flexible_quorum: None,
    };
    #[allow(clippy::needless_update)]
    let server_config = ServerConfig {
        pid,
        election_tick_timeout: 3,
        resend_message_tick_timeout: 5,
        buffer_size: 1024,
        batch_size: 1,
        flush_batch_tick_timeout: 100,
        leader_priority: if pid == 1 { 1 } else { 0 },
        ..Default::default()
    };
    OmniPaxosConfig {
        cluster_config,
        server_config,
    }
    .build(MemoryStorage::default())
    .unwrap()
}

/// Advance every instance and deliver all pending messages in-process. When `capture` is
/// `Some(pid)`, the first `AcceptDecide` addressed to `pid` is removed from the flow and
/// stored in `held` instead of being delivered, so it can be delivered later.
fn pump(
    ops: &mut BTreeMap<u64, Op>,
    capture: Option<u64>,
    held: &mut Option<Message<TestEntry>>,
) {
    for _ in 0..30 {
        let pids: Vec<u64> = ops.keys().copied().collect();
        for pid in &pids {
            ops.get_mut(pid).unwrap().tick();
        }
        for pid in &pids {
            let mut buf = Vec::new();
            ops.get_mut(pid).unwrap().take_outgoing_messages(&mut buf);
            for m in buf {
                let to = m.get_receiver();
                if to == *pid {
                    continue;
                }
                if Some(to) == capture && held.is_none() {
                    if let Message::SequencePaxos(p) = &m {
                        if matches!(&p.msg, PaxosMsg::AcceptDecide(_)) {
                            *held = Some(m);
                            continue;
                        }
                    }
                }
                if let Some(dst) = ops.get_mut(&to) {
                    dst.handle_incoming(m);
                }
            }
        }
    }
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

fn n(v: usize) -> String {
    v.to_string()
}

fn decided_values(op: &Op) -> (usize, Vec<u64>) {
    let decided_idx = op.get_decided_idx();
    let values = op
        .read_decided_suffix(0)
        .map(|entries| {
            entries
                .into_iter()
                .filter_map(|e| match e {
                    LogEntry::Decided(TestEntry(v)) => Some(v),
                    _ => None,
                })
                .collect::<Vec<u64>>()
        })
        .unwrap_or_default();
    (decided_idx, values)
}

fn join(values: &[u64]) -> String {
    values
        .iter()
        .map(|v| v.to_string())
        .collect::<Vec<_>>()
        .join(",")
}

fn elect_node_1(ops: &mut BTreeMap<u64, Op>, held: &mut Option<Message<TestEntry>>) -> bool {
    for _ in 0..200 {
        ops.get_mut(&1).unwrap().try_become_leader();
        pump(ops, None, held);
        if let Some((pid, true)) = ops.get(&2).unwrap().get_current_leader() {
            if pid == 1 {
                return true;
            }
        }
    }
    false
}

/// Both cases append entries 1..=6 on node 1 with node 2 as the follower under
/// observation. Case A delivers everything in order; case B holds back the
/// `AcceptDecide` for entry 4, lets the one for entry 5 arrive first, and then delivers
/// the held message.
#[test]
fn case_a_in_order_delivery() {
    run_case("A", false);
}

#[test]
fn case_b_reordered_delivery() {
    run_case("B", true);
}

fn run_case(mode: &str, reorder: bool) {
    let nodes = vec![1u64, 2, 3];
    let mut ops: BTreeMap<u64, Op> = nodes
        .iter()
        .map(|pid| (*pid, build(*pid, nodes.clone())))
        .collect();
    let mut held: Option<Message<TestEntry>> = None;

    let elected = elect_node_1(&mut ops, &mut held);
    emit(
        "admission",
        &[
            ("mode", q(mode)),
            ("nodes", q("1,2,3")),
            ("follower", n(2)),
            ("leader_elected", if elected { "true".to_string() } else { "false".to_string() }),
        ],
    );
    if !elected {
        emit(
            &format!("reorder_outcome_{}", mode.to_lowercase()),
            &[
                ("mode", q(mode)),
                ("stage", q("no_leader")),
            ],
        );
        return;
    }

    // Baseline: entries 1..=3 decided everywhere.
    for v in 1..=3u64 {
        ops.get_mut(&1).unwrap().append(TestEntry(v)).unwrap();
    }
    let mut baseline_ok = false;
    for _ in 0..40 {
        pump(&mut ops, None, &mut held);
        if ops.values().all(|op| op.get_decided_idx() >= 3) {
            baseline_ok = true;
            break;
        }
    }

    // Entry 4, then entry 5. In the reorder case the AcceptDecide carrying entry 4 is
    // captured, so node 2 sees the one for entry 5 as a sequence break.
    ops.get_mut(&1).unwrap().append(TestEntry(4)).unwrap();
    if reorder {
        pump(&mut ops, Some(2), &mut held);
    } else {
        pump(&mut ops, None, &mut held);
    }
    let captured = held.is_some();
    ops.get_mut(&1).unwrap().append(TestEntry(5)).unwrap();
    pump(&mut ops, None, &mut held);

    // Deliver the held-back older message (reorder case only).
    let delivered_late = if let Some(m) = held.take() {
        ops.get_mut(&2).unwrap().handle_incoming(m);
        true
    } else {
        false
    };
    pump(&mut ops, None, &mut held);

    // Entry 6 and enough pumping for the Recover path and any resends to settle.
    ops.get_mut(&1).unwrap().append(TestEntry(6)).unwrap();
    for _ in 0..10 {
        pump(&mut ops, None, &mut held);
    }

    let (leader_decided, leader_values) = decided_values(ops.get(&1).unwrap());
    let (follower_decided, follower_values) = decided_values(ops.get(&2).unwrap());
    let (third_decided, third_values) = decided_values(ops.get(&3).unwrap());
    let same_values = follower_values == leader_values;
    let all_six = leader_values.len() >= 6 && follower_values.len() >= 6;

    emit(
        &format!("reorder_outcome_{}", mode.to_lowercase()),
        &[
            ("mode", q(mode)),
            ("nodes", q("1,2,3")),
            ("follower", n(2)),
            ("reorder", if reorder { "true".to_string() } else { "false".to_string() }),
            ("baseline_three_decided_everywhere", if baseline_ok { "true".to_string() } else { "false".to_string() }),
            ("acceptdecide_captured", if captured { "true".to_string() } else { "false".to_string() }),
            ("held_message_delivered_late", if delivered_late { "true".to_string() } else { "false".to_string() }),
            ("leader_decided_idx", n(leader_decided)),
            ("follower_decided_idx", n(follower_decided)),
            ("third_node_decided_idx", n(third_decided)),
            ("leader_decided_values", q(&join(&leader_values))),
            ("follower_decided_values", q(&join(&follower_values))),
            ("third_node_decided_values", q(&join(&third_values))),
            ("follower_values_equal_leader", if same_values { "true".to_string() } else { "false".to_string() }),
            ("all_six_entries_decided_on_both", if all_six { "true".to_string() } else { "false".to_string() }),
        ],
    );
}
