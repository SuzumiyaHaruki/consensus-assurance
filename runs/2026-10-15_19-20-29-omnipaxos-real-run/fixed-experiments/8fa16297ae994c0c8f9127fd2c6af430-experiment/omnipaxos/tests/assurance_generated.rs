//! Generated assurance harness (experiment target): applicability contrast for the
//! below-compaction log-update request.
//!
//! Two nodes are exercised with everything held equal except the Entry type: one without snapshots
//! and one with snapshots enabled. Each receives the same legal leader prefix (Prepare, AcceptSync
//! carrying six entries with decided_idx 6, forwarded Compaction::Trim(6)) and then the same legal
//! Prepare from a node whose decided index is 3 while its accepted round is older, which is the
//! message the responder must handle by building a log update.

use std::cell::RefCell;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::rc::Rc;

use omnipaxos::{
    ballot_leader_election::Ballot,
    messages::{
        sequence_paxos::{AcceptSync, Compaction, PaxosMessage, PaxosMsg, Prepare},
        Message,
    },
    storage::{Entry, Snapshot, StopSign, Storage, StorageOp, StorageResult},
    util::{LogSync, NodeId, SequenceNumber},
    ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_storage::{
    memory_storage::MemoryStorage,
    persistent_storage::{PersistentStorage, PersistentStorageConfig},
};
use serde_json::{json, Value};

fn emit(event: &str, fields: Value) {
    let mut obj = json!({ "event": event });
    if let Some(map) = fields.as_object() {
        for (k, v) in map {
            obj[k] = v.clone();
        }
    }
    println!("CA_EVENT {obj}");
}

/// Entry type without snapshots.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct NoSnapEntry(pub u64);

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct NoSnapshot;

impl Snapshot<NoSnapEntry> for NoSnapshot {
    fn create(_entries: &[NoSnapEntry]) -> Self {
        NoSnapshot
    }
    fn merge(&mut self, _delta: Self) {}
    fn use_snapshots() -> bool {
        false
    }
}

impl Entry for NoSnapEntry {
    type Snapshot = NoSnapshot;
}

/// Entry type with snapshots enabled; the snapshot keeps the largest value seen.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct SnapEntry(pub u64);

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct MaxSnapshot(pub u64);

impl Snapshot<SnapEntry> for MaxSnapshot {
    fn create(entries: &[SnapEntry]) -> Self {
        MaxSnapshot(entries.iter().map(|e| e.0).max().unwrap_or(0))
    }
    fn merge(&mut self, delta: Self) {
        self.0 = self.0.max(delta.0);
    }
    fn use_snapshots() -> bool {
        true
    }
}

impl Entry for SnapEntry {
    type Snapshot = MaxSnapshot;
}

#[derive(Clone)]
pub struct SharedStorage<T: Entry>(Rc<RefCell<MemoryStorage<T>>>);

impl<T: Entry> SharedStorage<T> {
    fn new() -> Self {
        SharedStorage(Rc::new(RefCell::new(MemoryStorage::default())))
    }
}

impl<T: Entry> Storage<T> for SharedStorage<T> {
    fn write_atomically(&mut self, ops: Vec<StorageOp<T>>) -> StorageResult<()> {
        self.0.borrow_mut().write_atomically(ops)
    }
    fn append_entry(&mut self, e: T) -> StorageResult<()> {
        self.0.borrow_mut().append_entry(e)
    }
    fn append_entries(&mut self, e: Vec<T>) -> StorageResult<()> {
        self.0.borrow_mut().append_entries(e)
    }
    fn append_on_prefix(&mut self, i: usize, e: Vec<T>) -> StorageResult<()> {
        self.0.borrow_mut().append_on_prefix(i, e)
    }
    fn set_promise(&mut self, b: Ballot) -> StorageResult<()> {
        self.0.borrow_mut().set_promise(b)
    }
    fn set_decided_idx(&mut self, i: usize) -> StorageResult<()> {
        self.0.borrow_mut().set_decided_idx(i)
    }
    fn get_decided_idx(&self) -> StorageResult<usize> {
        self.0.borrow().get_decided_idx()
    }
    fn set_accepted_round(&mut self, b: Ballot) -> StorageResult<()> {
        self.0.borrow_mut().set_accepted_round(b)
    }
    fn get_accepted_round(&self) -> StorageResult<Option<Ballot>> {
        self.0.borrow().get_accepted_round()
    }
    fn get_entries(&self, f: usize, t: usize) -> StorageResult<Vec<T>> {
        self.0.borrow().get_entries(f, t)
    }
    fn get_log_len(&self) -> StorageResult<usize> {
        self.0.borrow().get_log_len()
    }
    fn get_suffix(&self, f: usize) -> StorageResult<Vec<T>> {
        self.0.borrow().get_suffix(f)
    }
    fn get_promise(&self) -> StorageResult<Option<Ballot>> {
        self.0.borrow().get_promise()
    }
    fn set_stopsign(&mut self, s: Option<StopSign>) -> StorageResult<()> {
        self.0.borrow_mut().set_stopsign(s)
    }
    fn get_stopsign(&self) -> StorageResult<Option<StopSign>> {
        self.0.borrow().get_stopsign()
    }
    fn trim(&mut self, i: usize) -> StorageResult<()> {
        self.0.borrow_mut().trim(i)
    }
    fn set_compacted_idx(&mut self, i: usize) -> StorageResult<()> {
        self.0.borrow_mut().set_compacted_idx(i)
    }
    fn get_compacted_idx(&self) -> StorageResult<usize> {
        self.0.borrow().get_compacted_idx()
    }
    fn set_snapshot(&mut self, s: Option<T::Snapshot>) -> StorageResult<()> {
        self.0.borrow_mut().set_snapshot(s)
    }
    fn get_snapshot(&self) -> StorageResult<Option<T::Snapshot>> {
        self.0.borrow().get_snapshot()
    }
}

fn build<T: Entry, S: Storage<T>>(pid: NodeId, store: S) -> OmniPaxos<T, S> {
    let cluster_config = ClusterConfig {
        configuration_id: 1,
        nodes: vec![1, 2, 3],
        flexible_quorum: None,
    };
    #[allow(clippy::needless_update)]
    let server_config = ServerConfig {
        pid,
        election_tick_timeout: 2,
        resend_message_tick_timeout: 4,
        buffer_size: 1000,
        batch_size: 1,
        flush_batch_tick_timeout: 100,
        leader_priority: 0,
        ..Default::default()
    };
    OmniPaxosConfig {
        cluster_config,
        server_config,
    }
    .build(store)
    .expect("failed to build OmniPaxos instance")
}

fn from_leader<T: Entry>(to: NodeId, msg: PaxosMsg<T>) -> Message<T> {
    Message::SequencePaxos(PaxosMessage { from: 1, to, msg })
}

fn scenario<T: Entry, S: Storage<T>, F: Fn(u64) -> T>(
    case: &str,
    snapshots: bool,
    outcome_event: &str,
    store: S,
    mk: F,
) {
    // The responder is node 2; node 1 stands in for the leader that is still running the same
    // prefix of traffic a real leader produces.
    let mut op: OmniPaxos<T, S> = build(2, store);
    let leader_ballot = Ballot::with(1, 1, 0, 1);
    let stale_ballot = Ballot::with(1, 2, 0, 1);
    let no_round = Ballot::default(); // older than the round the responder will accept under

    emit(
        "case_started",
        json!({ "case": case, "use_snapshots": snapshots, "responder": 2 }),
    );

    // (1) leader prepares; responder promises at ballot (1,1,pid 1)
    op.handle_incoming(from_leader(
        2,
        PaxosMsg::Prepare(Prepare {
            n: leader_ballot,
            decided_idx: 0,
            n_accepted: no_round,
            accepted_idx: 0,
        }),
    ));
    // (2) leader syncs six entries and the decided index 6
    let suffix: Vec<T> = (0..6u64).map(&mk).collect();
    op.handle_incoming(from_leader(
        2,
        PaxosMsg::AcceptSync(AcceptSync {
            n: leader_ballot,
            seq_num: SequenceNumber {
                session: 0,
                counter: 1,
            },
            decided_idx: 6,
            log_sync: LogSync {
                decided_snapshot: if snapshots { None } else { None },
                suffix,
                sync_idx: 0,
                stopsign: None,
            },
        }),
    ));
    // (3) leader forwards its successful compaction of the decided prefix
    op.handle_incoming(from_leader(2, PaxosMsg::Compaction(Compaction::Trim(6))));

    emit(
        "state_reached",
        json!({
            "case": case,
            "use_snapshots": snapshots,
            "accepted_idx": op.get_accepted_idx(),
            "decided_idx": op.get_decided_idx(),
            "compacted_idx": op.get_compacted_idx(),
        }),
    );

    // (4) a node whose decided index is 3 (accepted 6, older accepted round) starts a takeover
    let prep = Prepare {
        n: stale_ballot,
        decided_idx: 3,
        n_accepted: no_round,
        accepted_idx: 6,
    };
    let outcome = catch_unwind(AssertUnwindSafe(|| {
        op.handle_incoming(from_leader(2, PaxosMsg::Prepare(prep)));
    }));
    match outcome {
        Ok(()) => emit(
            outcome_event,
            json!({
                "case": case,
                "use_snapshots": snapshots,
                "outcome": "completed",
                "panic_message": Value::Null,
                "compacted_idx": op.get_compacted_idx(),
                "decided_idx": op.get_decided_idx(),
                "accepted_idx": op.get_accepted_idx(),
            }),
        ),
        Err(payload) => {
            let msg = payload
                .downcast_ref::<String>()
                .cloned()
                .or_else(|| payload.downcast_ref::<&str>().map(|s| s.to_string()))
                .unwrap_or_else(|| "<non-string panic payload>".to_string());
            emit(
                outcome_event,
                json!({
                    "case": case,
                    "use_snapshots": snapshots,
                    "outcome": "aborted_panic",
                    "panic_message": msg,
                    "compacted_idx": op.get_compacted_idx(),
                    "decided_idx": op.get_decided_idx(),
                    "accepted_idx": op.get_accepted_idx(),
                }),
            );
        }
    }
}

#[test]
fn below_compaction_request_with_and_without_snapshots() {
    scenario(
        "nosnapshot_entry",
        false,
        "log_sync_outcome_nosnapshot",
        SharedStorage::new(),
        NoSnapEntry,
    );
    scenario(
        "snapshot_entry",
        true,
        "log_sync_outcome_snapshot",
        SharedStorage::new(),
        SnapEntry,
    );

    // Same request with the captured persistent (RocksDB) backend instead of the in-memory one.
    let dir = tempfile::tempdir().expect("failed to create temp dir for persistent storage");
    let path = dir.path().to_str().expect("non-utf8 temp path").to_string();
    let store = PersistentStorage::<NoSnapEntry>::open(PersistentStorageConfig::with_path(path));
    scenario(
        "persistent_backend_entry",
        false,
        "log_sync_outcome_persistent",
        store,
        NoSnapEntry,
    );
    drop(dir);
}
