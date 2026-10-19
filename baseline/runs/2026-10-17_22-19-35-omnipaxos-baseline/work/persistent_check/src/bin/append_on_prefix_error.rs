use std::fmt;

use omnipaxos::storage::{Entry, Snapshot, Storage};
use omnipaxos_storage::persistent_storage::{PersistentStorage, PersistentStorageConfig};
use serde::{
    de::{self, Deserializer, Visitor},
    ser::{SerializeStruct, Serializer},
    Deserialize, Serialize,
};

#[derive(Clone, Debug)]
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
                Ok(FailingEntry {
                    id: seq.next_element()?.unwrap(),
                    fail_serialization: seq.next_element()?.unwrap(),
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

fn entry(id: u64, fail_serialization: bool) -> FailingEntry {
    FailingEntry {
        id,
        fail_serialization,
    }
}

fn main() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("db").to_string_lossy().into_owned();
    let mut storage = PersistentStorage::<FailingEntry>::new(PersistentStorageConfig::with_path(
        path.clone(),
    ));
    storage
        .append_entries(vec![entry(1, false), entry(2, false), entry(3, false), entry(4, false)])
        .unwrap();

    let result = storage.append_on_prefix(1, vec![entry(9, false), entry(10, true)]);
    assert!(result.is_err(), "replacement serialization was supposed to fail");
    drop(storage);

    let reopened =
        PersistentStorage::<FailingEntry>::open(PersistentStorageConfig::with_path(path));
    let len_after_failure = reopened.get_log_len().unwrap();
    let entries_after_failure = reopened.get_entries(0, 3).map(|entries| {
        entries
            .into_iter()
            .map(|entry| entry.id)
            .collect::<Vec<_>>()
    });
    assert_eq!(
        len_after_failure, 4,
        "failed append_on_prefix permanently removed the old suffix; entries={entries_after_failure:?}"
    );
}
