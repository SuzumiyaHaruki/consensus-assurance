use omnipaxos::unicache::{lru_cache::LRUniCache, FieldCache};

fn main() {
    let mut leader = LRUniCache::<String, u64>::new(2);
    for value in ["A", "B", "A", "A"] {
        let _ = leader.try_encode(&value.to_string());
    }
    let mut follower = leader.clone();
    for value in ["C", "D", "A", "B", "C", "A"] {
        let value = value.to_string();
        let encoded = leader.try_encode(&value);
        assert_eq!(follower.decode(encoded), value);
    }
    println!("PASS: cloned LRU decoder stayed synchronized");
}
