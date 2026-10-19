#![cfg(feature = "unicache")]

use omnipaxos::unicache::{lfu_cache::LFUniCache, FieldCache};

#[test]
fn cloned_lfu_decoder_reconstructs_later_cache_hits() {
    let mut leader = LFUniCache::<String, u64>::new(2);
    for value in ["A", "B", "A", "A"] {
        let _ = leader.try_encode(&value.to_string());
    }
    let mut follower = leader.clone();

    for value in ["C", "D", "A", "B", "C", "A"] {
        let value = value.to_string();
        let encoded = leader.try_encode(&value);
        assert_eq!(
            follower.decode(encoded),
            value,
            "follower decoded a cache hit to a different value"
        );
    }
}
