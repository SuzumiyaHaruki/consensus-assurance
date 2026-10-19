use omnipaxos::macros::UniCacheEntry;
use omnipaxos::storage::Entry;
use omnipaxos::unicache::{MaybeEncoded, UniCache};

#[derive(Clone, Debug, PartialEq, Eq, UniCacheEntry)]
struct Customer {
    id: u64,
    #[unicache(encoding(u8))]
    first_name: String,
    #[unicache(encoding(u16), size(1000))]
    last_name: String,
    email: String,
    #[unicache(encoding(u16), cache(lru))]
    profession: String,
}

fn main() {
    let _ = Customer {
        id: 1,
        first_name: "Ada".into(),
        last_name: "Lovelace".into(),
        email: "ada@example.invalid".into(),
        profession: "Engineer".into(),
    };
}
