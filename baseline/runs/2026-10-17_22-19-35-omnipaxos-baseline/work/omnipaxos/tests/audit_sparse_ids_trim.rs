#![cfg(not(feature = "unicache"))]

use std::collections::HashMap;

use omnipaxos::{
    messages::Message,
    storage::{Entry, NoSnapshot},
    util::NodeId,
    ClusterConfig, CompactionErr, OmniPaxos, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq)]
struct TestEntry(u64);

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

fn build_cluster(nodes: &[NodeId]) -> HashMap<NodeId, OmniPaxos<TestEntry, MemoryStorage<TestEntry>>> {
    nodes
        .iter()
        .map(|&pid| {
            let cfg = OmniPaxosConfig {
                cluster_config: ClusterConfig {
                    configuration_id: 1,
                    nodes: nodes.to_vec(),
                    flexible_quorum: None,
                },
                server_config: ServerConfig {
                    pid,
                    ..Default::default()
                },
            };
            (
                pid,
                cfg.build(MemoryStorage::<TestEntry>::default()).unwrap(),
            )
        })
        .collect()
}

fn pump_sequence_messages(
    ops: &mut HashMap<NodeId, OmniPaxos<TestEntry, MemoryStorage<TestEntry>>>,
) {
    for _ in 0..100 {
        let mut messages = Vec::new();
        for op in ops.values_mut() {
            op.take_outgoing_messages(&mut messages);
        }
        if messages.is_empty() {
            break;
        }
        for msg in messages {
            if let Message::SequencePaxos(_) = &msg {
                let to = msg.get_receiver();
                ops.get_mut(&to)
                    .unwrap_or_else(|| panic!("message addressed to unconfigured pid {to}"))
                    .handle_incoming(msg);
            }
        }
    }
}

fn fill_log_and_trim(nodes: &[NodeId]) -> Result<(), CompactionErr> {
    let mut ops = build_cluster(nodes);
    ops.get_mut(&1).unwrap().try_become_leader();
    pump_sequence_messages(&mut ops);
    assert_eq!(
        ops.get(&1).unwrap().get_current_leader(),
        Some((1, true)),
        "node 1 did not reach the accepted-leader phase"
    );

    for value in 1..=3 {
        ops.get_mut(&1)
            .unwrap()
            .append(TestEntry(value))
            .unwrap();
        pump_sequence_messages(&mut ops);
    }
    for pid in nodes {
        assert_eq!(
            ops.get(pid).unwrap().get_decided_idx(),
            3,
            "pid {pid} did not decide the complete prefix"
        );
    }

    // All configured nodes accepted index 3, so this index is safe to trim.
    ops.get_mut(&1).unwrap().trim(Some(3))
}

#[test]
fn trim_works_for_contiguous_node_ids_control() {
    fill_log_and_trim(&[1, 2, 3]).expect("trim should succeed on the contiguous-ID control");
}

#[test]
fn trim_is_not_blocked_by_unconfigured_node_id_slots() {
    let result = fill_log_and_trim(&[1, 10, 20]);
    assert!(
        result.is_ok(),
        "all configured nodes accepted index 3, but trim failed: {result:?}"
    );
}
