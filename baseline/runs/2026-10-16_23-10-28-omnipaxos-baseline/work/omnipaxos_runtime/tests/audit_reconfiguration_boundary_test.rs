//! Audit probe #4 (added by the auditor, NOT part of the captured source).
//!
//! Question: at the reconfiguration boundary, do the core log, the runtime's decided-log
//! subscriber and the `OmniPaxosEvent` stream agree on where the StopSign is and deliver it
//! exactly once?
//!
//! The captured suite never starts an actor on an already-stopped cluster and never
//! subscribes across a StopSign (`append_notify_resolves_propose_error_immediately` checks
//! the propose error but not the log/event boundary). A stopped cluster is also exactly the
//! hand-off point to the next configuration, so getting the index/flag wrong there matters.

#![cfg(all(feature = "tokio_runtime", not(feature = "unicache")))]

use std::time::Duration;

use omnipaxos::{
    storage::{Entry, Snapshot},
    util::{LogEntry, NodeId},
    ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig,
};
use omnipaxos_runtime::{spawn_actor, OmniPaxosEvent, OmniPaxosHandle, RuntimeConfig, TokioRuntime};
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

fn build(pid: NodeId, priority: u32) -> Op {
    let cluster_config = ClusterConfig {
        configuration_id: 1,
        nodes: vec![1, 2],
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

/// Hand-driven two-node cluster: decide `n` entries, then reconfigure to configuration 2 and
/// pump until both nodes have observed the reconfiguration.
fn decided_then_reconfigured(n: u64) -> (Op, Op) {
    let mut a = build(1, 1);
    let mut b = build(2, 0);
    a.try_become_leader();
    let mut next = 0u64;
    let mut reconfigured = false;
    for _ in 0..5000 {
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
        if !reconfigured {
            if a.get_current_leader() == Some((1, true)) {
                while next < n {
                    a.append(TestEntry(200 + next)).expect("append");
                    next += 1;
                }
                if a.get_decided_idx() == n as usize {
                    a.reconfigure(
                        ClusterConfig {
                            configuration_id: 2,
                            nodes: vec![1, 2],
                            flexible_quorum: None,
                        },
                        Some(vec![7, 8, 9]),
                    )
                    .expect("reconfigure");
                    reconfigured = true;
                }
            }
        } else if a.is_reconfigured().is_some() && b.is_reconfigured().is_some() {
            return (a, b);
        }
    }
    panic!(
        "cluster did not reach a decided reconfiguration (n1 decided {}, reconfigured {}, n2 \
         decided {})",
        a.get_decided_idx(),
        a.is_reconfigured().is_some(),
        b.get_decided_idx()
    );
}

#[tokio::test]
async fn stopsign_boundary_is_consistent_across_log_subscription_and_events() {
    let n = 3u64;
    let (a, b) = decided_then_reconfigured(n);

    // ---- core view -------------------------------------------------------------------
    let decided = a.get_decided_idx();
    let stop_sign_idx = n as usize + 1;
    assert_eq!(
        decided, stop_sign_idx,
        "the decided index must be the StopSign's index"
    );
    let ss = a.is_reconfigured().expect("a must report itself reconfigured");
    assert_eq!(
        ss.next_config.configuration_id, 2,
        "StopSign must carry the next configuration"
    );
    assert_eq!(ss.metadata.as_deref(), Some(&[7u8, 8, 9][..]));

    let suffix = a.read_decided_suffix(0).expect("decided suffix");
    let last = suffix.last().expect("non-empty suffix");
    assert!(
        matches!(last, LogEntry::StopSign(_, true)),
        "last decided entry must be a decided StopSign, got {last:?}"
    );
    assert_eq!(
        suffix.len(),
        decided,
        "the decided suffix must contain exactly one item per decided position: {:?}",
        suffix
    );
    assert_eq!(
        a.read(stop_sign_idx - 1).map(|e| matches!(e, LogEntry::StopSign(_, true))),
        Some(true),
        "reading the StopSign by index must return it"
    );
    eprintln!(
        "[audit-stopsign] core: decided_idx {decided}, suffix items {}, last {:?}",
        suffix.len(),
        last
    );

    // ---- runtime view ----------------------------------------------------------------
    let cfg = RuntimeConfig {
        tick_period: Duration::from_millis(20),
        egress_period: Duration::from_millis(1),
        ..Default::default()
    };
    let h: OmniPaxosHandle<TestEntry> =
        spawn_actor::<TestEntry, MemoryStorage<TestEntry>, TokioRuntime>(a, cfg);
    let events = h.subscribe_events();
    let rx = h.subscribe_decided(0).await;

    let mut items = Vec::new();
    let mut reconfigured_event = None;
    let mut decided_events: Vec<usize> = Vec::new();
    let mut other_events = 0usize;
    let deadline = tokio::time::Instant::now() + Duration::from_millis(400);
    while tokio::time::Instant::now() < deadline {
        if let Ok(Ok(item)) = timeout(Duration::from_millis(20), rx.recv()).await {
            items.push(item);
        }
        if let Ok(Ok(ev)) = timeout(Duration::from_millis(1), events.recv()).await {
            match ev {
                OmniPaxosEvent::Reconfigured { stop_sign_idx } => {
                    reconfigured_event = Some(stop_sign_idx)
                }
                OmniPaxosEvent::Decided { new_decided_idx } => {
                    decided_events.push(new_decided_idx)
                }
                _ => other_events += 1,
            }
        }
    }

    let summary: Vec<String> = items
        .iter()
        .map(|e| match e {
            LogEntry::Decided(v) => format!("Decided({})", v.0),
            LogEntry::Undecided(v) => format!("Undecided({})", v.0),
            LogEntry::Trimmed(i) => format!("Trimmed({i})"),
            LogEntry::Snapshotted(s) => format!("Snapshotted({})", s.trimmed_idx),
            LogEntry::StopSign(_, decided) => format!("StopSign(decided={decided})"),
        })
        .collect();
    eprintln!(
        "[audit-stopsign] runtime: subscriber got {} items {summary:?}; Reconfigured event \
         {reconfigured_event:?}",
        items.len()
    );

    assert_eq!(
        items.len(),
        decided,
        "subscriber must receive one item per decided position: {summary:?}"
    );
    let stop_signs = items
        .iter()
        .filter(|e| matches!(e, LogEntry::StopSign(_, true)))
        .count();
    assert_eq!(
        stop_signs, 1,
        "the StopSign must be delivered exactly once: {summary:?}"
    );
    assert!(
        matches!(items.last(), Some(LogEntry::StopSign(_, true))),
        "the StopSign must be the last item delivered: {summary:?}"
    );
    let undecided = items
        .iter()
        .filter(|e| matches!(e, LogEntry::Undecided(_)))
        .count();
    assert_eq!(undecided, 0, "no decided entry may be marked undecided");
    assert_eq!(
        reconfigured_event,
        Some(stop_sign_idx),
        "the Reconfigured event must report the StopSign's index"
    );
    // The actor starts on a log that is *already* decided up to `decided`: per the event's
    // documented meaning ("the decided index advanced") it must not announce the backlog, and
    // nothing can advance here because the configuration is stopped.
    assert!(
        decided_events.is_empty(),
        "no Decided event may be emitted for entries that were already decided before the \
         actor started (got {decided_events:?}; other events: {other_events})"
    );
    assert_eq!(
        h.decided_idx().await,
        decided,
        "the recovered decided index must be reported"
    );

    // The peer must agree on the same decided prefix.
    let peer = b.read_decided_suffix(0).expect("peer suffix");
    let peer_values: Vec<LogEntry<TestEntry>> = peer;
    let own_values: Vec<LogEntry<TestEntry>> = items;
    assert_eq!(
        format!("{peer_values:?}"),
        format!("{own_values:?}"),
        "peer's decided log must match what the subscriber received"
    );
}
