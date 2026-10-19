pub mod utils;

use omnipaxos::{
    ballot_leader_election::Ballot,
    messages::{
        sequence_paxos::{AcceptSync, PaxosMessage, PaxosMsg, Prepare, Promise},
        Message,
    },
    storage::{Snapshot, Storage, StorageOp},
    util::{LogEntry, LogSync, SequenceNumber},
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;
#[cfg(feature = "unicache")]
use omnipaxos::unicache::UniCache;
use utils::{Value, ValueSnapshot};

fn entry(id: u64) -> Value {
    Value::with_id(id)
}

#[test]
fn delta_snapshot_sync_discards_receiver_suffix_after_common_prefix() {
    let mut storage = MemoryStorage::<Value>::default();
    storage
        .write_atomically(vec![
            StorageOp::AppendEntries(vec![entry(1), entry(2), entry(3)]),
            StorageOp::SetDecidedIndex(3),
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

    // Receiver has decided [1,2,3], then compacts [1,2] into a snapshot.
    op.snapshot(Some(2), true).unwrap();

    // Make pid 1 an accepted leader so it locally accepts an invalid suffix
    // [6,7]. This models the disconnected old leader.
    op.try_become_leader();
    let old_ballot = op.get_promise();
    op.handle_incoming(Message::SequencePaxos(PaxosMessage {
        from: 2,
        to: 1,
        msg: PaxosMsg::Promise(Promise {
            n: old_ballot,
            n_accepted: Ballot::default(),
            decided_idx: 0,
            accepted_idx: 0,
            log_sync: None,
        }),
    }));
    assert_eq!(op.get_current_leader(), Some((1, true)));
    op.append(entry(6)).unwrap();
    op.append(entry(7)).unwrap();
    assert_eq!(op.get_accepted_idx(), 5);
    assert_eq!(op.get_decided_idx(), 3);

    // A new leader knows the correct prefix [1,2,3,4,5] (decided through 5)
    // and has accepted [10,11,12]. Its snapshot update for this follower is
    // only a delta for [4,5]; the common prefix ends at index 3.
    let new_ballot = Ballot::with(1, old_ballot.n + 1, 0, 3);
    op.handle_incoming(Message::SequencePaxos(PaxosMessage {
        from: 3,
        to: 1,
        msg: PaxosMsg::Prepare(Prepare {
            n: new_ballot,
            decided_idx: 5,
            n_accepted: Ballot::with(1, 1, 0, 2),
            accepted_idx: 5,
        }),
    }));
    op.handle_incoming(Message::SequencePaxos(PaxosMessage {
        from: 3,
        to: 1,
        msg: PaxosMsg::AcceptSync(AcceptSync {
            n: new_ballot,
            seq_num: SequenceNumber {
                session: 1,
                counter: 1,
            },
            decided_idx: 5,
            log_sync: LogSync {
                decided_snapshot: Some(omnipaxos::storage::SnapshotType::Delta(
                    ValueSnapshot::create(&[entry(4), entry(5)]),
                )),
                suffix: vec![entry(10), entry(11), entry(12)],
                sync_idx: 2,
                stopsign: None,
            },
            #[cfg(feature = "unicache")]
            unicache: <Value as omnipaxos::storage::Entry>::UniCache::new(),
        }),
    }));

    let snapshot = match op.read(0).expect("no compacted entry at index 0") {
        LogEntry::Snapshotted(snapshot) => snapshot.snapshot,
        other => panic!("expected snapshot, got {other:?}"),
    };
    assert_eq!(
        snapshot.snapshotted,
        vec![entry(1), entry(2), entry(3), entry(4), entry(5)],
        "snapshot retained the receiver's invalid [6,7] suffix instead of \
         representing only the common prefix plus the leader's delta"
    );
}
