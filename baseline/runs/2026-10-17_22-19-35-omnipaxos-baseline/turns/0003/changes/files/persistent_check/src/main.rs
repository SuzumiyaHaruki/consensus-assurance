use std::fmt;

use omnipaxos::{
    ballot_leader_election::Ballot,
    storage::{Entry, Snapshot, Storage, StorageOp},
};
use omnipaxos_storage::persistent_storage::{PersistentStorage, PersistentStorageConfig};
use serde::{
    de::{self, Deserializer, Visitor},
    ser::{SerializeStruct, Serializer},
    Deserialize, Serialize,
};

#[derive(Clone, Debug, PartialEq)]
struct FailingEntry {
    id: u64,
    fail_serialization: bool,
}

impl Serialize for FailingEntry {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        if self.fail_serialization {
            return Err(serde::ser::Error::custom("intentional serialization failure"));
        }
        let mut state = serializer.serialize_struct("FailingEntry", 2)?;
        state.serialize_field("id", &self.id)?;
        state.serialize_field("fail_serialization", &self.fail_serialization)?;
        state.end()
    }
}

impl<'de> Deserialize<'de> for FailingEntry {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct EntryVisitor;

        impl<'de> Visitor<'de> for EntryVisitor {
            type Value = FailingEntry;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a FailingEntry")
            }

            fn visit_seq<A>(self, mut seq: A) -> Result<Self::Value, A::Error>
            where
                A: de::SeqAccess<'de>,
            {
                let id = seq
                    .next_element::<u64>()?
                    .ok_or_else(|| de::Error::custom("missing id"))?;
                let fail_serialization = seq
                    .next_element::<bool>()?
                    .ok_or_else(|| de::Error::custom("missing fail_serialization"))?;
                Ok(FailingEntry {
                    id,
                    fail_serialization,
                })
            }
        }

        deserializer.deserialize_struct(
            "FailingEntry",
            &["id", "fail_serialization"],
            EntryVisitor,
        )
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct NoSnapshot;

impl Snapshot<FailingEntry> for NoSnapshot {
    fn create(_entries: &[FailingEntry]) -> Self {
        NoSnapshot
    }

    fn merge(&mut self, _delta: Self) {}

    fn use_snapshots() -> bool {
        false
    }
}

impl Entry for FailingEntry {
    type Snapshot = NoSnapshot;
}

fn main() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("db").to_string_lossy().into_owned();
    let mut storage = PersistentStorage::<FailingEntry>::new(PersistentStorageConfig::with_path(path));

    let result = storage.write_atomically(vec![
        StorageOp::AppendEntry(FailingEntry {
            id: 1,
            fail_serialization: false,
        }),
        StorageOp::AppendEntry(FailingEntry {
            id: 2,
            fail_serialization: true,
        }),
    ]);
    assert!(result.is_err(), "the second serialization was supposed to fail");

    // Storage::write_atomically promises all-or-none semantics. A failed
    // transaction must not leave the first append visible or queued.
    let visible_len_after_failure = storage.get_log_len().unwrap();
    let entries_after_failure = storage.get_entries(0, 1).map(|entries| entries.len());

    // A subsequent unrelated transaction must not commit the failed one.
    storage
        .write_atomically(vec![StorageOp::SetPromise(Ballot::default())])
        .unwrap();
    let entries_after_unrelated_write = storage.get_entries(0, 1).map(|entries| entries.len());
    let failure_was_empty = entries_after_failure.as_ref().map_or(false, |n| *n == 0);
    let unrelated_was_empty = entries_after_unrelated_write
        .as_ref()
        .map_or(false, |n| *n == 0);
    assert!(
        visible_len_after_failure == 0
            && failure_was_empty
            && unrelated_was_empty,
        "failed transaction leaked state: len_after_failure={visible_len_after_failure}, \
         entries_after_failure={entries_after_failure:?}, \
         entries_after_unrelated_write={entries_after_unrelated_write:?}"
    );
}
