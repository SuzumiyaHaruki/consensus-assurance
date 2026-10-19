#![cfg(not(feature = "unicache"))]

use omnipaxos::{
    ballot_leader_election::Ballot,
    messages::{
        sequence_paxos::{AcceptSync, PaxosMessage, PaxosMsg, Prepare},
        Message,
    },
    storage::{Entry, NoSnapshot, Storage, StorageOp},
    util::{LogSync, SequenceNumber},
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq)]
struct TestEntry(u64);

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

#[test]
fn accept_sync_does_not_regress_receiver_decided_index() {
    let entries: Vec<_> = (1..=10).map(TestEntry).collect();
    let mut storage = MemoryStorage::<TestEntry>::default();
    storage
        .write_atomically(vec![
            StorageOp::AppendEntries(entries),
            StorageOp::SetDecidedIndex(10),
        ])
        .unwrap();
    let mut op = OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id: 1,
            nodes: vec![1, 2, 3],
            flexible_quorum: None,
        },
        server_config: ServerConfig {
            pid: 1,
            ..Default::default()
        },
    }
    .build(storage)
    .unwrap();
    assert_eq!(op.get_decided_idx(), 10);

    let n = Ballot::with(1, 1, 0, 2);
    op.handle_incoming(Message::SequencePaxos(PaxosMessage {
        from: 2,
        to: 1,
        msg: PaxosMsg::Prepare(Prepare {
            n,
            decided_idx: 5,
            n_accepted: Ballot::with(1, 1, 0, 2),
            accepted_idx: 10,
        }),
    }));
    op.handle_incoming(Message::SequencePaxos(PaxosMessage {
        from: 2,
        to: 1,
        msg: PaxosMsg::AcceptSync(AcceptSync {
            n,
            seq_num: SequenceNumber {
                session: 1,
                counter: 1,
            },
            decided_idx: 5,
            log_sync: LogSync {
                decided_snapshot: None,
                suffix: Vec::new(),
                sync_idx: 10,
                stopsign: None,
            },
            #[cfg(feature = "unicache")]
            unicache: <TestEntry as Entry>::UniCache::new(),
        }),
    }));

    assert_eq!(
        op.get_decided_idx(),
        10,
        "AcceptSync decreased the receiver's already-decided index"
    );
}
