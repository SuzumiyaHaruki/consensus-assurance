use omnipaxos::unicache::{lru_cache::LRUniCache, FieldCache};

fn next(state: &mut u64) -> u64 {
    *state = state
        .wrapping_mul(6364136223846793005)
        .wrapping_add(1442695040888963407);
    *state
}

fn main() {
    for size in 1..=8 {
        for seed in 0..20 {
            let mut state = seed + 1;
            let mut leader = LRUniCache::<u64, u64>::new(size);
            for _ in 0..100 {
                let value = next(&mut state) % 20;
                let _ = leader.try_encode(&value);
            }
            let mut follower = leader.clone();
            for step in 0..2000 {
                let value = next(&mut state) % 20;
                let encoded = leader.try_encode(&value);
                let decoded = follower.decode(encoded);
                assert_eq!(
                    decoded, value,
                    "LRU mismatch at size={size}, seed={seed}, step={step}"
                );
            }
        }
    }
    println!("PASS: 160 randomized LRU clone/decode runs remained synchronized");
}
