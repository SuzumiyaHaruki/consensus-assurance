use std::sync::atomic::{AtomicUsize, Ordering};
use omnipaxos::{ballot_leader_election::Ballot, storage::{Entry, Snapshot, Storage, StorageOp}};
use omnipaxos_storage::persistent_storage::{PersistentStorage, PersistentStorageConfig};
use serde::{Serialize, Serializer, Deserialize};

static SERIALIZATION_ERRORS: AtomicUsize = AtomicUsize::new(0);
#[derive(Clone, Debug, PartialEq, Deserialize)]
#[serde(transparent)]
struct Value(u64);
impl Serialize for Value {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok,S::Error> {
        if self.0 == 99 {
            SERIALIZATION_ERRORS.fetch_add(1,Ordering::SeqCst);
            Err(serde::ser::Error::custom("declared entry encoding failure"))
        } else { serializer.serialize_u64(self.0) }
    }
}
#[derive(Clone,Debug,Serialize,Deserialize)]
struct NoSnapshot;
impl Snapshot<Value> for NoSnapshot {
    fn create(_: &[Value]) -> Self { Self }
    fn merge(&mut self,_:Self) {}
    fn use_snapshots() -> bool { false }
}
impl Entry for Value { type Snapshot = NoSnapshot; }

#[test]
fn atomic_error_preserves_extent() {
    SERIALIZATION_ERRORS.store(0,Ordering::SeqCst);
    // The runner owns this disposable workspace; no captured database is opened.
    let directory=tempfile::Builder::new().prefix("rollback-check-").tempdir_in(".").unwrap();
    let path=directory.path().join("db").to_string_lossy().into_owned();
    let mut storage=PersistentStorage::<Value>::new(PersistentStorageConfig::with_path(path.clone()));
    storage.append_entry(Value(7)).unwrap();
    let before_len=storage.get_log_len().unwrap();
    let before_entries=storage.get_entries(0,before_len).unwrap();
    let before_promise=storage.get_promise().unwrap();
    assert_eq!(before_entries,vec![Value(7)]);
    assert_eq!(before_len,1);
    assert!(before_promise.is_none());
    println!("CA_EVENT {{\"event\":\"atomic_admitted\",\"transaction\":\"error-after-staging\",\"before_len\":{},\"healthy_prefix\":true,\"fault_value\":99}}",before_len);
    let attempted_promise=Ballot::with(1,2,0,1);
    let result=storage.write_atomically(vec![
        StorageOp::SetPromise(attempted_promise),
        StorageOp::AppendEntries(vec![Value(8),Value(99)]),
    ]);
    let returned_error=result.is_err();
    let error_text=result.err().map(|e|e.to_string()).unwrap_or_default();
    let after_len=storage.get_log_len().unwrap();
    let after_promise=storage.get_promise().unwrap();
    let original_prefix=storage.get_entries(0,1).unwrap();
    println!("CA_EVENT {{\"event\":\"atomic_result\",\"transaction\":\"error-after-staging\",\"returned_error\":{},\"after_len\":{},\"serialization_errors\":{},\"original_prefix_unchanged\":{},\"promise_unchanged\":{},\"error\":{}}}",returned_error,after_len,SERIALIZATION_ERRORS.load(Ordering::SeqCst),original_prefix==before_entries,after_promise==before_promise,serde_json::to_string(&error_text).unwrap());

    // Diagnostic only: a later unrelated successful operation tests whether
    // rejected staging remains. The formal predicate above is already observed.
    storage.write_atomically(vec![StorageOp::SetDecidedIndex(0)]).unwrap();
    let later_promise=storage.get_promise().unwrap();
    let later_len=storage.get_log_len().unwrap();
    println!("CA_EVENT {{\"event\":\"later_commit_diagnostic\",\"transaction\":\"error-after-staging\",\"len\":{},\"rejected_promise_visible\":{}}}",later_len,later_promise==Some(attempted_promise));
    drop(storage);
    let reopened=PersistentStorage::<Value>::open(PersistentStorageConfig::with_path(path));
    println!("CA_EVENT {{\"event\":\"reopen_diagnostic\",\"transaction\":\"error-after-staging\",\"len\":{},\"rejected_promise_visible\":{}}}",reopened.get_log_len().unwrap(),reopened.get_promise().unwrap()==Some(attempted_promise));
    drop(reopened);
    directory.close().unwrap();
}
