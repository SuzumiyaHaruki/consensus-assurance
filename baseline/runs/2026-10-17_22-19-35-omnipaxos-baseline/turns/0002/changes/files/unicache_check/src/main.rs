use omnipaxos::unicache::{lru_cache::LRUniCache, FieldCache};

fn round_trip(cache: &LRUniCache<u64, u64>, label: &str) {
    let encoded = serde_json::to_string(cache).expect("serialize");
    let decoded: LRUniCache<u64, u64> =
        serde_json::from_str(&encoded).unwrap_or_else(|err| panic!("{label}: {err}"));
    let reencoded = serde_json::to_string(&decoded).expect("reserialize");
    assert_eq!(encoded, reencoded, "{label}: round-trip changed the cache");
}

fn main() {
    let empty = LRUniCache::<u64, u64>::new(4);
    round_trip(&empty, "empty cache");

    // Control: the same implementation round-trips once it contains an entry.
    let mut populated = LRUniCache::<u64, u64>::new(4);
    let _ = populated.try_encode(&42);
    round_trip(&populated, "populated cache");
    println!("PASS: empty and populated UniCache values round-trip through serde");
}
