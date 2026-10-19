use std::collections::HashMap;

use omnipaxos::{
    ballot_leader_election::Ballot,
    messages::{
        sequence_paxos::{PaxosMessage, PaxosMsg, Prepare},
        Message,
    },
    storage::{Entry, NoSnapshot},
    util::NodeId,
    ClusterConfig, CompactionErr, OmniPaxos, OmniPaxosConfig, ProposeErr, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq)]
struct TestEntry(u64);

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

fn config(pid: NodeId, configuration_id: u32) -> OmniPaxosConfig {
    OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id,
            nodes: vec![1, 2, 3],
            flexible_quorum: None,
        },
        server_config: ServerConfig {
            pid,
            ..Default::default()
        },
    }
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
    ops.get_mut(&1).unwrap().trim(Some(3))
}

fn check_sparse_trim() {
    fill_log_and_trim(&[1, 2, 3]).expect("contiguous-ID control unexpectedly failed");
    let sparse = fill_log_and_trim(&[1, 10, 20]);
    assert!(
        sparse.is_ok(),
        "all configured nodes accepted/decided index 3, but trim failed: {sparse:?}"
    );
}

fn check_reconfigure_epoch() {
    let mut op = config(1, 7)
        .build(MemoryStorage::<TestEntry>::default())
        .unwrap();
    let result = op.reconfigure(
        ClusterConfig {
            configuration_id: 7,
            nodes: vec![1, 2, 3],
            flexible_quorum: None,
        },
        None,
    );
    assert!(
        matches!(result, Err(ProposeErr::ConfigError(..))),
        "reconfigure accepted non-increasing next configuration ID: {result:?}"
    );
}

fn check_ballot_ordering() {
    let first_epoch = Ballot::with(1, 5, 0, 1);
    let second_epoch = Ballot::with(2, 5, 0, 1);
    assert_ne!(first_epoch, second_epoch);
    assert_ne!(
        first_epoch.cmp(&second_epoch),
        std::cmp::Ordering::Equal,
        "Ballot::cmp ignores config_id despite derived equality distinguishing it"
    );
}

fn check_stale_epoch_message() {
    let mut op = config(2, 2)
        .build(MemoryStorage::<TestEntry>::default())
        .unwrap();
    op.try_become_leader();
    assert_eq!(op.get_current_leader(), Some((2, false)));
    let current_promise = op.get_promise();
    assert_eq!(current_promise.config_id, 2);

    let stale_prepare = Prepare {
        n: Ballot::with(1, current_promise.n + 1, 0, 1),
        decided_idx: 0,
        n_accepted: Ballot::default(),
        accepted_idx: 0,
    };
    op.handle_incoming(Message::SequencePaxos(PaxosMessage {
        from: 1,
        to: 2,
        msg: PaxosMsg::Prepare(stale_prepare),
    }));

    assert_eq!(
        op.get_promise(),
        current_promise,
        "a Prepare from the previous (lower) configuration replaced the current epoch's promise"
    );
}

fn check_zero_node_id_validation() {
    let mut cfg = config(1, 1);
    cfg.cluster_config.nodes = vec![1, 0, 2];
    assert!(
        cfg.validate().is_err(),
        "configuration accepted node ID 0, although every server PID must be nonzero"
    );
}

fn check_zero_node_id_does_not_panic() {
    let mut cfg = config(1, 1);
    cfg.cluster_config.nodes = vec![1, 0, 2];
    cfg.server_config.election_tick_timeout = 1;
    cfg.server_config.resend_message_tick_timeout = 1;
    let mut op = cfg.build(MemoryStorage::<TestEntry>::default()).unwrap();
    op.try_become_leader();
    op.tick();
}

fn main() {
    let checks: [(&str, fn()); 6] = [
        ("sparse-id trim", check_sparse_trim),
        ("reconfiguration epoch validation", check_reconfigure_epoch),
        ("Ballot Ord/Eq consistency", check_ballot_ordering),
        ("cross-epoch Prepare rejection", check_stale_epoch_message),
        ("zero node ID validation", check_zero_node_id_validation),
        ("zero node ID runtime safety", check_zero_node_id_does_not_panic),
    ];
    let mut failed = 0;
    for (name, check) in checks {
        let outcome = std::panic::catch_unwind(check);
        match outcome {
            Ok(()) => println!("PASS: {name}"),
            Err(err) => {
                failed += 1;
                let msg = err
                    .downcast_ref::<String>()
                    .map(String::as_str)
                    .or_else(|| err.downcast_ref::<&str>().copied())
                    .unwrap_or("<non-string panic>");
                println!("FAIL: {name}: {msg}");
            }
        }
    }
    if failed != 0 {
        std::process::exit(1);
    }
}
