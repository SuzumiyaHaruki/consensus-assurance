//! Audit probe #3 (added by the auditor, NOT part of the captured source).
//!
//! Question: when a node that has *no* knowledge of the current log is elected leader
//! (a "stale" new leader, e.g. one that was partitioned away while entries were accepted
//! and decided), does it adopt the log of the followers that are more up to date, without
//! losing or duplicating entries that were proposed under the previous leader's ballot?
//!
//! The captured suite never drives this shape: `sync_test`/`reconnect_test` always let the
//! *leader* push its log to followers, and every leader in those tests has the longest log.
//! Here node 3 is cut off while node 1 (leader) and node 2 accept and decide three entries,
//! then node 3 is forced to become leader with a higher ballot (its priority is higher), so
//! node 1 and node 2 must hand their suffix over in their `Promise` (`LogSync`) and node 3
//! must adopt it in `handle_majority_promises`.
//!
//! Everything is driven in-process by the public core API: no kompact, no sockets, no
//! timing dependence.

// Gated like the captured suite's own `Entry` scaffolding: this file's `TestEntry` does not
// carry the `unicache` associated types, so it is skipped when that feature is on.
#![cfg(not(feature = "unicache"))]

use omnipaxos::{
    messages::{sequence_paxos::PaxosMsg, Message},
    storage::{Entry, Snapshot},
    util::{LogEntry, NodeId},
    ClusterConfig, OmniPaxos, OmniPaxosConfig, ServerConfig,
};
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

type Op = OmniPaxos<TestEntry, MemoryStorage<TestEntry>>;

fn build(pid: NodeId, priority: u32) -> Op {
    let cluster_config = ClusterConfig {
        configuration_id: 1,
        nodes: vec![1, 2, 3],
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

/// Three nodes wired together in-process. `deliver_filtered` decides per message whether
/// it is delivered at all, which is how partitions are expressed.
struct Net {
    n1: Op,
    n2: Op,
    n3: Op,
}

impl Net {
    fn new() -> Self {
        Net {
            // Node 3 has the highest priority so that it can be forced to win the election
            // once it is finally allowed to talk to the others.
            n1: build(1, 1),
            n2: build(2, 1),
            n3: build(3, 2),
        }
    }

    /// Three nodes with node 1 holding the highest priority, so the BLE settles on node 1
    /// and stays there (used by the lost-`AcceptDecide` probes).
    fn with_node1_leading() -> Self {
        Net {
            n1: build(1, 1),
            n2: build(2, 0),
            n3: build(3, 0),
        }
    }

    fn pump(&mut self, rounds: usize, keep: &dyn Fn(&Message<TestEntry>) -> bool) {
        for _ in 0..rounds {
            self.tick_all();
            self.deliver_filtered(keep);
        }
    }

    fn tick_all(&mut self) {
        self.n1.tick();
        self.n2.tick();
        self.n3.tick();
    }

    fn deliver_filtered(&mut self, keep: &dyn Fn(&Message<TestEntry>) -> bool) {
        let mut from1 = Vec::new();
        let mut from2 = Vec::new();
        let mut from3 = Vec::new();
        self.n1.take_outgoing_messages(&mut from1);
        self.n2.take_outgoing_messages(&mut from2);
        self.n3.take_outgoing_messages(&mut from3);
        for msgs in [from1, from2, from3] {
            for m in msgs {
                if !keep(&m) {
                    continue;
                }
                match m.get_receiver() {
                    1 => self.n1.handle_incoming(m),
                    2 => self.n2.handle_incoming(m),
                    3 => self.n3.handle_incoming(m),
                    _ => {}
                }
            }
        }
    }

    fn deliver_all(&mut self) {
        self.deliver_filtered(&|_| true);
    }

    fn decided(&self, pid: NodeId) -> usize {
        match pid {
            1 => self.n1.get_decided_idx(),
            2 => self.n2.get_decided_idx(),
            _ => self.n3.get_decided_idx(),
        }
    }

    fn decided_values(&self, pid: NodeId) -> Vec<u64> {
        let op = match pid {
            1 => &self.n1,
            2 => &self.n2,
            _ => &self.n3,
        };
        op.read_decided_suffix(0)
            .unwrap_or_default()
            .into_iter()
            .filter_map(|e| match e {
                LogEntry::Decided(v) => Some(v.0),
                _ => None,
            })
            .collect()
    }
}

/// Drive the cluster until `pids` have each decided `want` entries, delivering only the
/// messages the caller allows. Appends go through whichever node reports itself leader in
/// the Accept phase.
fn pump_until(net: &mut Net, want: usize, leader: NodeId, keep: &dyn Fn(&Message<TestEntry>) -> bool) {
    let mut appended = 0u64;
    for _ in 0..5000 {
        net.tick_all();
        net.deliver_filtered(keep);
        let leader_op = match leader {
            1 => &mut net.n1,
            2 => &mut net.n2,
            _ => &mut net.n3,
        };
        if leader_op.get_current_leader() == Some((leader, true)) && appended < want as u64 {
            while appended < want as u64 {
                appended += 1;
                leader_op
                    .append(TestEntry(appended))
                    .expect("append on leader");
            }
        }
        if net.decided(1) >= want && net.decided(2) >= want {
            return;
        }
    }
    panic!(
        "cluster did not decide {want} entries (decided: 1={}, 2={}, 3={})",
        net.decided(1),
        net.decided(2),
        net.decided(3)
    );
}

/// Same "stale new leader" shape, but the partitioned node is in the *same* accepted round
/// with an empty log (it promised the old leader and received an `AcceptSync`, while every
/// `AcceptDecide` addressed to it was dropped). Its `Promise` metadata therefore ties on
/// `n_accepted` with the up-to-date followers, which exercises the other `log_sync` branch
/// in `handle_prepare` (`na == prep.n_accepted && accepted_idx > prep.accepted_idx`).
#[test]
fn stale_new_leader_in_same_round_adopts_follower_suffix() {
    let mut net = Net::new();
    let only_acceptdecide_to_3_dropped = |m: &Message<TestEntry>| {
        !(m.get_receiver() == 3
            && matches!(m, Message::SequencePaxos(p) if matches!(&p.msg, PaxosMsg::AcceptDecide(_))))
    };

    net.n1.try_become_leader();
    pump_until(&mut net, 3, 1, &only_acceptdecide_to_3_dropped);
    assert_eq!(net.decided(3), 0, "node 3 must not have decided anything");
    assert_eq!(
        net.n3.get_accepted_idx(),
        0,
        "node 3 must not have accepted any entry"
    );

    net.n3.try_become_leader();
    for _ in 0..5000 {
        net.tick_all();
        net.deliver_all();
        if net.decided(1) == 3 && net.decided(2) == 3 && net.decided(3) == 3 {
            break;
        }
    }
    let expected = vec![1u64, 2, 3];
    for pid in [1u64, 2, 3] {
        eprintln!(
            "[audit-adopt-same-round] pid {pid}: decided_idx {}, values {:?}",
            net.decided(pid),
            net.decided_values(pid)
        );
        assert_eq!(net.decided(pid), 3, "pid {pid} must decide all 3 entries");
        assert_eq!(
            net.decided_values(pid),
            expected,
            "pid {pid} decided log must be the three entries proposed under the previous \
             leader, in order"
        );
    }
}

#[test]
fn stale_new_leader_adopts_more_up_to_date_follower_log() {
    let mut net = Net::new();

    // ---- phase 1: node 1 leads; node 3 is partitioned away --------------------------
    net.n1.try_become_leader();
    // Only node 1 <-> node 2 traffic flows: node 3 learns nothing at all.
    let only_12 = |m: &Message<TestEntry>| {
        let (from, to) = (m.get_sender(), m.get_receiver());
        from != 3 && to != 3
    };
    pump_until(&mut net, 3, 1, &only_12);
    assert_eq!(net.decided(1), 3, "old leader must decide all 3 entries");
    assert_eq!(net.decided(2), 3, "follower must decide all 3 entries");
    assert_eq!(net.decided(3), 0, "partitioned node must know nothing");
    assert_eq!(
        net.n3.get_accepted_idx(),
        0,
        "partitioned node must have accepted nothing"
    );
    eprintln!(
        "[audit-adopt] before takeover: n1 decided {:?}, n2 decided {:?}, n3 decided {:?}",
        net.decided_values(1),
        net.decided_values(2),
        net.decided_values(3)
    );

    // ---- phase 2: node 3 is elected with a higher ballot -----------------------------
    net.n3.try_become_leader();
    for _ in 0..5000 {
        net.tick_all();
        net.deliver_all();
        if net.decided(1) == 3 && net.decided(2) == 3 && net.decided(3) == 3 {
            break;
        }
    }

    let expected = vec![1u64, 2, 3];
    for pid in [1u64, 2, 3] {
        eprintln!(
            "[audit-adopt] pid {pid}: decided_idx {}, values {:?}",
            net.decided(pid),
            net.decided_values(pid)
        );
        assert_eq!(
            net.decided(pid),
            3,
            "pid {pid} must have all 3 entries decided after the takeover"
        );
        assert_eq!(
            net.decided_values(pid),
            expected,
            "pid {pid} decided log must be exactly the three entries proposed under the \
             previous leader, in order"
        );
    }
}

/// Randomised but reproducible safety soak over the same harness: partitions are redrawn
/// every round, proposals are issued on whichever node reports itself leader, and a random
/// node is periodically forced to bump its ballot (`try_become_leader`), i.e. continuous
/// leader churn across partitions. Only *safety* invariants are asserted, so an
/// unconverged/frozen cluster cannot produce a false failure:
///
/// 1. agreement: any two nodes agree on every decided entry of their common prefix;
/// 2. no duplication: no entry value decided twice on any node;
/// 3. `decided_idx <= accepted_idx` on every node.
#[test]
fn random_partitions_and_leader_churn_preserve_safety_invariants() {
    for seed in [0x5eed_1234_9abc_def0u64, 0xdead_beef_0bad_f00du64, 1, 0xffff_ffff_ffff_ffff] {
        soak(seed);
    }
}

fn soak(seed: u64) {
    let mut rng = seed;
    let mut next = |rng: &mut u64| {
        *rng = rng
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        *rng >> 33
    };

    let mut net = Net::new();
    let mut value = 0u64;
    net.n1.try_become_leader();

    for round in 0..1000u64 {
        let (up1, up2, up3) = (
            next(&mut rng) % 3 != 0,
            next(&mut rng) % 3 != 0,
            next(&mut rng) % 3 != 0,
        );
        let keep = move |m: &Message<TestEntry>| {
            let up = |pid: NodeId| match pid {
                1 => up1,
                2 => up2,
                _ => up3,
            };
            let (from, to) = (m.get_sender(), m.get_receiver());
            from != to && up(from) && up(to)
        };

        net.tick_all();
        net.deliver_filtered(&keep);

        // Propose on a random node: only the current leader accepts locally, others take
        // the core's own ProposalForward path.
        let pid = (next(&mut rng) % 3) + 1;
        let leader_now = match pid {
            1 => net.n1.get_current_leader(),
            2 => net.n2.get_current_leader(),
            _ => net.n3.get_current_leader(),
        };
        if leader_now.map(|(p, accepted)| p == pid && accepted) == Some(true) {
            value += 1;
            match pid {
                1 => net.n1.append(TestEntry(value)).expect("append"),
                2 => net.n2.append(TestEntry(value)).expect("append"),
                _ => net.n3.append(TestEntry(value)).expect("append"),
            };
        }

        // Periodic leader churn.
        if round % 29 == 0 {
            match (next(&mut rng) % 3) + 1 {
                1 => net.n1.try_become_leader(),
                2 => net.n2.try_become_leader(),
                _ => net.n3.try_become_leader(),
            }
        }

        // Invariants.
        for pid in [1u64, 2, 3] {
            let decided = net.decided_values(pid);
            let mut sorted = decided.clone();
            sorted.sort_unstable();
            sorted.dedup();
            assert_eq!(
                sorted.len(),
                decided.len(),
                "round {round}: pid {pid} decided the same entry more than once: {decided:?}"
            );
            let accepted = match pid {
                1 => net.n1.get_accepted_idx(),
                2 => net.n2.get_accepted_idx(),
                _ => net.n3.get_accepted_idx(),
            };
            assert!(
                net.decided(pid) <= accepted,
                "round {round}: pid {pid} has decided_idx {} > accepted_idx {accepted}",
                net.decided(pid)
            );
        }
        let logs = [
            net.decided_values(1),
            net.decided_values(2),
            net.decided_values(3),
        ];
        let common = logs.iter().map(|l| l.len()).min().unwrap_or(0);
        for i in 0..common {
            assert!(
                logs[0][i] == logs[1][i] && logs[1][i] == logs[2][i],
                "round {round}: decided logs disagree at index {i}: {:?}",
                logs
            );
        }
    }

    eprintln!(
        "[audit-soak-core] seed {seed:#x}: p1 decided {} (accepted {}), p2 {} ({}), p3 {} ({})",
        net.decided(1),
        net.n1.get_accepted_idx(),
        net.decided(2),
        net.n2.get_accepted_idx(),
        net.decided(3),
        net.n3.get_accepted_idx()
    );
}

/// Deterministic, load-free probe for the mechanism behind finding 3: a single lost
/// `AcceptDecide` to a follower that is already in the Accept phase.
///
/// Node 3 is synced normally (so it is in `Phase::Accept` with sequence number `(1,1)`),
/// then the leader appends one entry and *every* `AcceptDecide` addressed to node 3 is
/// dropped, modelling a lost message. Nodes 1 and 2 form the write quorum, so the entry is
/// accepted and decided; the question is whether node 3 ever catches up on its own.
///
/// Per `resend_messages_leader` (no `AcceptDecide`/`AcceptSync` retry in `Phase::Accept`),
/// `resend_messages_follower` (`Phase::Accept => ()`) and `handle_sequence_num`
/// (`MessageStatus::Outdated => ()`, so an older-sequence message is silently ignored
/// instead of triggering `reconnected`), the expected answer is *no*: nothing re-sends the
/// missing accept and nothing detects that node 3 is behind. 5000 rounds are pumped, i.e.
/// ~250 resend periods (`resend_message_tick_timeout: 20`).
#[test]
fn lost_acceptdecide_leaves_a_lagging_follower_behind_forever() {
    let mut net = Net::with_node1_leading();
    net.n1.try_become_leader();
    let drop_acceptdecide_to_3 = |m: &Message<TestEntry>| {
        !(m.get_receiver() == 3
            && matches!(m, Message::SequencePaxos(p) if matches!(&p.msg, PaxosMsg::AcceptDecide(_))))
    };
    // Bring the cluster up so that node 3 has promised and accepted the sync.
    net.pump(60, &drop_acceptdecide_to_3);
    assert_eq!(
        net.n1.get_current_leader(),
        Some((1, true)),
        "node 1 should be leader in the Accept phase"
    );
    assert_eq!(
        net.n3.get_current_leader(),
        Some((1, true)),
        "node 3 should be following in the Accept phase"
    );
    assert_eq!(net.n3.get_accepted_idx(), 0);

    // One entry whose AcceptDecide to node 3 is lost -- with a trace of what still reaches
    // node 3, so the recovery path it uses is visible.
    let trace = std::cell::RefCell::new(Vec::<String>::new());
    let dropped = std::cell::Cell::new(0usize);
    let keep = |m: &Message<TestEntry>| {
        let (from, to) = (m.get_sender(), m.get_receiver());
        if let Message::SequencePaxos(p) = m {
            let kind = match &p.msg {
                PaxosMsg::Prepare(_) => "Prepare",
                PaxosMsg::Promise(_) => "Promise",
                PaxosMsg::AcceptSync(_) => "AcceptSync",
                PaxosMsg::AcceptDecide(_) => "AcceptDecide",
                PaxosMsg::Accepted(_) => "Accepted",
                PaxosMsg::Decide(_) => "Decide",
                PaxosMsg::PrepareReq(_) => "PrepareReq",
                PaxosMsg::NotAccepted(_) => "NotAccepted",
                PaxosMsg::ProposalForward(_) => "ProposalForward",
                _ => "other",
            };
            if trace.borrow().len() < 40 {
                trace.borrow_mut().push(format!("{from}->{to} {kind}"));
            }
            if to == 3 && (kind == "AcceptDecide" || kind == "Decide") {
                dropped.set(dropped.get() + 1);
                return false;
            }
        }
        true
    };
    net.n1.append(TestEntry(1)).expect("append on leader");
    for chunk in 0..500 {
        net.pump(10, &keep);
        if chunk < 12 {
            eprintln!(
                "[audit-lost-accept] round {}: n1 decided {} accepted {} | n3 decided {} \
                 accepted {} leader {:?}",
                (chunk + 1) * 10,
                net.decided(1),
                net.n1.get_accepted_idx(),
                net.decided(3),
                net.n3.get_accepted_idx(),
                net.n3.get_current_leader(),
            );
        }
        if net.decided(3) == 1 {
            eprintln!(
                "[audit-lost-accept] node 3 caught up after {} rounds; AcceptDecide dropped: \
                 {}\n[audit-lost-accept] message trace: {:?}",
                (chunk + 1) * 10,
                dropped.get(),
                trace.borrow()
            );
            break;
        }
    }

    let (d1, d2, d3) = (net.decided(1), net.decided(2), net.decided(3));
    eprintln!(
        "[audit-lost-accept] after 5000 rounds: decided 1={d1} {:?}, 2={d2} {:?}, 3={d3} {:?}",
        net.decided_values(1),
        net.decided_values(2),
        net.decided_values(3)
    );
    assert_eq!(d1, 1, "leader must decide the entry (quorum with node 2)");
    assert_eq!(d2, 1, "node 2 must decide the entry");
    assert_eq!(
        d3, 1,
        "node 3 must eventually be synced up to the leader's log: a lost AcceptDecide has \
         to be recovered by the resend/detection machinery, not left for the user"
    );
}

/// The documented remedy for the case above: when the transport reports the connection as
/// re-established, `OmniPaxos::reconnected(pid)` makes the follower re-request the leader's
/// log (`Phase::Recover` -> `PrepareReq` -> `Prepare` -> `AcceptSync`) and it catches up.
/// This test pins down that the gap in the previous test is specifically "no self-healing",
/// not "no way to fix it".
#[test]
fn lost_acceptdecide_is_repaired_by_reconnected() {
    let mut net = Net::with_node1_leading();
    net.n1.try_become_leader();
    // Same isolation as the previous test: node 3 gets neither the accept nor the following
    // decide, so nothing nudges it and it is genuinely behind.
    let drop_acceptdecide_to_3 = |m: &Message<TestEntry>| {
        !(m.get_receiver() == 3
            && matches!(m, Message::SequencePaxos(p)
                if matches!(&p.msg, PaxosMsg::AcceptDecide(_) | PaxosMsg::Decide(_))))
    };
    net.pump(60, &drop_acceptdecide_to_3);
    net.n1.append(TestEntry(1)).expect("append on leader");
    net.pump(200, &drop_acceptdecide_to_3);
    assert_eq!(net.decided(3), 0, "node 3 is behind before the nudge");

    // Transport reports the connection to the leader as re-established.
    net.n3.reconnected(1);
    net.pump(2000, &|_| true);
    eprintln!(
        "[audit-lost-accept-fix] after reconnected(1): node 3 decided {} {:?}",
        net.decided(3),
        net.decided_values(3)
    );
    assert_eq!(net.decided(3), 1, "node 3 must catch up after reconnected()");
    assert_eq!(net.decided_values(3), vec![1]);
}
