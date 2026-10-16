//! Focused probe for core-crate trimming with sparse (non-contiguous) node ids.
//!
//! This file lives in the `omnipaxos_runtime` test target because that crate's dev
//! dependency graph builds offline in this environment; it exercises the `omnipaxos`
//! crate's public API directly (three real `OmniPaxos` instances driven in one process),
//! and never touches the actor layer.
//!
//! Question: after every configured server has decided the same entry, does
//! `OmniPaxos::trim(None)` advance the compacted index when the configuration's node ids
//! are not contiguous (e.g. {1, 2, 5}), and does the documented repair path
//! (`trim(Some(idx))` with the reported index) advance it instead?

use std::collections::BTreeMap;

use omnipaxos::{
    storage::{Entry, Snapshot},
    ClusterConfig, CompactionErr, OmniPaxos, OmniPaxosConfig, ServerConfig,
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

fn build(pid: u64, nodes: Vec<u64>, preferred: u64) -> Op {
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
        leader_priority: if pid == preferred { 1 } else { 0 },
        ..Default::default()
    };
    OmniPaxosConfig {
        cluster_config,
        server_config,
    }
    .build(MemoryStorage::default())
    .unwrap()
}

/// Advance every instance and deliver all pending messages in-process (lossless).
fn pump(ops: &mut BTreeMap<u64, Op>) {
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
                if to != *pid {
                    if let Some(dst) = ops.get_mut(&to) {
                        dst.handle_incoming(m);
                    }
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

fn trim_result(r: &Result<(), CompactionErr>) -> String {
    match r {
        Ok(()) => "ok".to_string(),
        Err(CompactionErr::NotAllDecided(idx)) => format!("not_all_decided:{}", idx),
        Err(CompactionErr::UndecidedIndex(idx)) => format!("undecided_index:{}", idx),
        Err(CompactionErr::TrimmedIndex(idx)) => format!("trimmed_index:{}", idx),
        Err(CompactionErr::NotCurrentLeader(pid)) => format!("not_current_leader:{}", pid),
    }
}

/// Elect node 1, decide one entry on every server, then probe `trim(None)` and the
/// documented explicit-index repair on the leader.
fn evaluate(mode: &str, node_ids: Vec<u64>) {
    let node_list = node_ids
        .iter()
        .map(|p| p.to_string())
        .collect::<Vec<_>>()
        .join(",");
    let mut ops: BTreeMap<u64, Op> = node_ids
        .iter()
        .map(|pid| (*pid, build(*pid, node_ids.clone(), node_ids[0])))
        .collect();
    let preferred = node_ids[0];
    let peer = node_ids[1];

    let mut leader_pid = 0u64;
    for _ in 0..200 {
        ops.get_mut(&preferred).unwrap().try_become_leader();
        pump(&mut ops);
        if let Some((pid, true)) = ops.get(&peer).unwrap().get_current_leader() {
            if pid == preferred {
                leader_pid = pid;
                break;
            }
        }
    }

    emit(
        "admission",
        &[
            ("mode", q(mode)),
            ("nodes", q(&node_list)),
            ("leader", n(leader_pid as usize)),
        ],
    );
    if leader_pid != preferred {
        emit(
            &format!("trim_outcome_{}", mode.to_lowercase()),
            &[
                ("mode", q(mode)),
                ("nodes", q(&node_list)),
                ("leader", n(0)),
                ("stage", q("no_leader")),
            ],
        );
        return;
    }

    // One entry appended on the leader, propagated to every server.
    ops.get_mut(&preferred).unwrap().append(TestEntry(7)).unwrap();
    let mut all_decided = false;
    for _ in 0..60 {
        pump(&mut ops);
        if node_ids
            .iter()
            .all(|p| ops.get(p).unwrap().get_decided_idx() >= 1)
        {
            all_decided = true;
            break;
        }
    }
    let decided_before = ops.get(&preferred).unwrap().get_decided_idx();
    let compacted_before = ops.get(&preferred).unwrap().get_compacted_idx();

    let none_result = ops.get_mut(&preferred).unwrap().trim(None);
    let compacted_after_none = ops.get(&preferred).unwrap().get_compacted_idx();
    let none_advanced = compacted_after_none > compacted_before;

    let explicit_result = ops.get_mut(&preferred).unwrap().trim(Some(decided_before));
    let compacted_after_explicit = ops.get(&preferred).unwrap().get_compacted_idx();
    let explicit_advanced = compacted_after_explicit > compacted_after_none;

    emit(
        &format!("trim_outcome_{}", mode.to_lowercase()),
        &[
            ("mode", q(mode)),
            ("nodes", q(&node_list)),
            ("leader", n(leader_pid as usize)),
            ("all_servers_decided", if all_decided { "true".to_string() } else { "false".to_string() }),
            ("decided_idx_before_trim", n(decided_before)),
            ("compacted_idx_before_trim", n(compacted_before)),
            ("trim_none_result", q(&trim_result(&none_result))),
            ("compacted_idx_after_trim_none", n(compacted_after_none)),
            ("trim_none_advanced_compaction", if none_advanced { "true".to_string() } else { "false".to_string() }),
            (
                "trim_explicit_result",
                q(&trim_result(&explicit_result)),
            ),
            (
                "compacted_idx_after_trim_explicit",
                n(compacted_after_explicit),
            ),
            (
                "trim_explicit_advanced_compaction",
                if explicit_advanced { "true".to_string() } else { "false".to_string() },
            ),
        ],
    );
}

/// Control: contiguous node ids {1,2,3}, all servers decided one entry.
#[test]
fn case_a_contiguous_node_ids() {
    evaluate("A", vec![1, 2, 3]);
}

/// Treatment: the same three-server shape with sparse ids {1,2,5}.
#[test]
fn case_b_sparse_node_ids() {
    evaluate("B", vec![1, 2, 5]);
}

/// Generalised trigger, ids {2,3,4}: the largest id exceeds the node count and id 1 is not
/// in the configuration at all.
#[test]
fn case_c_ids_2_3_4() {
    evaluate("C", vec![2, 3, 4]);
}

/// Generalised trigger, two-node cluster {1,3}: the slot for id 2 is never written.
#[test]
fn case_d_ids_1_3() {
    evaluate("D", vec![1, 3]);
}
