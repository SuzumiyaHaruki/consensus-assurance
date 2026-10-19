#![cfg(not(feature = "unicache"))]

use omnipaxos::{
    ballot_leader_election::Ballot,
    messages::{
        sequence_paxos::{AcceptSync, PaxosMessage, PaxosMsg, Prepare},
        Message,
    },
    storage::{Entry, NoSnapshot},
    util::{LogSync, SequenceNumber},
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug)]
struct TestEntry;

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

#[test]
fn stopsign_buffered_before_leader_election_is_forwarded_after_sync() {
    let mut op = OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id: 1,
            nodes: vec![1, 2, 3],
            flexible_quorum: None,
        },
        server_config: ServerConfig {
            pid: 3,
            ..Default::default()
        },
    }
    .build(MemoryStorage::<TestEntry>::default())
    .unwrap();

    // No leader is known, so reconfigure() reports success but buffers the request.
    op.reconfigure(
        ClusterConfig {
            configuration_id: 2,
            nodes: vec![1, 2, 3],
            flexible_quorum: None,
        },
        None,
    )
    .expect("valid reconfiguration was rejected");

    let n = Ballot::with(1, 1, 0, 1);
    op.handle_incoming(Message::SequencePaxos(PaxosMessage {
        from: 1,
        to: 3,
        msg: PaxosMsg::Prepare(Prepare {
            n,
            decided_idx: 0,
            n_accepted: Ballot::default(),
            accepted_idx: 0,
        }),
    }));
    op.handle_incoming(Message::SequencePaxos(PaxosMessage {
        from: 1,
        to: 3,
        msg: PaxosMsg::AcceptSync(AcceptSync {
            n,
            seq_num: SequenceNumber {
                session: 1,
                counter: 1,
            },
            decided_idx: 0,
            log_sync: LogSync {
                decided_snapshot: None,
                suffix: Vec::new(),
                sync_idx: 0,
                stopsign: None,
            },
            #[cfg(feature = "unicache")]
            unicache: <TestEntry as Entry>::UniCache::new(),
        }),
    }));
    assert_eq!(op.get_current_leader(), Some((1, true)));

    let mut outgoing = Vec::new();
    op.take_outgoing_messages(&mut outgoing);
    assert!(
        outgoing.iter().any(|message| matches!(
            message,
            Message::SequencePaxos(PaxosMessage {
                to: 1,
                msg: PaxosMsg::ForwardStopSign(_),
                ..
            })
        )),
        "the pre-election StopSign request was never forwarded to the newly known leader"
    );
}
