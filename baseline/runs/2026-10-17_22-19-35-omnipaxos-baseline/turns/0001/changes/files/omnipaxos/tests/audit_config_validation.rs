use omnipaxos::{
    ballot_leader_election::Ballot,
    messages::{
        sequence_paxos::{PaxosMessage, PaxosMsg, Prepare},
        Message,
    },
    storage::{Entry, NoSnapshot},
    ClusterConfig, OmniPaxosConfig, ProposeErr, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq)]
struct TestEntry(u64);

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

fn config(pid: u64, configuration_id: u32) -> OmniPaxosConfig {
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

#[test]
fn reconfigure_rejects_non_increasing_configuration_id() {
    let mut op = config(1, 7)
        .build(MemoryStorage::<TestEntry>::default())
        .unwrap();

    // ClusterConfig's own documentation requires the next configuration ID to be
    // greater than the current one. Reconfigure documents that it rejects invalid
    // configurations.
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
        "reconfigure accepted a next configuration with the same ID as the current one: {result:?}"
    );
}

#[test]
fn ballot_ordering_is_consistent_with_equality() {
    let query = Ballot::with(1, 5, 0, 1);
    let other_config = Ballot::with(2, 5, 0, 1);

    assert_ne!(query, other_config);
    assert_ne!(
        query.cmp(&other_config),
        std::cmp::Ordering::Equal,
        "Ballot::cmp ignores config_id even though derived PartialEq distinguishes it; \
         this violates Ord's requirement that cmp(a, b) == Equal exactly when a == b"
    );
}

#[test]
fn stale_configuration_prepare_is_rejected() {
    let mut op = config(2, 2)
        .build(MemoryStorage::<TestEntry>::default())
        .unwrap();
    op.try_become_leader();
    let current_promise = op.get_promise();
    assert_eq!(current_promise.config_id, 2);

    op.handle_incoming(Message::SequencePaxos(PaxosMessage {
        from: 1,
        to: 2,
        msg: PaxosMsg::Prepare(Prepare {
            n: Ballot::with(1, current_promise.n + 1, 0, 1),
            decided_idx: 0,
            n_accepted: Ballot::default(),
            accepted_idx: 0,
        }),
    }));

    assert_eq!(
        op.get_promise(),
        current_promise,
        "a Prepare from the previous configuration replaced the current epoch's promise"
    );
}
