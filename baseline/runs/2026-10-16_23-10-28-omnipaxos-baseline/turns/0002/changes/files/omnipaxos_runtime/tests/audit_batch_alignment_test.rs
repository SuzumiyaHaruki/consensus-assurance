//! Audit reproduction test (added by the auditor, NOT part of the captured source).
//!
//! Target: `omnipaxos_runtime/src/actor.rs`, the local FIFO bookkeeping for batched
//! `append_notify` calls (`ActorState::unconfirmed_local`, `append_tracked`,
//! `reconcile_unconfirmed`).
//!
//! Claimed contract (see `OmniPaxosHandle::append_notify` docs): the returned index is
//! "its decided log index", i.e. `read_decided_suffix()[idx - 1]` is the entry that call
//! appended.
//!
//! Scenario: `batch_size = 2`, all three calls issued on the elected leader within a
//! single tick window (so no `reconcile_unconfirmed` pass runs in between):
//!   1. plain `append(1000)`          -> enters batch buffer, no flush, pushes ONE
//!      `TrackIntent::Untracked` placeholder into `unconfirmed_local`
//!   2. `append_notify(2000)`         -> fills the batch, flushes {1000, 2000}; this
//!      entry is accepted immediately, so `append_tracked` resolves it directly and
//!      pushes NO placeholder, but `accepted_idx` advanced by 2 (one advance more than
//!      there are queued placeholders)
//!   3. `append_notify(3000)`         -> does NOT flush; pushes ONE
//!      `TrackIntent::Local(id3)` placeholder behind the untracked one
//! The next tick then pops one queue item per single unit of `accepted_idx` advance
//! (2 pops), consuming the stale slot that the immediately-accepted entry in step 2
//! never accounted for, and resolves call 3 with the index that actually belongs to
//! entry 2000.

use std::{collections::HashMap, sync::Arc, time::Duration};

use omnipaxos::{
    storage::{Entry, Snapshot},
    util::{LogEntry, NodeId},
    ClusterConfig, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_runtime::{spawn_actor, OmniPaxosHandle, RuntimeConfig, TokioRuntime};
use omnipaxos_storage::memory_storage::MemoryStorage;

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

/// Spawn `n` nodes wired together over in-memory channels, with a long tick period so
/// that a burst of commands issued back-to-back is processed without an intervening
/// `tick()`.
async fn spawn_cluster(
    n: NodeId,
    batch_size: usize,
    tick_period: Duration,
) -> HashMap<NodeId, OmniPaxosHandle<TestEntry>> {
    spawn_cluster_with_flush(n, batch_size, tick_period, 100).await
}

/// Same as [`spawn_cluster`], but with an explicit `flush_batch_tick_timeout` so a test can
/// let a partially-filled batch flush on its own within a few ticks.
async fn spawn_cluster_with_flush(
    n: NodeId,
    batch_size: usize,
    tick_period: Duration,
    flush_batch_tick_timeout: u64,
) -> HashMap<NodeId, OmniPaxosHandle<TestEntry>> {
    let nodes: Vec<NodeId> = (1..=n).collect();
    let rt_cfg = RuntimeConfig {
        tick_period,
        egress_period: Duration::from_millis(1),
        ..Default::default()
    };

    let mut handles: HashMap<NodeId, OmniPaxosHandle<TestEntry>> = HashMap::new();
    for pid in nodes.clone() {
        let cluster_config = ClusterConfig {
            configuration_id: 1,
            nodes: nodes.clone(),
            flexible_quorum: None,
        };
        #[allow(clippy::needless_update)]
        let server_config = ServerConfig {
            pid,
            election_tick_timeout: 3,
            resend_message_tick_timeout: 5,
            buffer_size: 100,
            batch_size,
            flush_batch_tick_timeout,
            leader_priority: 0,
            ..Default::default()
        };
        let op = OmniPaxosConfig {
            cluster_config,
            server_config,
        }
        .build(MemoryStorage::default())
        .unwrap();
        handles.insert(
            pid,
            spawn_actor::<TestEntry, MemoryStorage<TestEntry>, TokioRuntime>(op, rt_cfg.clone()),
        );
    }

    let handles_arc = Arc::new(handles.clone());
    for pid in nodes {
        let out = handles_arc[&pid].outgoing_messages();
        let peers = handles_arc.clone();
        tokio::spawn(async move {
            while let Ok(msg) = out.recv().await {
                let receiver = msg.get_receiver();
                if let Some(peer) = peers.get(&receiver) {
                    peer.handle_incoming(msg).await;
                }
            }
        });
    }
    handles
}

/// Waits until some node reports *itself* as leader in the Accept phase, and returns
/// that node's pid and handle.
async fn wait_for_leader_node(
    handles: &HashMap<NodeId, OmniPaxosHandle<TestEntry>>,
) -> (NodeId, OmniPaxosHandle<TestEntry>) {
    let start = tokio::time::Instant::now();
    loop {
        for (pid, h) in handles.iter() {
            if let Some((leader, true)) = h.current_leader().await {
                if leader == *pid {
                    return (*pid, h.clone());
                }
            }
        }
        if start.elapsed() > Duration::from_secs(5) {
            panic!("no node reports itself as leader within 5s");
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}

async fn decided_log(h: &OmniPaxosHandle<TestEntry>) -> Vec<TestEntry> {
    h.read_decided_suffix(0)
        .await
        .unwrap_or_default()
        .into_iter()
        .filter_map(|e| match e {
            LogEntry::Decided(v) => Some(v),
            _ => None,
        })
        .collect()
}

#[tokio::test]
async fn append_notify_index_is_wrong_when_a_flush_is_followed_by_a_batched_append() {
    let tick = Duration::from_millis(100);
    let handles = spawn_cluster(3, 2, tick).await;
    let (_, leader_h) = wait_for_leader_node(&handles).await;

    // Issue all three calls in one burst: `futures::join!` polls them in order, each
    // command channel send completes immediately (capacity 1024), so all three commands
    // are queued before this task yields and before the actor's next tick can run.
    let f1 = leader_h.append(TestEntry(1000));
    let f2 = leader_h.append_notify(TestEntry(2000));
    let f3 = leader_h.append_notify(TestEntry(3000));
    let (r1, r2, r3) = futures::join!(f1, f2, f3);
    r1.expect("plain append(1000) failed");
    let idx2 = r2.expect("append_notify(2000) failed");
    let idx3 = r3.expect("append_notify(3000) failed");
    eprintln!("[audit] idx(2000) = {idx2}, idx(3000) = {idx3}");

    // Force the still-buffered third entry to flush by filling the batch, then let the
    // cluster decide everything.
    leader_h.append(TestEntry(4000)).await.expect("append(4000) failed");
    tokio::time::sleep(20 * tick).await;

    let log = decided_log(&leader_h).await;
    eprintln!("[audit] decided log (1-based): ");
    for (i, e) in log.iter().enumerate() {
        eprintln!("[audit]   idx {} = {:?}", i + 1, e);
    }

    // Sanity: the entry that triggered the flush got its own (correct) index.
    assert_eq!(
        log.get(idx2 - 1),
        Some(&TestEntry(2000)),
        "append_notify(2000) returned idx {idx2}, but the decided log there is {:?}",
        log.get(idx2 - 1)
    );

    // The contract under audit: the index returned for `append_notify(3000)` must hold
    // that call's entry.
    assert_eq!(
        log.get(idx3 - 1),
        Some(&TestEntry(3000)),
        "append_notify(3000) returned idx {idx3}, but the decided log has {:?} at that \
         index (its own entry is at idx {:?}) -- the returned index is not this entry's \
         decided index",
        log.get(idx3 - 1),
        log.iter().position(|e| *e == TestEntry(3000)).map(|p| p + 1)
    );
}

/// Control for the test above: byte-for-byte the same calls in the same order, except
/// that the third call is issued *after* a tick has run (so `reconcile_unconfirmed`
/// passes over the stale slot while the queue is empty and re-aligns
/// `last_seen_accepted_idx`). Same cluster, same `batch_size`, same entries -> the
/// returned index is correct. This isolates the cause to the missing placeholder for the
/// flush-triggering entry and the pop-per-advance accounting in `reconcile_unconfirmed`,
/// rather than to batching, leader election or the core log.
#[tokio::test]
async fn control_same_calls_separated_by_a_tick_resolve_correctly() {
    let tick = Duration::from_millis(100);
    let handles = spawn_cluster(3, 2, tick).await;
    let (_, leader_h) = wait_for_leader_node(&handles).await;

    let f1 = leader_h.append(TestEntry(1000));
    let f2 = leader_h.append_notify(TestEntry(2000));
    let (r1, r2) = futures::join!(f1, f2);
    r1.expect("plain append(1000) failed");
    let idx2 = r2.expect("append_notify(2000) failed");

    // One tick pass (reconcile_unconfirmed) happens here.
    tokio::time::sleep(2 * tick).await;

    // Same two remaining calls as the failing case, still issued back-to-back (so the
    // second one is the one that flushes the batch).
    let f3 = leader_h.append_notify(TestEntry(3000));
    let f4 = leader_h.append_notify(TestEntry(4000));
    let (r3, r4) = futures::join!(f3, f4);
    let idx3 = r3.expect("append_notify(3000) failed");
    let idx4 = r4.expect("append_notify(4000) failed");
    tokio::time::sleep(20 * tick).await;

    let log = decided_log(&leader_h).await;
    eprintln!(
        "[audit-control] idx(2000) = {idx2}, idx(3000) = {idx3}, idx(4000) = {idx4}, \
         log = {log:?}"
    );
    assert_eq!(log.get(idx2 - 1), Some(&TestEntry(2000)));
    assert_eq!(
        log.get(idx3 - 1),
        Some(&TestEntry(3000)),
        "control case should return the correct index"
    );
    assert_eq!(log.get(idx4 - 1), Some(&TestEntry(4000)));
}

/// Same defect with `batch_size = 4` (the shape used by the captured suite's own
/// `append_notify_index_correct_when_batched_with_plain_append` test, plus one extra
/// `append_notify` after the flush): 2 plain appends + 2 `append_notify` calls fill and
/// flush the batch, and a 5th call is batched behind them in the same tick window. Shows
/// the mis-assignment is not a `batch_size = 2` quirk.
#[tokio::test]
async fn append_notify_index_is_wrong_batch_size_four() {
    let tick = Duration::from_millis(100);
    let handles = spawn_cluster(3, 4, tick).await;
    let (_, leader_h) = wait_for_leader_node(&handles).await;

    let f1 = leader_h.append(TestEntry(1000));
    let f2 = leader_h.append(TestEntry(2000));
    let f3 = leader_h.append_notify(TestEntry(3000));
    let f4 = leader_h.append_notify(TestEntry(4000));
    let f5 = leader_h.append_notify(TestEntry(5000));
    let (r1, r2, r3, r4, r5) = futures::join!(f1, f2, f3, f4, f5);
    r1.expect("append(1000) failed");
    r2.expect("append(2000) failed");
    let idx3 = r3.expect("append_notify(3000) failed");
    let idx4 = r4.expect("append_notify(4000) failed");
    let idx5 = r5.expect("append_notify(5000) failed");
    eprintln!(
        "[audit-b4] idx(3000) = {idx3}, idx(4000) = {idx4}, idx(5000) = {idx5}"
    );

    // Fill the (size-4) batch so the still-buffered entry 5000 is flushed and accepted.
    for e in [6000, 7000, 8000] {
        leader_h
            .append(TestEntry(e))
            .await
            .expect("plain append failed");
    }
    tokio::time::sleep(20 * tick).await;

    let log = decided_log(&leader_h).await;
    eprintln!("[audit-b4] decided log: {log:?}");

    assert_eq!(log.get(idx4 - 1), Some(&TestEntry(4000)));
    assert_eq!(
        log.get(idx3 - 1),
        Some(&TestEntry(3000)),
        "append_notify(3000) returned idx {idx3}, decided log there is {:?}",
        log.get(idx3 - 1)
    );
    assert_eq!(
        log.get(idx5 - 1),
        Some(&TestEntry(5000)),
        "append_notify(5000) returned idx {idx5}, but the decided log has {:?} at that \
         index (its own entry is at idx {:?})",
        log.get(idx5 - 1),
        log.iter().position(|e| *e == TestEntry(5000)).map(|p| p + 1)
    );
}

/// Same defect reached through the *remote* path (`TrackIntent::Remote` +
/// `AsyncRuntimeMsg::Assigned`), i.e. a follower's `append_notify` gets the wrong index
/// back from the leader. `batch_size = 4`: the leader buffers 4 plain appends (the 4th
/// one flushes the batch and is accepted directly, leaving a stale queued slot), then a
/// follower's tagged proposal is buffered behind them in the same tick window, so the
/// next `reconcile_unconfirmed` pass pops the follower's placeholder one index too early
/// and the leader replies `Assigned { idx: 4 }` for an entry that lands at index 5.
#[tokio::test]
async fn follower_append_notify_gets_wrong_index_from_leader() {
    let tick = Duration::from_millis(150);
    let handles = spawn_cluster(3, 4, tick).await;
    let (leader_pid, leader_h) = wait_for_leader_node(&handles).await;
    let follower_h = handles
        .iter()
        .find(|(pid, _)| **pid != leader_pid)
        .map(|(_, h)| h.clone())
        .expect("no follower");

    // Leader-side burst that fills and flushes the batch (last call is the trigger, and
    // is accepted directly), issued together with the follower's tagged proposal.
    let a1 = leader_h.append(TestEntry(1000));
    let a2 = leader_h.append(TestEntry(2000));
    let a3 = leader_h.append(TestEntry(3000));
    let a4 = leader_h.append(TestEntry(4000));
    let f5 = follower_h.append_notify(TestEntry(5000));
    let (r1, r2, r3, r4, r5) = futures::join!(a1, a2, a3, a4, f5);
    r1.expect("append(1000) failed");
    r2.expect("append(2000) failed");
    r3.expect("append(3000) failed");
    r4.expect("append(4000) failed");
    let idx5 = r5.expect("follower append_notify(5000) failed");
    eprintln!("[audit-remote] follower idx(5000) = {idx5}");

    // Flush the follower's still-buffered entry on the leader.
    for e in [6000, 7000, 8000] {
        leader_h
            .append(TestEntry(e))
            .await
            .expect("plain append failed");
    }
    tokio::time::sleep(20 * tick).await;

    let log = decided_log(&follower_h).await;
    eprintln!("[audit-remote] decided log: {log:?}");
    assert_eq!(
        log.get(idx5 - 1),
        Some(&TestEntry(5000)),
        "follower's append_notify(5000) was told idx {idx5}, but the decided log has {:?} \
         at that index (its own entry is at idx {:?})",
        log.get(idx5 - 1),
        log.iter().position(|e| *e == TestEntry(5000)).map(|p| p + 1)
    );
}

/// Extent of the defect: with two more tracked writes queued behind the flush-triggering
/// one, the one-index shift is not a single one-off — *both* of the following callers are
/// told the index of the write before them, and so on for as long as the queue stays
/// non-empty. `batch_size = 4`, six `append_notify` calls in one tick window: calls 1-3
/// are buffered, call 4 fills the batch (flush, self-resolved, no placeholder), calls 5
/// and 6 are buffered behind it, so the next `reconcile_unconfirmed` pass pops the
/// placeholders of calls 5 and 6 one advance early.
#[tokio::test]
async fn shift_propagates_to_multiple_pending_callers() {
    let tick = Duration::from_millis(100);
    // `flush_batch_tick_timeout: 2` lets the batch holding calls 5 and 6 flush by itself
    // after two ticks, so all six calls resolve without any extra appends.
    let handles = spawn_cluster_with_flush(3, 4, tick, 2).await;
    let (_, leader_h) = wait_for_leader_node(&handles).await;

    let f1 = leader_h.append_notify(TestEntry(1000));
    let f2 = leader_h.append_notify(TestEntry(2000));
    let f3 = leader_h.append_notify(TestEntry(3000));
    let f4 = leader_h.append_notify(TestEntry(4000));
    let f5 = leader_h.append_notify(TestEntry(5000));
    let f6 = leader_h.append_notify(TestEntry(6000));
    let (r1, r2, r3, r4, r5, r6) = futures::join!(f1, f2, f3, f4, f5, f6);
    let idx: Vec<usize> = [r1, r2, r3, r4, r5, r6]
        .into_iter()
        .enumerate()
        .map(|(i, r)| r.unwrap_or_else(|_| panic!("append_notify #{} failed", i + 1)))
        .collect();
    eprintln!("[audit-cascade] returned indices for entries 1000..6000 = {idx:?}");

    // Entries 5000 and 6000 are flushed by the batch tick timeout (see cluster setup).
    tokio::time::sleep(20 * tick).await;

    let log = decided_log(&leader_h).await;
    eprintln!("[audit-cascade] decided log: {log:?}");

    let wrong: Vec<(usize, usize, u64, u64)> = idx
        .iter()
        .enumerate()
        .filter_map(|(i, reported)| {
            let expected = TestEntry((i as u64 + 1) * 1000);
            match log.get(reported - 1) {
                Some(actual) if *actual == expected => None,
                other => Some((
                    i + 1,
                    *reported,
                    expected.0,
                    other.map(|e| e.0).unwrap_or(0),
                )),
            }
        })
        .collect();
    eprintln!("[audit-cascade] wrong (call#, reported idx, entry, actual entry at idx) = {wrong:?}");
    assert!(
        wrong.is_empty(),
        "{} of {} append_notify calls were told an index that does not hold their entry: {:?}",
        wrong.len(),
        idx.len(),
        wrong
    );
}

/// Sharpest observable consequence: the caller is told "decided" while its entry has not
/// even been accepted by anyone. Same `batch_size = 2` burst as the first test, but here
/// the state of the log is inspected *at the moment call 3 resolves*, before anything else
/// flushes the batch holding entry 3000 (the batch tick timeout is 100 ticks, i.e. 10s,
/// and the reply arrives within a tick or two).
#[tokio::test]
async fn wrong_index_is_reported_while_the_entry_is_still_unaccepted() {
    let tick = Duration::from_millis(100);
    let handles = spawn_cluster(3, 2, tick).await;
    let (_, leader_h) = wait_for_leader_node(&handles).await;

    let f1 = leader_h.append(TestEntry(1000));
    let f2 = leader_h.append_notify(TestEntry(2000));
    let f3 = leader_h.append_notify(TestEntry(3000));
    let (r1, r2, r3) = futures::join!(f1, f2, f3);
    r1.expect("append(1000) failed");
    let idx2 = r2.expect("append_notify(2000) failed");
    let idx3 = r3.expect("append_notify(3000) failed");

    let log_at_reply = decided_log(&leader_h).await;
    let decided_idx = leader_h.decided_idx().await;
    eprintln!(
        "[audit-unaccepted] call 3 resolved Ok({idx3}) (call 2 -> Ok({idx2})); \
         decided_idx = {decided_idx}, decided log = {log_at_reply:?}"
    );
    assert_eq!(log_at_reply.get(idx2 - 1), Some(&TestEntry(2000)));
    assert_eq!(
        log_at_reply.get(idx3 - 1),
        Some(&TestEntry(3000)),
        "call 3 was told its entry is decided at idx {idx3}; at that moment the decided \
         log is {log_at_reply:?} -- idx {idx3} holds {:?} and entry 3000 is not in the \
         decided log at all",
        log_at_reply.get(idx3 - 1)
    );
}
