use std::panic::{catch_unwind, AssertUnwindSafe};

use omnipaxos::unicache::{lfu_cache::LFUniCache, FieldCache};

fn main() {
    let mut leader = LFUniCache::<String, u64>::new(2);

    // Build unequal access frequencies before the decoder is cloned.
    for value in ["A", "B", "A", "A"] {
        let _ = leader.try_encode(&value.to_string());
    }
    let mut follower = leader.clone();

    // New misses evict entries, then a former hot entry is sent as a cache hit.
    for value in ["C", "D", "A", "B", "C", "A"] {
        let value = value.to_string();
        let encoded = leader.try_encode(&value);
        let decoded = catch_unwind(AssertUnwindSafe(|| follower.decode(encoded)))
            .unwrap_or_else(|_| panic!("follower panicked decoding a leader cache hit for {value:?}"));
        assert_eq!(
            decoded, value,
            "LFU decoder did not reconstruct the leader's encoded value"
        );
    }
    println!("PASS: cloned LFU decoder remained synchronized with the leader");
}
