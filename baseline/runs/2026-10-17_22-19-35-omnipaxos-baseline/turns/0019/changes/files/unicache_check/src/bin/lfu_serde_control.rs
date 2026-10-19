use omnipaxos::unicache::{lfu_cache::LFUniCache, FieldCache};

fn check<D>(label: &str, deserialize: D)
where
    D: Fn(&[u8]) -> LFUniCache<String, u64>,
{
    let mut leader = LFUniCache::<String, u64>::new(4);
    for value in ["A", "B"] {
        let _ = leader.try_encode(&value.to_string());
    }
    let transmitted = leader.clone();
    let bytes = serde_json::to_vec(&transmitted).unwrap();
    let mut follower = deserialize(&bytes);
    for value in ["C", "D", "A", "B"] {
        let value = value.to_string();
        assert_eq!(follower.decode(leader.try_encode(&value)), value, "{label}");
    }
}

fn main() {
    check("json", |bytes| serde_json::from_slice(bytes).unwrap());
    println!("PASS: serialized LFU cache remained synchronized");
}
