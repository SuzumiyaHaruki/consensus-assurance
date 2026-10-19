use std::panic::{catch_unwind, AssertUnwindSafe};

use omnipaxos::unicache::{lru_cache::LRUniCache, FieldCache};

fn check_after_round_trip<S, D>(label: &str, serialize: S, deserialize: D)
where
    S: Fn(&LRUniCache<String, u64>) -> Vec<u8>,
    D: Fn(&[u8]) -> LRUniCache<String, u64>,
{
    let mut leader = LRUniCache::<String, u64>::new(4);
    for value in ["A", "B"] {
        let _ = leader.try_encode(&value.to_string());
    }

    let transmitted = leader.clone();
    let bytes = serialize(&transmitted);
    let mut follower = catch_unwind(AssertUnwindSafe(|| deserialize(&bytes)))
        .unwrap_or_else(|_| panic!("{label}: cache deserialization panicked"));

    let mut history = vec!["A".to_string(), "B".to_string()];
    for value in ["C", "D", "A", "B", "C", "A"] {
        let value = value.to_string();
        history.push(value.clone());
        let encoded = leader.try_encode(&value);
        let decoded = catch_unwind(AssertUnwindSafe(|| follower.decode(encoded)))
            .unwrap_or_else(|_| panic!("{label}: decoder panicked; history={history:?}"));
        assert_eq!(
            decoded, value,
            "{label}: wrong decoded value; history={history:?}"
        );
    }
}

fn main() {
    let mut failures = Vec::new();

    let bincode_bytes = |cache: &LRUniCache<String, u64>| bincode::serialize(cache).unwrap();
    let bincode_cache =
        |bytes: &[u8]| bincode::deserialize(bytes).expect("bincode cache deserialization failed");
    if catch_unwind(AssertUnwindSafe(|| {
        check_after_round_trip("bincode", bincode_bytes, bincode_cache)
    }))
    .is_err()
    {
        failures.push("bincode");
    }

    let json_bytes = |cache: &LRUniCache<String, u64>| serde_json::to_vec(cache).unwrap();
    let json_cache = |bytes: &[u8]| {
        serde_json::from_slice(bytes).expect("json cache deserialization failed")
    };
    if catch_unwind(AssertUnwindSafe(|| {
        check_after_round_trip("json", json_bytes, json_cache)
    }))
    .is_err()
    {
        failures.push("json");
    }
    if !failures.is_empty() {
        panic!("serialized LRU round-trip failed for: {failures:?}");
    }
    println!("PASS: serialized LRU decoder remained synchronized");
}
