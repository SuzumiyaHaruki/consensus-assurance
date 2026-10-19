pub mod utils;

use omnipaxos::{
    ballot_leader_election::Ballot,
    messages::{
        sequence_paxos::{PaxosMessage, PaxosMsg, Promise},
        Message,
    },
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;
use utils::Value;

#[test]
fn zero_flush_timeout_is_rejected_or_flushes_batched_entries() {
    let cfg = OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id: 1,
            nodes: vec![1, 2, 3],
            flexible_quorum: None,
        },
        server_config: ServerConfig {
            pid: 1,
            batch_size: 2,
            flush_batch_tick_timeout: 0,
            election_tick_timeout: 100,
            resend_message_tick_timeout: 100,
            ..Default::default()
        },
    };
    if cfg.validate().is_err() {
        return;
    }

    let mut op = cfg
        .build(MemoryStorage::<Value>::default())
        .expect("validated configuration failed to build");
    op.try_become_leader();
    let n = op.get_promise();
    op.handle_incoming(Message::SequencePaxos(PaxosMessage {
        from: 2,
        to: 1,
        msg: PaxosMsg::Promise(Promise {
            n,
            n_accepted: Ballot::default(),
            decided_idx: 0,
            accepted_idx: 0,
            log_sync: None,
        }),
    }));
    assert_eq!(op.get_current_leader(), Some((1, true)));

    op.append(Value::with_id(1)).unwrap();
    assert_eq!(op.get_batched_len(), 1);
    for _ in 0..20 {
        op.tick();
    }
    assert!(
        op.get_accepted_idx() >= 1,
        "the entry remained forever in the batch with flush_batch_tick_timeout = 0"
    );
}
