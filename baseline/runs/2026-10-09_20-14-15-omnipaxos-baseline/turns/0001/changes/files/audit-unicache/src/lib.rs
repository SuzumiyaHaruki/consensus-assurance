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
    struct Cache(LRUniCache<String,u8>);
    impl UniCache for Cache {
        type T = Item;
        fn new() -> Self { Self(LRUniCache::new(255)) }
        fn try_encode(&mut self, e: &Item) -> MaybeEncoded<String,u8> { self.0.try_encode(&e.0) }
        fn decode(&mut self, e: MaybeEncoded<String,u8>) -> Item { Item(self.0.decode(e)) }
    }
    type Node = OmniPaxos<Item,MemoryStorage<Item>>;
    fn deliver(nodes: &mut [Node]) {
        for _ in 0..100 {
            let mut msgs: Vec<Message<Item>> = vec![];
            for n in nodes.iter_mut() { n.take_outgoing_messages(&mut msgs); }
            if msgs.is_empty() { return; }
            // Move messages without cloning or serialization, isolating cache leadership behavior.
            for m in msgs { nodes[m.get_receiver() as usize - 1].handle_incoming(m); }
        }
        panic!("did not quiesce");
    }
    fn scenario(change_leader: bool) {
        let mut nodes: Vec<Node> = (1..=3).map(|pid|
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
}
