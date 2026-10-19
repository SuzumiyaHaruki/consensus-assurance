#![cfg(feature = "unicache")]

use std::collections::HashMap;

use omnipaxos::{
    messages::Message,
    storage::{Entry, NoSnapshot},
    unicache::{lfu_cache::LFUniCache, FieldCache, MaybeEncoded, UniCache},
    util::NodeId,
    ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::memory_storage::MemoryStorage;

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
struct TestEntry {
    id: u64,
    key: String,
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
struct TestKeyCache {
    cache: LFUniCache<String, u64>,
}

impl UniCache for TestKeyCache {
    type T = TestEntry;

    fn new() -> Self {
        Self {
            cache: LFUniCache::new(2),
        }
    }

    fn try_encode(
        &mut self,
        entry: &Self::T,
    ) -> <Self::T as Entry>::EncodeResult {
        (entry.id, self.cache.try_encode(&entry.key))
    }

    fn decode(&mut self, (id, key): <Self::T as Entry>::EncodeResult) -> Self::T {
        TestEntry {
            id,
            key: self.cache.decode(key),
        }
    }
}

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
    type Encoded = (String,);
    type Encodable = (String,);
    type NotEncodable = (u64,);
    type EncodeResult = (u64, MaybeEncoded<String, u64>);
    type UniCache = TestKeyCache;
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

fn pump(ops: &mut HashMap<NodeId, OmniPaxos<TestEntry, MemoryStorage<TestEntry>>>) {
    for _ in 0..100 {
        let mut messages = Vec::new();
        for op in ops.values_mut() {
            op.take_outgoing_messages(&mut messages);
        }
        if messages.is_empty() {
            return;
        }
        for msg in messages {
            if matches!(&msg, Message::SequencePaxos(_)) {
                ops.get_mut(&msg.get_receiver())
                    .unwrap()
                    .handle_incoming(msg);
            }
        }
    }
}

fn entry(id: u64, key: &str) -> TestEntry {
    TestEntry {
        id,
        key: key.to_string(),
    }
}

#[test]
fn follower_keeps_leader_values_after_lfu_cache_resync() {
    let mut ops: HashMap<_, _> = (1..=3).map(|pid| (pid, build(pid))).collect();
    ops.get_mut(&1).unwrap().try_become_leader();
    pump(&mut ops);

    for (id, key) in [(1, "A"), (2, "B"), (3, "A"), (4, "A")] {
        ops.get_mut(&1).unwrap().append(entry(id, key)).unwrap();
        pump(&mut ops);
    }

    // Replace follower 3's decoder with a clone of the now non-empty LFU cache.
    ops.get_mut(&3).unwrap().reconnected(1);
    pump(&mut ops);

    for (id, key) in [(5, "C"), (6, "D"), (7, "A")] {
        ops.get_mut(&1).unwrap().append(entry(id, key)).unwrap();
        pump(&mut ops);
    }

    let leader_entries = ops[&1]
        .read_decided_suffix(0)
        .expect("leader has no decided entries");
    let follower_entries = ops[&3]
        .read_decided_suffix(0)
        .expect("follower has no decided entries");
    assert_eq!(
        follower_entries, leader_entries,
        "follower decoded a different value after LFU cache resynchronization"
    );
}
