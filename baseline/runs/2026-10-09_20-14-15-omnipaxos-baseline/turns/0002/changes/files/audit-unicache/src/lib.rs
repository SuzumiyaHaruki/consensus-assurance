#[cfg(test)]
mod tests {
    use omnipaxos::unicache::{lru_cache::LRUniCache, FieldCache};
    #[test]
    fn lfu_cache_bincode_roundtrip_control() {
        use omnipaxos::unicache::lfu_cache::LFUniCache;
        let mut cache = LFUniCache::<String,u8>::new(3);
        cache.try_encode(&"A".to_owned());
        let serialized = bincode::serialize(&cache.clone()).unwrap();
        let mut received: LFUniCache<String,u8> = bincode::deserialize(&serialized).unwrap();
        assert_eq!(received.decode(cache.try_encode(&"A".to_owned())), "A");
    }

    #[test]
    fn lru_cache_bincode_roundtrip() {
        let mut cache = LRUniCache::<String,u8>::new(3);
        cache.try_encode(&"A".to_owned());
        // AcceptSync carries the result of cloning the leader's encoder cache.
        let follower_cache = cache.clone();
        let serialized = bincode::serialize(&follower_cache).unwrap();
        println!("serialized valid LRU follower cache into {} bytes", serialized.len());
        let _: LRUniCache<String,u8> = bincode::deserialize(&serialized).unwrap();
    }
}

#[cfg(test)]
mod leadership {
    use omnipaxos::{OmniPaxos, ClusterConfig, ServerConfig, storage::{Entry, NoSnapshot}, unicache::{UniCache, FieldCache, MaybeEncoded, lru_cache::LRUniCache}, messages::Message};
    use omnipaxos_storage::memory_storage::MemoryStorage;
    use serde::{Serialize, Deserialize};
    #[derive(Clone, Debug, Serialize, Deserialize)]
    struct Item<const CAP: usize>(String);
    impl<const CAP: usize> Entry for Item<CAP> {
        type Snapshot = NoSnapshot;
        type Encoded = u8;
        type Encodable = String;
        type NotEncodable = ();
        type EncodeResult = MaybeEncoded<String,u8>;
        type UniCache = Cache<CAP>;
    }
    #[derive(Clone, Debug, Serialize, Deserialize)]
    struct Cache<const CAP: usize>(LRUniCache<String,u8>);
    impl<const CAP: usize> UniCache for Cache<CAP> {
        type T = Item<CAP>;
        fn new() -> Self { Self(LRUniCache::new(CAP)) }
        fn try_encode(&mut self, e: &Item<CAP>) -> MaybeEncoded<String,u8> { self.0.try_encode(&e.0) }
        fn decode(&mut self, e: MaybeEncoded<String,u8>) -> Item<CAP> { Item(self.0.decode(e)) }
    }
    type Node<const CAP: usize> = OmniPaxos<Item<CAP>,MemoryStorage<Item<CAP>>>;
    fn deliver<const CAP: usize>(nodes: &mut [Node<CAP>]) {
        for _ in 0..100 {
            let mut msgs: Vec<Message<Item<CAP>>> = vec![];
            for n in nodes.iter_mut() { n.take_outgoing_messages(&mut msgs); }
            if msgs.is_empty() { return; }
            // Move messages without cloning or serialization, isolating cache leadership behavior.
            for m in msgs { nodes[m.get_receiver() as usize - 1].handle_incoming(m); }
        }
        panic!("did not quiesce");
    }
    fn scenario(change_leader: bool) {
        let mut nodes: Vec<Node<255>> = (1..=3).map(|pid|
            ClusterConfig { configuration_id: 1, nodes: vec![1,2,3], flexible_quorum: None }
            .build_for_server(ServerConfig {pid, ..Default::default()}, MemoryStorage::default()).unwrap()
        ).collect();
        nodes[0].try_become_leader();
        deliver(&mut nodes);
        for i in 0..255 { nodes[0].append(Item(format!("key-{i}"))).unwrap(); deliver(&mut nodes); }
        assert!(nodes.iter().all(|n| n.get_decided_idx() == 255));
        let leader = if change_leader {
            nodes[1].try_become_leader();
            deliver(&mut nodes);
            1
        } else { 0 };
        println!("255 distinct values decided; leader now {}; appending another distinct value", leader + 1);
        nodes[leader].append(Item("next-value".into())).unwrap();
        deliver(&mut nodes);
        assert!(nodes.iter().all(|n| n.get_decided_idx() == 256));
    }
    #[test]
    fn new_leader_lru_encoding_overflow() { scenario(true); }
    #[test]
    fn unchanged_leader_full_lru_control() { scenario(false); }

    fn small_cache_scenario(change_leader: bool) {
        let mut nodes: Vec<Node<3>> = (1..=3).map(|pid|
            ClusterConfig { configuration_id: 1, nodes: vec![1,2,3], flexible_quorum: None }
            .build_for_server(ServerConfig {pid, ..Default::default()}, MemoryStorage::default()).unwrap()
        ).collect();
        nodes[0].try_become_leader();
        deliver(&mut nodes);
        for value in ["A", "B", "C"] {
            nodes[0].append(Item(value.into())).unwrap();
            deliver(&mut nodes);
        }
        let leader = if change_leader {
            nodes[1].try_become_leader();
            deliver(&mut nodes);
            1
        } else { 0 };
        for value in ["D", "E", "F", "G", "G"] {
            println!("leader {}, capacity 3, append {value}", leader + 1);
            nodes[leader].append(Item(value.into())).unwrap();
            deliver(&mut nodes);
        }
        assert!(nodes.iter().all(|n| n.get_decided_idx() == 8));
        for n in nodes {
            match n.read(7).unwrap() {
                omnipaxos::util::LogEntry::Decided(v) => assert_eq!(v.0, "G"),
                e => panic!("unexpected final entry {e:?}"),
            }
        }
    }
    fn batched_sync_scenario(resync: bool) {
        let mut nodes: Vec<Node<3>> = (1..=3).map(|pid|
            ClusterConfig { configuration_id: 1, nodes: vec![1,2,3], flexible_quorum: None }
            .build_for_server(ServerConfig {pid, batch_size: 2, ..Default::default()}, MemoryStorage::default()).unwrap()
        ).collect();
        nodes[0].try_become_leader();
        deliver(&mut nodes);
        nodes[0].append(Item("A".into())).unwrap();
        assert_eq!(nodes[0].get_accepted_idx(), 0);
        assert_eq!(nodes[0].get_batched_len(), 1);
        if resync { nodes[2].reconnected(1); deliver(&mut nodes); }
        nodes[0].append(Item("A".into())).unwrap();
        deliver(&mut nodes);
        nodes[0].append(Item("B".into())).unwrap();
        nodes[0].append(Item("B".into())).unwrap();
        deliver(&mut nodes);
        assert!(nodes.iter().all(|n| n.get_decided_idx() == 4));
        for n in nodes {
            let entries: Vec<_> = n.read_decided_suffix(0).unwrap().into_iter().map(|e| match e {
                omnipaxos::util::LogEntry::Decided(v) => v.0,
                e => panic!("unexpected entry {e:?}"),
            }).collect();
            println!("batching: node {} decided {:?}", n.get_pid(), entries);
            assert_eq!(entries, vec!["A", "A", "B", "B"]);
        }
    }
    #[test]
    fn sync_copies_cache_ahead_of_batched_log() { batched_sync_scenario(true); }
    #[test]
    fn batching_without_resync_control() { batched_sync_scenario(false); }
    #[test]
    fn promoted_lru_encoder_outgrows_decoder() { small_cache_scenario(true); }
    #[test]
    fn unchanged_leader_small_lru_control() { small_cache_scenario(false); }
}

#[cfg(test)]
mod lfu_sync {
    use omnipaxos::{OmniPaxos, ClusterConfig, ServerConfig, storage::{Entry, NoSnapshot}, unicache::{UniCache, FieldCache, MaybeEncoded, lfu_cache::LFUniCache}, messages::Message, util::LogEntry};
    use omnipaxos_storage::memory_storage::MemoryStorage;
    use serde::{Serialize, Deserialize};
    #[derive(Clone, Debug, Serialize, Deserialize)]
    struct Item(String);
    impl Entry for Item {
        type Snapshot = NoSnapshot;
        type Encoded = u8;
        type Encodable = String;
        type NotEncodable = ();
        type EncodeResult = MaybeEncoded<String,u8>;
        type UniCache = Cache;
    }
    #[derive(Clone, Debug, Serialize, Deserialize)]
    struct Cache(LFUniCache<String,u8>);
    impl UniCache for Cache {
        type T = Item;
        fn new() -> Self { Self(LFUniCache::new(2)) }
        fn try_encode(&mut self, e: &Item) -> MaybeEncoded<String,u8> { self.0.try_encode(&e.0) }
        fn decode(&mut self, e: MaybeEncoded<String,u8>) -> Item { Item(self.0.decode(e)) }
    }
    type Node = OmniPaxos<Item,MemoryStorage<Item>>;
    fn deliver(nodes: &mut [Node]) {
        for _ in 0..100 {
            let mut msgs: Vec<Message<Item>> = vec![];
            for n in nodes.iter_mut() { n.take_outgoing_messages(&mut msgs); }
            if msgs.is_empty() { return; }
            for m in msgs {
                println!("deliver {:?}", m);
                nodes[m.get_receiver() as usize - 1].handle_incoming(m);
            }
        }
        panic!("did not quiesce");
    }
    fn scenario(resync: bool) {
        let mut nodes: Vec<Node> = (1..=3).map(|pid|
            ClusterConfig { configuration_id: 1, nodes: vec![1,2,3], flexible_quorum: None }
            .build_for_server(ServerConfig {pid, ..Default::default()}, MemoryStorage::default()).unwrap()
        ).collect();
        nodes[0].try_become_leader();
        deliver(&mut nodes);
        // A is much more frequent than B at the leader and both followers.
        for _ in 0..10 { nodes[0].append(Item("A".into())).unwrap(); deliver(&mut nodes); }
        nodes[0].append(Item("B".into())).unwrap();
        deliver(&mut nodes);
        if resync {
            // A transport reconnect uses the ordinary same-leader sync path.
            nodes[2].reconnected(1);
            deliver(&mut nodes);
        }
        // In the reset clone, this makes B more frequent than A; at the leader A still wins.
        // The subsequent C evicts different encodings, regardless of HashMap iteration order.
        for value in ["B", "C", "C"] {
            nodes[0].append(Item(value.into())).unwrap();
            deliver(&mut nodes);
        }
        assert!(nodes.iter().all(|n| n.get_decided_idx() == 14));
        for n in nodes {
            let entry = n.read(13).unwrap();
            println!("node {} decided entry at index 13: {:?}", n.get_pid(), entry);
            match entry {
                LogEntry::Decided(v) => assert_eq!(v.0, "C", "each replica must decode the leader's C"),
                e => panic!("unexpected entry {e:?}"),
            }
        }
    }
    #[test]
    fn lfu_resync_loses_frequency_metadata() { scenario(true); }
    #[test]
    fn lfu_without_resync_control() { scenario(false); }
}
