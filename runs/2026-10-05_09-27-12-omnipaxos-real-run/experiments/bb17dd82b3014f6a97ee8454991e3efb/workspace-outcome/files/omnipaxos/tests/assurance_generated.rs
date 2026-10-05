use omnipaxos::{ballot_leader_election::Ballot, storage::{Entry, NoSnapshot, Storage, StorageOp}};
use omnipaxos_storage::persistent_storage::{PersistentStorage, PersistentStorageConfig};
use serde::{Deserialize, Serialize, Serializer};
use serde_json::json;
use std::sync::atomic::{AtomicUsize, Ordering};

static SERIALIZATION_ERRORS: AtomicUsize = AtomicUsize::new(0);
#[derive(Clone, Debug, Deserialize, PartialEq)]
struct Value(u64);
impl Serialize for Value {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        if self.0 == 999 {
            SERIALIZATION_ERRORS.fetch_add(1, Ordering::SeqCst);
            return Err(serde::ser::Error::custom("selected entry cannot be serialized"));
        }
        serializer.serialize_u64(self.0)
    }
}
impl Entry for Value { type Snapshot = NoSnapshot; }
fn event(v: serde_json::Value) { println!("CA_EVENT {}", v); }

#[test]
fn persistent_returned_error_rollback() {
    // Database lives only in this clean execution workspace; close before cleanup.
    let root = tempfile::Builder::new().prefix("rollback-check-").tempdir_in(".").unwrap();
    let path = root.path().join("db").to_string_lossy().into_owned();
    let config = || PersistentStorageConfig::with_path(path.clone());
    let mut storage = PersistentStorage::<Value>::open(config());
    let old_ballot=Ballot::with(1,1,0,1);
    let failed_ballot=Ballot::with(1,2,0,1);
    storage.append_entry(Value(7)).unwrap();
    storage.set_promise(old_ballot).unwrap();
    let before_len=storage.get_log_len().unwrap();
    let before_promise=storage.get_promise().unwrap().unwrap();
    let before_prefix=storage.get_entries(0,before_len).unwrap();
    assert_eq!(before_len,1);
    assert_eq!(before_promise,old_ballot);
    assert_eq!(before_prefix,vec![Value(7)]);
    event(json!({"event":"storage_admitted","op_id":"failed-transaction","before_len":before_len,
        "before_promise_n":before_promise.n,"before_first":before_prefix[0].0,"error_value":999}));
    let result=storage.write_atomically(vec![StorageOp::SetPromise(failed_ballot),
        StorageOp::AppendEntry(Value(11)),StorageOp::AppendEntry(Value(999))]);
    let returned_error=result.is_err();
    let error_count=SERIALIZATION_ERRORS.load(Ordering::SeqCst);
    let error_text=result.err().map(|e|e.to_string()).unwrap_or_default();
    event(json!({"event":"storage_returned","op_id":"failed-transaction","returned_error":returned_error,
        "serialization_error_observed":error_count>0,"error_text":error_text}));
    assert!(returned_error && error_count>0,"selected serialization failure was not reached");
    let immediate_len=storage.get_log_len().unwrap();
    let immediate_promise=storage.get_promise().unwrap().unwrap();
    let prefix=storage.get_entries(0,1).unwrap();
    event(json!({"event":"immediate_state","op_id":"failed-transaction","log_len":immediate_len,
        "promise_n":immediate_promise.n,"first":prefix[0].0}));
    // This independent transaction contains neither failed append nor failed promise.
    let independent=storage.write_atomically(vec![StorageOp::SetDecidedIndex(0)]);
    let independent_ok=independent.is_ok();
    event(json!({"event":"independent_completed","op_id":"failed-transaction","success":independent_ok,
        "requested_decided_idx":0}));
    independent.unwrap();
    let after_len=storage.get_log_len().unwrap();
    let after_promise=storage.get_promise().unwrap().unwrap();
    let after_entries=storage.get_entries(0,after_len).unwrap();
    event(json!({"event":"after_independent","op_id":"failed-transaction","log_len":after_len,
        "promise_n":after_promise.n,"entries":after_entries.iter().map(|v|v.0).collect::<Vec<_>>(),
        "decided_idx":storage.get_decided_idx().unwrap()}));
    drop(storage);
    let reopened=PersistentStorage::<Value>::open(config());
    let reopened_len=reopened.get_log_len().unwrap();
    let reopened_promise=reopened.get_promise().unwrap().unwrap();
    event(json!({"event":"reopened_state","op_id":"failed-transaction","log_len":reopened_len,
        "promise_n":reopened_promise.n,"entries":reopened.get_entries(0,reopened_len).unwrap().iter().map(|v|v.0).collect::<Vec<_>>()}));
    drop(reopened);
    root.close().unwrap();
}
