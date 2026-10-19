#![cfg(all(feature = "serde", feature = "unicache"))]

use omnipaxos::unicache::{lru_cache::LRUniCache, FieldCache};

#[test]
fn serialized_lru_cache_remains_usable_after_deserialization() {
    let mut leader = LRUniCache::<String, u64>::new(4);
    for value in ["A", "B"] {
        let _ = leader.try_encode(&value.to_string());
    }

    let transmitted = leader.clone();
    let bytes = serde_json::to_vec(&transmitted).unwrap();
    let mut follower: LRUniCache<String, u64> = serde_json::from_slice(&bytes).unwrap();

    for value in ["C", "D", "A"] {
        let value = value.to_string();
        let encoded = leader.try_encode(&value);
        assert_eq!(
            follower.decode(encoded),
            value,
            "deserialized LRU cache failed to decode a later cache hit"
        );
    }
}
