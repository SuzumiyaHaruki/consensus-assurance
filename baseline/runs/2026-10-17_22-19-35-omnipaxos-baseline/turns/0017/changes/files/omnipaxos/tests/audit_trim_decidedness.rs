#![cfg(not(feature = "unicache"))]

use std::collections::HashMap;

use omnipaxos::{
    messages::{sequence_paxos::PaxosMsg, Message},
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

fn build(pid: NodeId) -> OmniPaxos<TestEntry, MemoryStorage<TestEntry>> {
    OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id: 1,
            nodes: vec![1, 2, 3],
            flexible_quorum: None,
        },
        server_config: ServerConfig {
            pid,
            ..Default::default()
        },
    }
    .build(MemoryStorage::default())
    .unwrap()
}

fn pump_without_deciding_pid3(ops: &mut HashMap<NodeId, OmniPaxos<TestEntry, MemoryStorage<TestEntry>>>) {
    for _ in 0..100 {
        let mut messages = Vec::new();
        for op in ops.values_mut() {
            op.take_outgoing_messages(&mut messages);
        }
        if messages.is_empty() {
            return;
        }
        for msg in messages {
            if matches!(
                &msg,
                Message::SequencePaxos(message)
                    if message.to == 3 && matches!(message.msg, PaxosMsg::Decide(_))
            ) {
                continue;
            }
            if matches!(&msg, Message::SequencePaxos(_)) {
                ops.get_mut(&msg.get_receiver())
                    .unwrap()
                    .handle_incoming(msg);
            }
        }
    }
}

#[test]
fn trim_rejects_prefix_not_decided_by_every_node() {
    let mut ops: HashMap<_, _> = (1..=3).map(|pid| (pid, build(pid))).collect();
    ops.get_mut(&1).unwrap().try_become_leader();
    pump_without_deciding_pid3(&mut ops);

    ops.get_mut(&1).unwrap().append(TestEntry(1)).unwrap();
    pump_without_deciding_pid3(&mut ops);

    assert_eq!(ops[&1].get_decided_idx(), 1);
    assert_eq!(ops[&3].get_accepted_idx(), 1);
    assert_eq!(ops[&3].get_decided_idx(), 0);

    let result = ops.get_mut(&1).unwrap().trim(Some(1));
    assert!(
        matches!(result, Err(CompactionErr::NotAllDecided(_))),
        "trim accepted an index that pid 3 had not decided: {result:?}"
    );
}
