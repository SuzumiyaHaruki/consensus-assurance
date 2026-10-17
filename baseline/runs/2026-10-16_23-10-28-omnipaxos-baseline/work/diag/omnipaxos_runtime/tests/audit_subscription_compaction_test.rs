//! Audit reproduction test #2 (added by the auditor, NOT part of the captured source).
//!
//! Target: `omnipaxos_runtime/src/actor.rs`, the decided-log subscriber cursor
//! (`DecidedSub::next_idx`, `push_to_sub`, `push_to_all_subs`).
//!
//! The actor's `Command` set has no trim/snapshot command, but compaction does not have to
//! come from the actor: `OmniPaxos::snapshot(idx, local_only)` is public API on the core
//! instance the caller hands to `spawn_actor`, so a node that snapshots its recovered log
//! before starting its actor is an ordinary, documented use. `next_idx` is advanced once
//! per *delivered item*, while `InternalStorage::read` returns a single
//! `LogEntry::Snapshotted`/`Trimmed` item standing for the whole compacted prefix, so the
//! cursor ends up *behind* the log and the same prefix (or the same entries) is delivered
//! again on every subsequent tick.

#![cfg(all(feature = "tokio_runtime", not(feature = "unicache")))]

use std::time::Duration;

use omnipaxos::{
    storage::{Entry, Snapshot},
    util::{LogEntry, NodeId},
    ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_runtime::{spawn_actor, OmniPaxosHandle, RuntimeConfig, TokioRuntime};
use omnipaxos_storage::memory_storage::MemoryStorage;
use tokio::time::timeout;

#[derive(Clone, Debug, Default, PartialEq, serde::Serialize, serde::Deserialize)]
struct TestEntry(u64);

#[derive(Clone, Debug, Default, serde::Serialize, serde::Deserialize)]
struct NoSnapshot;

impl Snapshot<TestEntry> for NoSnapshot {
    fn create(_entries: &[TestEntry]) -> Self {
        NoSnapshot
    }
    fn merge(&mut self, _delta: Self) {}
    fn use_snapshots() -> bool {
        false
    }
}

impl Entry for TestEntry {
    type Snapshot = NoSnapshot;
}

type Op = OmniPaxos<TestEntry, MemoryStorage<TestEntry>>;

fn build(pid: NodeId, nodes: Vec<NodeId>, priority: u32) -> Op {
    let cluster_config = ClusterConfig {
        configuration_id: 1,
        nodes,
        flexible_quorum: None,
    };
    #[allow(clippy::needless_update)]
    let server_config = ServerConfig {
        pid,
        election_tick_timeout: 5,
        resend_message_tick_timeout: 20,
        buffer_size: 100,
        batch_size: 1,
        flush_batch_tick_timeout: 10,
        leader_priority: priority,
        ..Default::default()
    };
    OmniPaxosConfig {
        cluster_config,
        server_config,
    }
    .build(MemoryStorage::default())
    .expect("build")
}

/// Hand-driven two-node core cluster with no network and no actor: node 1 is forced to
/// become leader, `n` entries are appended, and messages are shuttled between the two
/// instances until both have decided all `n`.
fn decided_pair(n: u64) -> (Op, Op) {
    let mut a = build(1, vec![1, 2], 1);
    let mut b = build(2, vec![1, 2], 0);
    a.try_become_leader();
    let mut next = 0u64;
    for round in 0..5000 {
        a.tick();
        b.tick();
        let mut buf = Vec::new();
        a.take_outgoing_messages(&mut buf);
        for m in buf {
            if m.get_receiver() == 2 {
                b.handle_incoming(m);
            }
        }
        let mut buf = Vec::new();
        b.take_outgoing_messages(&mut buf);
        for m in buf {
            if m.get_receiver() == 1 {
                a.handle_incoming(m);
            }
        }
        if a.get_current_leader() == Some((1, true)) {
            while next < n {
                a.append(TestEntry(100 + next)).expect("append");
                next += 1;
            }
        }
        if a.get_decided_idx() >= n as usize && b.get_decided_idx() >= n as usize {
            eprintln!("[audit-subs] both nodes decided {n} entries after {round} rounds");
            return (a, b);
        }
    }
    panic!(
        "hand-driven cluster failed to decide {n} entries (leader {:?}, node1 decided {}, \
         node2 decided {})",
        a.get_current_leader(),
        a.get_decided_idx(),
        b.get_decided_idx()
    );
}

/// Starts a runtime actor on `op` and collects everything a subscriber starting at `from`
/// receives for `window` while ticking the actor.
async fn collect_subscription(op: Op, from: usize, window: Duration) -> Vec<LogEntry<TestEntry>> {
    let cfg = RuntimeConfig {
        tick_period: Duration::from_millis(20),
        egress_period: Duration::from_millis(1),
        ..Default::default()
    };
    let h: OmniPaxosHandle<TestEntry> =
        spawn_actor::<TestEntry, MemoryStorage<TestEntry>, TokioRuntime>(op, cfg);
    let rx = h.subscribe_decided(from).await;
    let mut items = Vec::new();
    let deadline = tokio::time::Instant::now() + window;
    while tokio::time::Instant::now() < deadline {
        match timeout(Duration::from_millis(30), rx.recv()).await {
            Ok(Ok(item)) => items.push(item),
            Ok(Err(_)) => break,
            Err(_) => {}
        }
    }
    items
}

fn summarize(items: &[LogEntry<TestEntry>]) -> Vec<String> {
    items
        .iter()
        .map(|e| match e {
            LogEntry::Decided(v) => format!("Decided({})", v.0),
            LogEntry::Undecided(v) => format!("Undecided({})", v.0),
            LogEntry::Trimmed(idx) => format!("Trimmed({idx})"),
            LogEntry::Snapshotted(s) => format!("Snapshotted(trimmed_idx={})", s.trimmed_idx),
            LogEntry::StopSign(..) => "StopSign".to_string(),
        })
        .collect()
}

/// Variant A: log fully compacted up to the decided index before the actor starts.
/// Expected (per `subscribe_decided`'s docs: the accumulated decided backlog followed by
/// later entries, in log order) is one item standing for the compacted prefix. Observed:
/// the same prefix item is re-delivered once per tick, as many times as there were
/// compacted-then-decided positions, because `next_idx` counted items instead of log
/// positions.
#[tokio::test]
async fn subscriber_below_fully_compacted_log_gets_the_prefix_repeatedly() {
    let (mut a, mut b) = decided_pair(6);
    assert_eq!(b.get_decided_idx(), 6);
    b.snapshot(Some(6), true).expect("local snapshot");
    assert_eq!(b.get_compacted_idx(), 6, "log should be fully compacted");
    a.snapshot(Some(6), true).expect("local snapshot");

    let items = collect_subscription(b, 0, Duration::from_millis(400)).await;
    let summary = summarize(&items);
    eprintln!(
        "[audit-subs] fully compacted (compacted=6, decided=6), subscriber from 0 received {} \
         items: {:?}",
        items.len(),
        summary
    );

    let prefix_items = items
        .iter()
        .filter(|e| matches!(e, LogEntry::Snapshotted(_) | LogEntry::Trimmed(_)))
        .count();
    assert_eq!(
        prefix_items, 1,
        "the compacted prefix must be delivered once, but {} prefix items were delivered: \
         {summary:?}",
        prefix_items
    );
}

/// Variant B: only part of the log compacted, so the re-delivery is of *decided entries*
/// -- a subscriber can be handed the same application-level command twice.
#[tokio::test]
async fn subscriber_below_partially_compacted_log_gets_entries_twice() {
    let (mut a, mut b) = decided_pair(6);
    b.snapshot(Some(3), true).expect("local snapshot");
    assert_eq!(b.get_compacted_idx(), 3);
    assert_eq!(b.get_decided_idx(), 6);
    a.snapshot(Some(3), true).expect("local snapshot");

    let items = collect_subscription(b, 0, Duration::from_millis(400)).await;
    let summary = summarize(&items);
    eprintln!(
        "[audit-subs] partially compacted (compacted=3, decided=6), subscriber from 0 received \
         {} items: {:?}",
        items.len(),
        summary
    );

    // Every decided entry value may be delivered at most once.
    let mut seen: Vec<u64> = Vec::new();
    let mut duplicates: Vec<u64> = Vec::new();
    for e in &items {
        if let LogEntry::Decided(v) = e {
            if seen.contains(&v.0) {
                duplicates.push(v.0);
            } else {
                seen.push(v.0);
            }
        }
    }
    assert!(
        duplicates.is_empty(),
        "decided entries delivered more than once: {duplicates:?} (full stream: {summary:?})"
    );
}
