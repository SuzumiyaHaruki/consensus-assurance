//! Focused probe for two faults the captured suites do not exercise: duplication of
//! replication messages, and replay of a replaced leader's messages after the rest of the
//! cluster has moved to a newer ballot.
//!
//! Lives in the `omnipaxos_runtime` test target because that dependency graph builds
//! offline here; it drives three real `OmniPaxos` instances directly through the public
//! API and never touches the actor layer.

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

/// Transport faults the harness can apply while pumping.
#[derive(Default)]
struct Wire {
    /// Messages whose sender is this pid are diverted into `held` instead of delivered.
    hold_from: Option<u64>,
    /// Diverted messages, kept for replay.
    held: Vec<Message<TestEntry>>,
    /// Messages addressed to this pid are delivered twice.
    duplicate_to: Option<u64>,
    /// The first `AcceptDecide` addressed to this pid is diverted into `captured`.
    capture_to: Option<u64>,
    captured: Option<Message<TestEntry>>,
}

fn deliver(ops: &mut BTreeMap<u64, Op>, from: u64, m: Message<TestEntry>) {
    let to = m.get_receiver();
    if to == from {
        return;
    }
    if let Some(dst) = ops.get_mut(&to) {
        dst.handle_incoming(m);
    }
}

fn pump(ops: &mut BTreeMap<u64, Op>, wire: &mut Wire, rounds: usize) {
    for _ in 0..rounds {
        let pids: Vec<u64> = ops.keys().copied().collect();
        for pid in &pids {
            ops.get_mut(pid).unwrap().tick();
        }
        for pid in &pids {
            let mut buf = Vec::new();
            ops.get_mut(pid).unwrap().take_outgoing_messages(&mut buf);
            for m in buf {
                let from = m.get_sender();
                let to = m.get_receiver();
                if Some(from) == wire.hold_from {
                    wire.held.push(m);
                    continue;
                }
                if Some(to) == wire.capture_to && wire.captured.is_none() {
                    if let Message::SequencePaxos(p) = &m {
                        if matches!(&p.msg, PaxosMsg::AcceptDecide(_)) {
                            wire.captured = Some(m);
                            continue;
                        }
                    }
                }
                let duplicate = Some(to) == wire.duplicate_to;
                let copy = if duplicate { Some(m.clone()) } else { None };
                deliver(ops, from, m);
                if let Some(c) = copy {
                    deliver(ops, from, c);
                }
            }
        }
    }
}

fn replay_held(ops: &mut BTreeMap<u64, Op>, wire: &mut Wire) -> usize {
    let held = std::mem::take(&mut wire.held);
    let count = held.len();
    for m in held {
        let from = m.get_sender();
        deliver(ops, from, m);
    }
    count
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

fn leader_pid(op: &Op) -> String {
    op.get_current_leader()
        .map(|(pid, _)| pid.to_string())
        .unwrap_or_else(|| "none".to_string())
}

fn run_case(mode: &str, duplicate: bool, stale_replay: bool) {
    let nodes = vec![1u64, 2, 3];
    let mut ops: BTreeMap<u64, Op> = nodes
        .iter()
        .map(|pid| (*pid, build(*pid, nodes.clone())))
        .collect();
    let mut wire = Wire::default();

    // Elect node 1 and decide a baseline of three entries everywhere.
    let mut elected = false;
    for _ in 0..200 {
        ops.get_mut(&1).unwrap().try_become_leader();
        pump(&mut ops, &mut wire, 30);
        if let Some((pid, true)) = ops.get(&2).unwrap().get_current_leader() {
            if pid == 1 {
                elected = true;
                break;
            }
        }
    }
    for v in 1..=3u64 {
        ops.get_mut(&1).unwrap().append(TestEntry(v)).unwrap();
    }
    let mut baseline_ok = false;
    for _ in 0..40 {
        pump(&mut ops, &mut wire, 30);
        if ops.values().all(|op| op.get_decided_idx() >= 3) {
            baseline_ok = true;
            break;
        }
    }
    emit(
        "admission",
        &[
            ("mode", q(mode)),
            ("nodes", q("1,2,3")),
            ("follower", n(2)),
            ("leader_elected", if elected { "true".to_string() } else { "false".to_string() }),
            ("baseline_three_decided_everywhere", if baseline_ok { "true".to_string() } else { "false".to_string() }),
            ("duplicate_to_node2", if duplicate { "true".to_string() } else { "false".to_string() }),
            ("stale_replay", if stale_replay { "true".to_string() } else { "false".to_string() }),
        ],
    );
    if !elected || !baseline_ok {
        emit(
            &format!("fault_outcome_{}", mode.to_lowercase()),
            &[("mode", q(mode)), ("stage", q("setup_incomplete"))],
        );
        return;
    }

    let mut replayed = 0usize;
    let mut new_leader = 1u64;
    let mut appended_by_new_leader: Vec<u64> = Vec::new();

    if stale_replay {
        // Cut the leader off from both followers and let them take over. Messages it sends
        // are retained so they can be replayed afterwards.
        wire.hold_from = Some(1);
        let mut takeover = false;
        for _ in 0..40 {
            pump(&mut ops, &mut wire, 30);
            for pid in [2u64, 3] {
                if let Some((leader, true)) = ops.get(&pid).unwrap().get_current_leader() {
                    if leader != 1 {
                        new_leader = leader;
                        takeover = true;
                    }
                }
            }
            if takeover {
                break;
            }
        }
        // The new leader decides two entries while the old leader is cut off.
        for v in [7u64, 8] {
            ops.get_mut(&new_leader).unwrap().append(TestEntry(v)).unwrap();
            appended_by_new_leader.push(v);
        }
        for _ in 0..10 {
            pump(&mut ops, &mut wire, 30);
        }
        // Heal: the old leader is reachable again and its retained messages are replayed.
        wire.hold_from = None;
        replayed = replay_held(&mut ops, &mut wire);
    } else {
        // The new leader is the same node; two more entries advance the log.
        for v in [7u64, 8] {
            ops.get_mut(&1).unwrap().append(TestEntry(v)).unwrap();
            appended_by_new_leader.push(v);
        }
    }

    if duplicate {
        wire.duplicate_to = Some(2);
    }
    for _ in 0..10 {
        pump(&mut ops, &mut wire, 30);
    }

    // A final proposal through whichever node currently leads, then settle.
    let final_leader = ops
        .iter()
        .find_map(|(pid, op)| op.get_current_leader().filter(|(_, a)| *a).map(|(l, _)| if op.get_pid() == l { *pid } else { *pid }))
        .unwrap_or(1);
    let proposer = if stale_replay { new_leader } else { final_leader };
    ops.get_mut(&proposer)
        .unwrap()
        .append(TestEntry(9))
        .unwrap();
    for _ in 0..15 {
        pump(&mut ops, &mut wire, 30);
    }
    wire.duplicate_to = None;

    let (leader_decided, leader_values) = decided_values(ops.get(&1).unwrap());
    let (second_decided, second_values) = decided_values(ops.get(&2).unwrap());
    let (third_decided, third_values) = decided_values(ops.get(&3).unwrap());
    let all_equal = leader_values == second_values && second_values == third_values;
    let expected = [1u64, 2, 3, 7, 8, 9];
    let mut sorted = leader_values.clone();
    sorted.sort_unstable();
    let has_expected = sorted == expected.to_vec();

    emit(
        &format!("fault_outcome_{}", mode.to_lowercase()),
        &[
            ("mode", q(mode)),
            ("nodes", q("1,2,3")),
            ("follower", n(2)),
            ("duplicate_to_node2", if duplicate { "true".to_string() } else { "false".to_string() }),
            ("stale_replay", if stale_replay { "true".to_string() } else { "false".to_string() }),
            ("stale_messages_replayed", n(replayed)),
            ("new_leader_pid", n(new_leader as usize)),
            ("final_proposer_pid", n(proposer as usize)),
            ("leader1_decided_idx", n(leader_decided)),
            ("node2_decided_idx", n(second_decided)),
            ("node3_decided_idx", n(third_decided)),
            ("leader1_decided_values", q(&join(&leader_values))),
            ("node2_decided_values", q(&join(&second_values))),
            ("node3_decided_values", q(&join(&third_values))),
            ("all_three_values_equal", if all_equal { "true".to_string() } else { "false".to_string() }),
            ("expected_entries_all_decided", if has_expected { "true".to_string() } else { "false".to_string() }),
            ("node1_current_leader_pid", q(&leader_pid(ops.get(&1).unwrap()))),
            ("node2_current_leader_pid", q(&leader_pid(ops.get(&2).unwrap()))),
        ],
    );
}

/// Control: no fault, entries decided in order by the original leader.
#[test]
fn case_a_control() {
    run_case("A", false, false);
}

/// Duplication: every message addressed to node 2 is delivered twice.
#[test]
fn case_b_duplicated_delivery() {
    run_case("B", true, false);
}

/// Stale replay: the followers take over while the old leader is cut off, then the old
/// leader's retained messages are replayed to them after the heal.
#[test]
fn case_c_stale_leader_replay() {
    run_case("C", false, true);
}
