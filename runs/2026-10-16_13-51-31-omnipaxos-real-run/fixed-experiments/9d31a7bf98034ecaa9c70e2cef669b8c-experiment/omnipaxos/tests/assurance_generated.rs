//! Deterministic in-process simulation of the core Sequence Paxos for one sourced
//! question: if a follower's `Accepted` reply is lost, is there any timer-driven or
//! self-initiated repair, or does the quorum-accepted entry stay undecided until an
//! unrelated new proposal arrives?
//!
//! 2 nodes ({1,2}) so the write quorum is the leader's own acceptance plus exactly
//! one follower receipt: dropping that single receipt leaves the entry unaccepted
//! *from the leader's point of view* while both nodes really hold the entry.
//!
//! Three cases share one simulator:
//!   A `lost_accepted_leaves_entry_undecided` - drop the follower's Accepted, then
//!     run a window of 100 resend periods of ticks: no decision, no leadership
//!     change, both nodes still holding the entry.
//!   B `delivered_accepted_decides` (control) - identical, but the receipt is
//!     delivered, and the entry is decided inside a bounded tick window.
//!   C `a_later_proposal_is_the_only_repair` - continue case A's state and append a
//!     second entry: only then does the earlier entry become decided (the new
//!     receipt advertises an accepted index that covers it).

use std::collections::VecDeque;

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

const ELECTION_TICKS: u64 = 3;
const RESEND_TICKS: u64 = 5;
/// The window each case is given, expressed in resend periods: 100 resends of the
/// leader and the follower, i.e. far more opportunities than one repair attempt.
const RESEND_PERIODS: usize = 100;

fn node(pid: NodeId) -> Op {
    #[allow(clippy::needless_update)]
    let server_config = ServerConfig {
        pid,
        election_tick_timeout: ELECTION_TICKS,
        resend_message_tick_timeout: RESEND_TICKS,
        buffer_size: 100,
        batch_size: 1,
        flush_batch_tick_timeout: 100,
        // Node 1 always wins the election, so the run is deterministic.
        leader_priority: if pid == 1 { 1 } else { 0 },
        ..Default::default()
    };
    OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id: 1,
            nodes: vec![1, 2],
            flexible_quorum: None,
        },
        server_config,
    }
    .build(MemoryStorage::default())
    .expect("config build")
}

struct Sim {
    ops: Vec<(NodeId, Op)>,
    inflight: VecDeque<(NodeId, Message<TestEntry>)>,
    /// type name -> number of messages produced
    produced: Vec<(String, usize)>,
    /// type name -> number of messages deliberately dropped
    dropped: Vec<(String, usize)>,
    /// type name -> messages produced after the deliberate drop, i.e. what the
    /// protocol itself put on the wire while nothing new was proposed.
    after_drop: Vec<(String, usize)>,
}

fn msg_kind<T>(m: &Message<T>) -> &'static str
where
    T: Entry,
{
    match m {
        Message::SequencePaxos(p) => match &p.msg {
            PaxosMsg::PrepareReq(_) => "PrepareReq",
            PaxosMsg::Prepare(_) => "Prepare",
            PaxosMsg::Promise(_) => "Promise",
            PaxosMsg::AcceptSync(_) => "AcceptSync",
            PaxosMsg::AcceptDecide(_) => "AcceptDecide",
            PaxosMsg::Accepted(_) => "Accepted",
            PaxosMsg::NotAccepted(_) => "NotAccepted",
            PaxosMsg::Decide(_) => "Decide",
            PaxosMsg::ProposalForward(_) => "ProposalForward",
            PaxosMsg::Compaction(_) => "Compaction",
            PaxosMsg::AcceptStopSign(_) => "AcceptStopSign",
            PaxosMsg::ForwardStopSign(_) => "ForwardStopSign",
        },
        Message::BLE(_) => "BLE",
        #[cfg(feature = "async_runtime")]
        Message::AsyncRuntime(_) => "AsyncRuntime",
    }
}

fn bump(counts: &mut Vec<(String, usize)>, name: &str) {
    match counts.iter_mut().find(|(n, _)| n == name) {
        Some((_, c)) => *c += 1,
        None => counts.push((name.to_string(), 1)),
    }
}

impl Sim {
    fn new() -> Self {
        Sim {
            ops: vec![(1, node(1)), (2, node(2))],
            inflight: VecDeque::new(),
            produced: Vec::new(),
            dropped: Vec::new(),
            after_drop: Vec::new(),
        }
    }

    fn op(&self, pid: NodeId) -> &Op {
        &self
            .ops
            .iter()
            .find(|(p, _)| *p == pid)
            .expect("known pid")
            .1
    }

    fn op_mut(&mut self, pid: NodeId) -> &mut Op {
        &mut self
            .ops
            .iter_mut()
            .find(|(p, _)| *p == pid)
            .expect("known pid")
            .1
    }

    /// Collect one node's outgoing messages; `drop_accepted` counts how many
    /// `Accepted` messages to discard (the loss to be probed). Messages are
    /// delivered immediately afterwards (see `step`) so that heartbeat replies land
    /// in the round that asked for them and no leadership churn is provoked by the
    /// harness's own cadence.
    fn collect(&mut self, pid: NodeId, mut drop_accepted: usize) {
        let mut buf: Vec<Message<TestEntry>> = Vec::new();
        self.op_mut(pid).take_outgoing_messages(&mut buf);
        for m in buf.drain(..) {
            let kind = msg_kind(&m);
            bump(&mut self.produced, kind);
            if self.dropped_accepted() > 0 {
                bump(&mut self.after_drop, kind);
            }
            if kind == "Accepted" && drop_accepted > 0 {
                drop_accepted -= 1;
                bump(&mut self.dropped, kind);
                continue;
            }
            let to = m.get_receiver();
            self.inflight.push_back((to, m));
        }
    }

    fn deliver_all(&mut self) {
        while let Some((to, m)) = self.inflight.pop_front() {
            self.op_mut(to).handle_incoming(m);
        }
    }

    /// One logical step: tick a node, send what it produced, deliver it, then do the
    /// same for the other node. Delivery after each node keeps the BLE round the
    /// requester is in aligned with the replies it receives.
    fn step(&mut self, drop_accepted: usize) {
        for pid in [1u64, 2] {
            self.op_mut(pid).tick();
            self.collect(pid, if drop_accepted > 0 && self.dropped_accepted() == 0 { 1 } else { 0 });
            self.deliver_all();
        }
    }

    fn run(&mut self, steps: usize, drop_accepted: usize) {
        for _ in 0..steps {
            self.step(drop_accepted);
        }
    }

    fn dropped_accepted(&self) -> usize {
        self.dropped
            .iter()
            .find(|(n, _)| n == "Accepted")
            .map(|(_, c)| *c)
            .unwrap_or(0)
    }

    /// Run until node 1 is leader with every node in the accept phase.
    fn elect(&mut self, max_steps: usize) -> bool {
        for _ in 0..max_steps {
            self.step(0);
            if self.op(1).get_current_leader() == Some((1, true))
                && self.op(2).get_current_leader() == Some((1, true))
            {
                return true;
            }
        }
        false
    }

    fn counts(&self, list: &[(String, usize)]) -> String {
        list.iter()
            .map(|(n, c)| format!("{n}:{c}"))
            .collect::<Vec<_>>()
            .join(",")
    }
}

fn emit(line: &str) {
    println!("CA_EVENT {line}");
}

fn undecided_entry(op: &Op, idx: usize) -> bool {
    matches!(op.read(idx), Some(LogEntry::Undecided(_)))
}

/// Case A: the follower's receipt is lost and nothing else is proposed.
#[test]
fn lost_accepted_leaves_entry_undecided() {
    let mut sim = Sim::new();
    assert!(sim.elect(500), "setup: no stable leader");

    let leader_append = sim.op_mut(1).append(TestEntry(1));
    assert!(leader_append.is_ok(), "setup: leader append failed");

    // Whole window: the follower's Accepted is dropped, everything else is delivered.
    sim.run(RESEND_PERIODS * RESEND_TICKS as usize, 1);

    let leader_decided = sim.op(1).get_decided_idx();
    let follower_decided = sim.op(2).get_decided_idx();
    let follower_accepted = sim.op(2).get_accepted_idx();
    let follower_holds_entry = undecided_entry(sim.op(2), 0);
    let leader_still_leader = sim.op(1).get_current_leader() == Some((1, true));
    let accept_decide_total = sim
        .produced
        .iter()
        .find(|(n, _)| n == "AcceptDecide")
        .map(|(_, c)| *c)
        .unwrap_or(0);
    emit(&format!(
        "{{\"event\":\"lost_accepted_window\",\"steps\":{},\"resend_periods\":{RESEND_PERIODS},\"produced\":\"{}\",\"dropped\":\"{}\",\"after_drop\":\"{}\",\"accept_decide_total\":{accept_decide_total},\"leader_decided_idx\":{leader_decided},\"follower_decided_idx\":{follower_decided},\"follower_accepted_idx\":{follower_accepted},\"follower_holds_undecided_entry\":{follower_holds_entry},\"leader_still_stable\":{leader_still_leader}}}",
        RESEND_PERIODS * RESEND_TICKS as usize,
        sim.counts(&sim.produced),
        sim.counts(&sim.dropped),
        sim.counts(&sim.after_drop)
    ));

    assert_eq!(
        sim.dropped_accepted(),
        1,
        "probe did not drop exactly the follower's Accepted: dropped={}",
        sim.counts(&sim.dropped)
    );
    assert_eq!(
        follower_accepted, 1,
        "follower never accepted the entry, so the quorum premise is missing"
    );
    assert!(
        follower_holds_entry,
        "follower does not hold the entry as Undecided at index 0"
    );
    // Environment assertion, not an outcome prediction: no client proposal was made
    // after the drop, so the only AcceptDecide in the whole run is the first one. The
    // outcome (decided or not) is the measured operand above.
    assert_eq!(
        accept_decide_total, 1,
        "the window contained more than one AcceptDecide, so a new proposal was effectively made"
    );

    // Case C on the same state: a later unrelated proposal also decides the earlier
    // entry (whatever the window above already showed).
    let repair = sim.op_mut(1).append(TestEntry(2));
    assert!(repair.is_ok(), "second append failed");
    let mut steps_until_decided = None;
    for s in 0..RESEND_PERIODS * RESEND_TICKS as usize / 2 {
        sim.step(0);
        if sim.op(1).get_decided_idx() >= 2 {
            steps_until_decided = Some(s + 1);
            break;
        }
    }
    emit(&format!(
        "{{\"event\":\"later_proposal_repairs\",\"steps_until_decided\":{},\"leader_decided_idx\":{},\"follower_decided_idx\":{}}}",
        steps_until_decided.map(|s| s.to_string()).unwrap_or_else(|| "null".to_string()),
        sim.op(1).get_decided_idx(),
        sim.op(2).get_decided_idx()
    ));
    assert!(
        sim.op(1).get_decided_idx() >= 2,
        "the later proposal did not decide both entries (leader decided {})",
        sim.op(1).get_decided_idx()
    );
}

/// Case B (control): identical, but the follower's receipt is delivered.
#[test]
fn delivered_accepted_decides() {
    let mut sim = Sim::new();
    assert!(sim.elect(500), "setup: no stable leader");
    assert!(sim.op_mut(1).append(TestEntry(1)).is_ok(), "append failed");

    let mut steps_until_decided = None;
    for s in 0..RESEND_PERIODS * RESEND_TICKS as usize {
        sim.step(0);
        if sim.op(1).get_decided_idx() >= 1 {
            steps_until_decided = Some(s + 1);
            break;
        }
    }
    // Let the leader's Decide reach the follower before reading its decided index.
    for _ in 0..20 {
        sim.step(0);
    }
    emit(&format!(
        "{{\"event\":\"delivered_accepted_decides\",\"steps_until_decided\":{},\"produced\":\"{}\",\"leader_decided_idx\":{},\"follower_decided_idx\":{}}}",
        steps_until_decided.map(|s| s.to_string()).unwrap_or_else(|| "null".to_string()),
        sim.counts(&sim.produced),
        sim.op(1).get_decided_idx(),
        sim.op(2).get_decided_idx()
    ));
    assert!(
        sim.op(1).get_decided_idx() >= 1,
        "control: entry was not decided even though the receipt was delivered"
    );
    assert!(
        sim.op(2).get_decided_idx() >= 1,
        "control: follower never learned the decision"
    );
}
